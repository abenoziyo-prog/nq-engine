"""LVL_IMB — displacement-imbalance order-block zone engine (long-only, 5m).

Implements the LVL_IMB_LONDON_5M / LVL_IMB_ASIA_5M vault spec (configurable
formation session):
  - Zone detection: a bullish displacement leg (3-bar) that moves >= 1.5*ATR(14),
    breaks the prior 10-bar swing high, AND contains a bullish FVG (imbalance:
    bar-i low > bar-(i-2) high), formed in the configured session (London/Asia).
    The order block = the last down-close candle before the leg; zone = its full
    [low, high] range.
  - Survival (multi-touch): a zone stays valid until a 5m CLOSE below its far edge
    (zone low); intrabar taps do not invalidate.
  - Entry: long at the zone MIDPOINT on the first NY-session (NY_AM/NY_PM) tap.
  - Stop: structural = far edge - 0.75 * zone size (= zone_low - 0.75*height).
  - Exit: hold through the structural stop until +1R, then trail under the 6-bar
    swing low (ratchet). No EOD flatten (hold-through-validity).
  - Filter: only enter when close is above a RISING 200EMA(5m).
  - Long-only, single position at a time (harness constraint; overlapping taps
    skipped and counted).

Time-aware -> run through the unmodified harness via the daily_gap_fn(ts) hook
(feed_ts). ATR/EMA = simple conventions reused from v4.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from src.engine.v4 import _Atr, _Ema
from src.data.model import Session, tag_session


class Signal(str, Enum):
    NONE = "NONE"
    ENTER_LONG = "ENTER_LONG"
    EXIT_LONG = "EXIT_LONG"


@dataclass
class LvlImbConfig:
    formation_session: Session = Session.LONDON
    atr_len: int = 14
    disp_mult: float = 1.5
    swing_lookback: int = 10
    ema_len: int = 200
    ema_rising_lookback: int = 10
    stop_far_mult: float = 0.75
    trail_swing: int = 6
    trail_after_R: float = 1.0
    use_ema_gate: bool = True


NY = (Session.NY_AM, Session.NY_PM)


class LvlImbEngine:
    def __init__(self, cfg: LvlImbConfig = LvlImbConfig()):
        self.cfg = cfg
        self._atr = _Atr(cfg.atr_len)
        self._ema = _Ema(cfg.ema_len)
        self._ema_hist = deque(maxlen=cfg.ema_rising_lookback + 1)
        self._recent = deque(maxlen=cfg.swing_lookback + 6)   # prior bars (o,h,l,c)
        self._cur_ts: Optional[datetime] = None
        self.zones: list[dict] = []
        self.in_pos = False
        self.entry = self.stop = self.risk = 0.0
        self.trail_active = False
        self.trail = 0.0
        self._lows6 = deque(maxlen=cfg.trail_swing)
        # instrumentation
        self.skipped_inpos = 0
        self.gated_skips = 0

    def feed_ts(self, ts):
        self._cur_ts = ts
        return (0.0, False)

    def on_bar(self, o, h, l, c, daily_gap=0.0, daily_rising=False) -> Optional[dict]:
        ts = self._cur_ts
        sess = tag_session(ts)
        atr = self._atr.update(h, l, c)
        ema = self._ema.update(c)
        self._ema_hist.append(ema)
        decision = None

        # 1) manage open position
        if self.in_pos:
            if not self.trail_active and h >= self.entry + self.cfg.trail_after_R * self.risk:
                self.trail_active = True
            stop_level = self.stop
            if self.trail_active and self._lows6:
                self.trail = max(self.trail, min(self._lows6))
                stop_level = max(self.stop, self.trail)
            if l <= stop_level:
                self.in_pos = False
                decision = {"signal": Signal.EXIT_LONG, "price": stop_level, "qty": 1}
                self._finish(o, h, l, c)
                return decision
            self._lows6.append(l)
            self._finish(o, h, l, c)
            return decision

        # 2) zone invalidation: 5m close below far edge (zone low)
        if self.zones:
            self.zones = [z for z in self.zones if c >= z["low"]]

        # 3) entry on first NY tap of a valid zone (with EMA gate)
        if sess in NY:
            for z in self.zones:
                if z["tapped_ny"]:
                    continue
                if l <= z["mid"]:                      # price reached the midpoint
                    z["tapped_ny"] = True               # first NY tap consumed
                    rising = (ema is not None and len(self._ema_hist) > self.cfg.ema_rising_lookback
                              and self._ema_hist[0] is not None and ema > self._ema_hist[0])
                    gate = (not self.cfg.use_ema_gate) or (ema is not None and c > ema and rising)
                    if gate:
                        self.entry = z["mid"]
                        self.stop = z["low"] - self.cfg.stop_far_mult * (z["high"] - z["low"])
                        self.risk = self.entry - self.stop
                        self.in_pos = True
                        self.trail_active = False
                        self.trail = self.stop
                        self._lows6.clear()
                        decision = {"signal": Signal.ENTER_LONG, "price": self.entry, "qty": 1}
                        self._finish(o, h, l, c)
                        return decision
                    else:
                        self.gated_skips += 1
                        break

        # 4) detect a new zone in the formation session
        cfg = self.cfg
        if atr is not None and len(self._recent) >= cfg.swing_lookback + 3 and sess is cfg.formation_session:
            r = list(self._recent)
            b1, b2 = r[-1], r[-2]                        # bars i-1, i-2
            leg_low = min(l, b1["l"], b2["l"])
            leg_move = h - leg_low
            prior_swing_high = max(b["h"] for b in r[-(cfg.swing_lookback + 2):-2])
            bullish_fvg = l > b2["h"]                     # bar-i low above bar-(i-2) high
            if leg_move >= cfg.disp_mult * atr and h > prior_swing_high and bullish_fvg:
                ob = next((b for b in reversed(r[:-2]) if b["c"] < b["o"]), None)
                if ob is not None and ob["h"] > ob["l"]:
                    self.zones.append({"low": ob["l"], "high": ob["h"],
                                       "mid": (ob["l"] + ob["h"]) / 2.0, "tapped_ny": False})

        self._finish(o, h, l, c)
        return decision

    def _finish(self, o, h, l, c):
        self._recent.append({"o": o, "h": h, "l": l, "c": c})
