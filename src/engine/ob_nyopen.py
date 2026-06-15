"""OB_NYOPEN_BULL_1M — NY-open bullish order-block reversion (1m).

Implements the vault entry's description verbatim:
  - OB = the last down candle before a >= 1.5*ATR(14) up-displacement candle that
    breaks the prior 10-bar high, formed in the 09:30-11:00 ET window.
  - Enter long at the first SAME-DAY tap of the zone (price trades back to the
    zone's proximal/top edge).
  - Stop = 1 pt below zone low.
  - Target = entry + 2*risk, risk = max(zone_height, 3).
  - 120-min max hold (exit at market if neither stop nor target hit).
  - Friction 1pt is applied by the harness.

Shared backtest/live engine: implements on_bar(o,h,l,c,daily_gap,daily_rising)
like the other engines. It is time-aware (session window, same-day tap, 120-min
hold), and the harness does not pass the bar timestamp into on_bar() — so the
timestamp is delivered through the harness's daily_gap_fn hook via feed_ts(),
which is called with ts immediately before on_bar(). Use:

    eng = OBNyOpenEngine()
    trades, stats = run_backtest(bars, eng, friction_pts=1.0, daily_gap_fn=eng.feed_ts)

ATR = simple rolling-mean (repo convention, reused from v4._Atr).
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
class OBConfig:
    atr_len: int = 14
    disp_atr_mult: float = 1.5         # up-displacement body >= 1.5 * ATR
    breakout_lookback: int = 10        # must break prior 10-bar high
    form_start: time = time(9, 30)     # ET formation window
    form_end: time = time(11, 0)
    stop_pad: float = 1.0              # stop = zone_low - 1pt
    risk_floor: float = 3.0            # risk = max(zone_height, 3)
    target_R: float = 2.0              # target = entry + 2*risk
    max_hold_min: int = 120


class OBNyOpenEngine:
    def __init__(self, cfg: OBConfig = OBConfig()):
        self.cfg = cfg
        self._atr = _Atr(cfg.atr_len)
        self._prior_highs = deque(maxlen=cfg.breakout_lookback)  # highs of prior N bars
        self._recent = deque(maxlen=cfg.breakout_lookback + 5)   # prior bars (for OB lookup)
        self._cur_ts: Optional[datetime] = None
        self._cur_day = None
        self.zones: list[dict] = []      # active same-day zones not yet entered
        self.in_pos = False
        self.entry = self.stop = self.target = 0.0
        self.entry_ts: Optional[datetime] = None

    def feed_ts(self, ts):
        """Harness daily_gap_fn hook — delivers the bar timestamp, returns no gap."""
        self._cur_ts = ts
        return (0.0, False)

    def _in_window(self, et: datetime) -> bool:
        return self.cfg.form_start <= et.timetz().replace(tzinfo=None) < self.cfg.form_end

    def on_bar(self, o: float, h: float, l: float, c: float,
               daily_gap: float = 0.0, daily_rising: bool = False) -> Optional[dict]:
        ts = self._cur_ts
        et = ts.astimezone(ET)
        day = et.date()
        atr = self._atr.update(h, l, c)

        if day != self._cur_day:          # new session day: same-day zones expire
            self._cur_day = day
            self.zones = []

        decision = None

        # 1) manage an open position (exits): stop checked before target (conservative)
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
                decision = {"signal": Signal.EXIT_LONG, "price": exit_px, "qty": 1}
                self._record(o, h, l, c)
                return decision

        # 2) if flat, enter on the first same-day tap of an active zone
        if not self.in_pos:
            for z in self.zones:
                if z["day"] == day and l <= z["high"]:
                    zone_height = z["high"] - z["low"]
                    risk = max(zone_height, self.cfg.risk_floor)
                    self.entry = z["high"]
                    self.stop = z["low"] - self.cfg.stop_pad
                    self.target = self.entry + self.cfg.target_R * risk
                    self.entry_ts = ts
                    self.in_pos = True
                    self.zones.remove(z)
                    decision = {"signal": Signal.ENTER_LONG, "price": self.entry, "qty": 1}
                    self._record(o, h, l, c)
                    return decision

        # 3) detect a new OB zone on this (displacement) bar
        if atr is not None and len(self._prior_highs) == self.cfg.breakout_lookback:
            if (self._in_window(et) and c > o and (c - o) >= self.cfg.disp_atr_mult * atr
                    and h > max(self._prior_highs)):
                ob = next((b for b in reversed(self._recent) if b["c"] < b["o"]), None)
                if ob is not None:
                    self.zones.append({"low": ob["l"], "high": ob["h"], "day": day})

        self._record(o, h, l, c)
        return decision

    def _record(self, o: float, h: float, l: float, c: float):
        """Append the just-processed bar to history (called once per bar, after detection)."""
        self._recent.append({"o": o, "h": h, "l": l, "c": c})
        self._prior_highs.append(h)
