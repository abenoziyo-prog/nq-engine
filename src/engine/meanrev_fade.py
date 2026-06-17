"""MEANREV_FADE_2M — mean-reversion fade engine (2-min, long-only).

Per the operator-external spec (UNVERIFIED until this engine confirms it):
  - 2-min bars. EMA9 (ewm) and ATR14 (simple rolling-mean, repo convention).
  - distance = (close - EMA9) / ATR.
  - ENTER LONG at bar close when distance <= -3.0 (price stretched >= 3 ATR below EMA9).
  - EXIT at bar close when close >= EMA9 - 0.5*ATR (reverted near the mean).
  - Long-only, single position, no stop (exit is reversion-only, as specified).
  - Friction 1pt applied by the harness.

Runs through the unmodified harness directly (entry/exit depend only on OHLC, not
timestamp). Distinct family from everything else in the vault (a fade, not a
trend/zone signal). Do NOT tune.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.engine.v4 import _Ema, _Atr


class Signal(str, Enum):
    NONE = "NONE"
    ENTER_LONG = "ENTER_LONG"
    EXIT_LONG = "EXIT_LONG"


@dataclass
class MeanRevConfig:
    ema_len: int = 9
    atr_len: int = 14
    entry_dist: float = -3.0       # enter when (close-EMA9)/ATR <= -3.0
    exit_dist: float = -0.5        # exit when close >= EMA9 - 0.5*ATR


class MeanRevFadeEngine:
    def __init__(self, cfg: MeanRevConfig = MeanRevConfig()):
        self.cfg = cfg
        self._ema = _Ema(cfg.ema_len)
        self._atr = _Atr(cfg.atr_len)
        self.in_pos = False

    def on_bar(self, o: float, h: float, l: float, c: float,
               daily_gap: float = 0.0, daily_rising: bool = False) -> Optional[dict]:
        ema = self._ema.update(c)
        atr = self._atr.update(h, l, c)
        if atr is None or ema is None or atr <= 0:
            return None

        if self.in_pos:
            # exit on reversion back near the mean
            if c >= ema + self.cfg.exit_dist * atr:
                self.in_pos = False
                return {"signal": Signal.EXIT_LONG, "price": c, "qty": 1}
            return None

        # entry: stretched >= 3 ATR below EMA9
        distance = (c - ema) / atr
        if distance <= self.cfg.entry_dist:
            self.in_pos = True
            return {"signal": Signal.ENTER_LONG, "price": c, "qty": 1}
        return None
