"""EMA_CROSS_9_50 — EMA9/EMA50 cross engine, long + short, momentum-filtered.

Operator-requested (2026-06-24): buy/sell as EMA9 & EMA50 are about to cross, with a
momentum filter; exit on the reverse signal; both directions (a flip system).

  gap   = EMA9 - EMA50
  dGap  = gap - prev_gap        (the spread's slope = the momentum filter)
  bullish = gap > -band  AND  dGap >  momentum_min   (EMA9 rising up through EMA50)
  bearish = gap <  band  AND  dGap < -momentum_min   (EMA9 falling down through EMA50)

  flat  + bullish -> ENTER_LONG ;  flat + bearish -> ENTER_SHORT
  long  + bearish -> EXIT_LONG  ;  short + bullish -> EXIT_SHORT   (exit = reverse signal)

`band` = how early to act ("about to cross"): 0 = on the actual cross, >0 anticipates.
`momentum_min` = min |spread slope| to confirm — filters stalling/choppy crosses.

⚠ The vault FALSIFIED naive EMA-cross triggers (EMA_CROSS_CONFIRMED, -2307 pt). This is
built to spec and must earn deployment via backtest — do not assume it has edge.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from src.engine.v4 import _Ema, Signal


@dataclass
class EmaCrossConfig:
    fast: int = 9
    slow: int = 50
    band: float = 0.0           # points around the cross to act within (0 = on cross)
    momentum_min: float = 0.0   # min |gap slope| to confirm momentum


class EmaCrossEngine:
    def __init__(self, cfg: EmaCrossConfig = EmaCrossConfig()):
        self.cfg = cfg
        self._ef = _Ema(cfg.fast)
        self._es = _Ema(cfg.slow)
        self._gprev: Optional[float] = None
        self._bars = 0
        self.pos = 0            # +1 long, -1 short, 0 flat

    def on_bar(self, o: float, h: float, l: float, c: float,
               daily_gap: float = 0.0, daily_rising: bool = False) -> Optional[dict]:
        ef, es = self._ef.update(c), self._es.update(c)
        self._bars += 1
        gap = ef - es
        dg = None if self._gprev is None else gap - self._gprev
        self._gprev = gap
        if dg is None or self._bars < self.cfg.slow:
            return None

        b, m = self.cfg.band, self.cfg.momentum_min
        bullish = gap > -b and dg > m
        bearish = gap < b and dg < -m

        if self.pos == 0:
            if bullish:
                self.pos = 1
                return {"signal": Signal.ENTER_LONG, "price": c, "qty": 1}
            if bearish:
                self.pos = -1
                return {"signal": Signal.ENTER_SHORT, "price": c, "qty": 1}
        elif self.pos == 1 and bearish:
            self.pos = 0
            return {"signal": Signal.EXIT_LONG, "price": c, "qty": 1}
        elif self.pos == -1 and bullish:
            self.pos = 0
            return {"signal": Signal.EXIT_SHORT, "price": c, "qty": 1}
        return None
