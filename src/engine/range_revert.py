"""RANGE_REVERT — location mean-reversion: buy near the N-bar range low (or, mirror,
sell near the range high), exit on reversion to EMA9.

DISCOVERED by research/discover_edges.py (framework Stage 0): "near_60bar_low LONG"
showed +5.25 pt @ H6 (t=4.2) / +6.53 @ H24, and "near_60bar_high SHORT" +4.40 @ H6.
This engine turns that surfaced edge into a tradeable rule (Stage 1-2). Pre-registered
hypothesis: price tagging the recent range extreme mean-reverts back toward EMA9.

  entry LONG  : (close - min(prior N lows)) / ATR <= near_atr   (at/near the range low)
  exit  LONG  : close >= EMA9 (reverted to mean)  OR  held >= max_hold bars
  (short = mirror at the range high)
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Optional

from src.engine.v4 import _Ema, _Atr, Signal


@dataclass
class RangeRevertConfig:
    lookback: int = 60          # bars defining the range extreme
    atr_len: int = 14
    ema_len: int = 9
    near_atr: float = 0.3       # within this many ATR of the extreme to trigger
    max_hold: int = 24          # time cap (bars) if reversion never comes
    direction: str = "long"     # "long" (buy lows) | "short" (sell highs)


class RangeRevertEngine:
    def __init__(self, cfg: RangeRevertConfig = RangeRevertConfig()):
        self.cfg = cfg
        self._ema = _Ema(cfg.ema_len)
        self._atr = _Atr(cfg.atr_len)
        self._highs = deque(maxlen=cfg.lookback)
        self._lows = deque(maxlen=cfg.lookback)
        self._bars = 0
        self.pos = 0
        self._held = 0

    def on_bar(self, o: float, h: float, l: float, c: float,
               daily_gap: float = 0.0, daily_rising: bool = False) -> Optional[dict]:
        ema = self._ema.update(c)
        atr = self._atr.update(h, l, c)
        self._bars += 1
        rng_lo = min(self._lows) if self._lows else l      # PRIOR-window extremes (causal)
        rng_hi = max(self._highs) if self._highs else h
        self._highs.append(h); self._lows.append(l)
        if atr is None or ema is None or atr <= 0 or self._bars <= self.cfg.lookback:
            return None
        short = self.cfg.direction == "short"
        if self.pos != 0:
            self._held += 1

        if self.pos == 0:
            if not short and (c - rng_lo) / atr <= self.cfg.near_atr:
                self.pos = 1; self._held = 0
                return {"signal": Signal.ENTER_LONG, "price": c, "qty": 1}
            if short and (c - rng_hi) / atr >= -self.cfg.near_atr:
                self.pos = -1; self._held = 0
                return {"signal": Signal.ENTER_SHORT, "price": c, "qty": 1}
        elif self.pos == 1 and (c >= ema or self._held >= self.cfg.max_hold):
            self.pos = 0
            return {"signal": Signal.EXIT_LONG, "price": c, "qty": 1}
        elif self.pos == -1 and (c <= ema or self._held >= self.cfg.max_hold):
            self.pos = 0
            return {"signal": Signal.EXIT_SHORT, "price": c, "qty": 1}
        return None
