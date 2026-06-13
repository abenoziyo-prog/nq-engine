"""V4 engine — single source of signal truth for backtest AND live bridge.

Identical logic must drive both. The bridge feeds live bars in; the backtest
harness feeds historical bars in. If this module reproduces the vault numbers
on historical data, we know the live path is faithful.

Frozen config (strategy_vault.json :: EMA_PROX_V4_5M):
  fast=9 slow=50 atr=14, k=0.02*ATR, accel(ddG>0), long-only,
  exit on anticipated downcross, catastrophe stop 4*ATR, daily-align +1 unit.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Signal(str, Enum):
    NONE = "NONE"
    ENTER_LONG = "ENTER_LONG"
    EXIT_LONG = "EXIT_LONG"


@dataclass
class V4Config:
    fast: int = 9
    slow: int = 50
    atr_len: int = 14
    k_atr: float = 0.02
    stop_atr: float = 4.0
    accel: bool = True
    daily_align_size: bool = True


class _Ema:
    def __init__(self, span: int):
        self.a = 2.0 / (span + 1.0)
        self.v: Optional[float] = None
    def update(self, x: float) -> float:
        self.v = x if self.v is None else self.v + self.a * (x - self.v)
        return self.v


class _Atr:
    """Simple rolling-mean ATR(n) on closed bars — matches the validated backtest.
    (Wilder smoothing changes the k threshold and shifts trades; do not substitute.)
    """
    def __init__(self, n: int):
        from collections import deque
        self.n = n; self.trs = deque(maxlen=n); self.prev_close: Optional[float] = None
    def update(self, h: float, l: float, c: float) -> Optional[float]:
        tr = h - l if self.prev_close is None else max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        self.trs.append(tr); self.prev_close = c
        return sum(self.trs) / len(self.trs) if len(self.trs) == self.n else None


@dataclass
class V4State:
    in_position: bool = False
    entry_price: float = 0.0
    qty: int = 0
    stop_price: float = 0.0


class V4Engine:
    """Feed closed bars via on_bar(); returns a decision dict or None.

    daily_gap / daily_rising are supplied externally (the live bridge computes
    them from the daily timeframe; the backtest passes a precomputed series).
    """
    def __init__(self, cfg: V4Config = V4Config()):
        self.cfg = cfg
        self._ef = _Ema(cfg.fast)
        self._es = _Ema(cfg.slow)
        self._atr = _Atr(cfg.atr_len)
        self._g_prev: Optional[float] = None
        self._dg_prev: Optional[float] = None
        self.state = V4State()
        self._bars = 0

    def on_bar(self, o: float, h: float, l: float, c: float,
               daily_gap: float = 0.0, daily_rising: bool = False) -> Optional[dict]:
        ef = self._ef.update(c)
        es = self._es.update(c)
        atr = self._atr.update(h, l, c)
        self._bars += 1
        g = ef - es
        dg = None if self._g_prev is None else g - self._g_prev
        ddg = None if (dg is None or self._dg_prev is None) else dg - self._dg_prev
        self._g_prev = g
        if dg is not None:
            self._dg_prev = dg

        if atr is None or dg is None or ddg is None or self._bars < self.cfg.slow:
            return None

        k = self.cfg.k_atr * atr
        decision = None

        if not self.state.in_position:
            enter = abs(g) <= k and g < 0 and dg > 0 and (ddg > 0 if self.cfg.accel else True)
            if enter:
                aligned = self.cfg.daily_align_size and daily_gap > 0 and daily_rising
                qty = 2 if aligned else 1
                stop = c - self.cfg.stop_atr * atr
                self.state = V4State(in_position=True, entry_price=c, qty=qty, stop_price=stop)
                decision = {"signal": Signal.ENTER_LONG, "price": c, "qty": qty,
                            "stop": stop, "atr": atr, "daily_aligned": aligned}
        else:
            # catastrophe stop check (intrabar low would trigger live; on closed bars use low)
            if l <= self.state.stop_price:
                px = self.state.stop_price
                decision = {"signal": Signal.EXIT_LONG, "price": px, "reason": "catastrophe_stop",
                            "qty": self.state.qty}
                self.state = V4State()
            else:
                exit_ = abs(g) <= k and g > 0 and dg < 0
                if exit_:
                    decision = {"signal": Signal.EXIT_LONG, "price": c, "reason": "signal_exit",
                                "qty": self.state.qty}
                    self.state = V4State()
        return decision
