"""TEMPLATE engine — copy this to src/engine/<your_strategy>.py to start.

Implements the standard engine contract (see docs/STRATEGY_FRAMEWORK.md §2):
  - one position per engine, one decision per bar
  - on_bar(o,h,l,c,daily_gap,daily_rising) -> decision dict | None
  - reuse the validated _Ema / _Atr conventions from v4
  - support direction='long'|'short' so the mirror comes for free

State the hypothesis in this docstring BEFORE coding (pre-registration). Then:
  python research/validate_strategy.py src.engine.<your_strategy>:TemplateEngine
and record the result in the vault — win or lose.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from src.engine.v4 import _Ema, _Atr, Signal   # Signal has ENTER/EXIT _LONG/_SHORT


@dataclass
class TemplateConfig:
    ema_len: int = 9
    atr_len: int = 14
    # ... your parameters here ...
    direction: str = "long"            # "long" | "short" (mirror)


class TemplateEngine:
    def __init__(self, cfg: TemplateConfig = TemplateConfig()):
        self.cfg = cfg
        self._ema = _Ema(cfg.ema_len)
        self._atr = _Atr(cfg.atr_len)
        self._bars = 0
        self.pos = 0                   # +1 long, -1 short, 0 flat

    def on_bar(self, o: float, h: float, l: float, c: float,
               daily_gap: float = 0.0, daily_rising: bool = False) -> Optional[dict]:
        ema = self._ema.update(c)
        atr = self._atr.update(h, l, c)
        self._bars += 1
        if atr is None or ema is None or atr <= 0:      # warmup
            return None
        short = self.cfg.direction == "short"

        # ---- DEFINE YOUR SIGNAL HERE ----
        # long_entry  = <condition on o,h,l,c,ema,atr>
        # long_exit   = <condition>
        long_entry = long_exit = False                  # replace

        if self.pos == 0:
            if not short and long_entry:
                self.pos = 1
                return {"signal": Signal.ENTER_LONG, "price": c, "qty": 1}
            if short and long_exit:                     # mirror: short on the long-exit setup
                self.pos = -1
                return {"signal": Signal.ENTER_SHORT, "price": c, "qty": 1}
        elif self.pos == 1 and long_exit:
            self.pos = 0
            return {"signal": Signal.EXIT_LONG, "price": c, "qty": 1}
        elif self.pos == -1 and long_entry:
            self.pos = 0
            return {"signal": Signal.EXIT_SHORT, "price": c, "qty": 1}
        return None
