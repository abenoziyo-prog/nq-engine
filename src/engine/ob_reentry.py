"""OB_NYOPEN_REENTRY_1M — NY-open bullish OB reversion WITH re-entry (1m).

Per the vault spec (the re-entry variant of the FALSIFIED single-entry OB):
  - OB = last down candle before a single-bar up-displacement (body >= 1.5*ATR(14))
    that breaks the prior 10-bar high, formed 09:30-11:00 ET.
  - Zone = [OB low, OB high]. Zone stays VALID until a 1m CLOSE below zone low
    (intrabar wicks/taps do NOT invalidate). No fixed day expiry — literal per spec.
  - RE-ENTRY: after a zone is entered, it re-arms once price trades fully back above
    the zone top; each subsequent re-tap of a still-valid zone is a NEW long entry.
  - Entry at zone top; stop 1pt below zone low; target = entry + 2*max(zone_height,3);
    120-min max hold per entry; friction 1pt (harness).
  - SINGLE position at a time (harness constraint): taps that occur while a position
    is open, or a second armed-zone tap on the same bar, are SKIPPED and counted
    (self.skipped) so the overcounting risk is visible.

Time-aware -> driven through the unmodified harness via the daily_gap_fn(ts) hook
(feed_ts). ATR = simple rolling-mean (reused from v4._Atr).
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from src.engine.v4 import _Atr

ET = ZoneInfo("America/New_York")


class Signal(str, Enum):
    NONE = "NONE"
    ENTER_LONG = "ENTER_LONG"
    EXIT_LONG = "EXIT_LONG"


@dataclass
class OBReentryConfig:
    atr_len: int = 14
    disp_atr_mult: float = 1.5
    breakout_lookback: int = 10
    form_start: time = time(9, 30)
    form_end: time = time(11, 0)
    stop_pad: float = 1.0
    risk_floor: float = 3.0
    target_R: float = 2.0
    max_hold_min: int = 120


class OBReentryEngine:
    def __init__(self, cfg: OBReentryConfig = OBReentryConfig()):
        self.cfg = cfg
        self._atr = _Atr(cfg.atr_len)
        self._prior_highs = deque(maxlen=cfg.breakout_lookback)
        self._recent = deque(maxlen=cfg.breakout_lookback + 5)
        self._cur_ts: Optional[datetime] = None
        self.zones: list[dict] = []          # {low, high, id, armed}
        self._zid = 0
        self.in_pos = False
        self.entry = self.stop = self.target = 0.0
        self.entry_ts: Optional[datetime] = None
        self._entry_zid: Optional[int] = None
        # instrumentation
        self.skipped = 0                      # taps skipped (in-position or same-bar contention)
        self.entries_per_zone: dict[int, int] = {}

    def feed_ts(self, ts):
        self._cur_ts = ts
        return (0.0, False)

    def _in_window(self, et: datetime) -> bool:
        return self.cfg.form_start <= et.timetz().replace(tzinfo=None) < self.cfg.form_end

    def on_bar(self, o, h, l, c, daily_gap=0.0, daily_rising=False) -> Optional[dict]:
        ts = self._cur_ts
        et = ts.astimezone(ET)
        atr = self._atr.update(h, l, c)
        decision = None

        # 1) manage open position
        if self.in_pos:
            exit_px = None
            if l <= self.stop:
                exit_px = self.stop
            elif h >= self.target:
                exit_px = self.target
            elif (ts - self.entry_ts) >= timedelta(minutes=self.cfg.max_hold_min):
                exit_px = c
            if exit_px is not None:
                self.in_pos = False
                self._entry_zid = None
                decision = {"signal": Signal.EXIT_LONG, "price": exit_px, "qty": 1}
                self._finish(o, h, l, c)
                return decision

        # 2) re-arm zones where price has traded fully back above the top
        for z in self.zones:
            if not z["armed"] and l > z["high"]:
                z["armed"] = True

        # 3) entry on first armed-zone tap (if flat); count other simultaneous taps as skipped
        if not self.in_pos:
            entered = False
            for z in self.zones:
                if z["armed"] and l <= z["high"]:
                    if not entered:
                        zh = z["high"] - z["low"]
                        risk = max(zh, self.cfg.risk_floor)
                        self.entry = z["high"]
                        self.stop = z["low"] - self.cfg.stop_pad
                        self.target = self.entry + self.cfg.target_R * risk
                        self.entry_ts = ts
                        self.in_pos = True
                        z["armed"] = False
                        self._entry_zid = z["id"]
                        self.entries_per_zone[z["id"]] = self.entries_per_zone.get(z["id"], 0) + 1
                        decision = {"signal": Signal.ENTER_LONG, "price": self.entry, "qty": 1}
                        entered = True
                    else:
                        self.skipped += 1     # second armed tap same bar
        else:
            # taps while in position are skipped (logged)
            for z in self.zones:
                if z["armed"] and l <= z["high"]:
                    self.skipped += 1

        # 4) detect a new OB zone on this (displacement) bar
        if atr is not None and len(self._prior_highs) == self.cfg.breakout_lookback:
            if (self._in_window(et) and c > o and (c - o) >= self.cfg.disp_atr_mult * atr
                    and h > max(self._prior_highs)):
                ob = next((b for b in reversed(self._recent) if b["c"] < b["o"]), None)
                if ob is not None:
                    self._zid += 1
                    self.zones.append({"low": ob["l"], "high": ob["h"], "id": self._zid, "armed": True})

        self._finish(o, h, l, c)
        return decision

    def _finish(self, o, h, l, c):
        # invalidate zones on a CLOSE below zone low (applies to future bars)
        if self.zones:
            self.zones = [z for z in self.zones if not (c < z["low"] and z["id"] != self._entry_zid)]
        self._recent.append({"o": o, "h": h, "l": l, "c": c})
        self._prior_highs.append(h)
