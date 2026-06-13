"""SHOCK_v1 detector — implements docs/SHOCK_ENGINE_SPEC.md section 1.

Parameters are loaded from config and are a-priori fixed. Do not tune
against outcomes; changes go through the research loop.

Works identically on historical bar streams (backtest) and live feed.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

from src.data.model import Bar, ContextSnapshot


@dataclass(frozen=True)
class ShockParams:
    window_s: int = 180
    k_sigma: float = 4.0
    sigma_halflife_min: float = 30.0
    sigma_floor_frac: float = 0.25      # × 20d median sigma
    vol_multiple: float = 3.0
    cooldown_min: int = 30
    min_abs_move_pct: float = 0.35


@dataclass(slots=True)
class ShockEvent:
    shock_id: str
    ts_trigger: datetime
    direction: int                       # +1 up, -1 down
    shock_sigma: float
    impulse_range_pts: float
    impulse_open: float
    impulse_extreme: float
    impulse_duration_s: int
    # context features (filled from ContextSnapshot at trigger)
    session: str = ""
    mins_to_session_boundary: float = 0.0
    dist_to_pdh: Optional[float] = None
    dist_to_pdl: Optional[float] = None
    dist_to_asia_high: Optional[float] = None
    dist_to_asia_low: Optional[float] = None
    dist_to_london_high: Optional[float] = None
    dist_to_london_low: Optional[float] = None
    dist_to_session_vwap: Optional[float] = None
    vix_level: Optional[float] = None
    gamma_regime: str = "UNKNOWN"
    econ_flag: Optional[str] = None

    def to_record(self) -> dict:
        return asdict(self)


class EwmaSigma:
    """EWMA of 1-min log returns, half-life in minutes."""

    def __init__(self, halflife_min: float):
        self.alpha = 1 - math.exp(math.log(0.5) / halflife_min)
        self.var: Optional[float] = None
        self._last_close: Optional[float] = None

    def update(self, close: float) -> None:
        if self._last_close is not None and self._last_close > 0:
            r = math.log(close / self._last_close)
            self.var = r * r if self.var is None else (
                (1 - self.alpha) * self.var + self.alpha * r * r
            )
        self._last_close = close

    @property
    def sigma(self) -> Optional[float]:
        return None if self.var is None else math.sqrt(self.var)


class ShockDetector:
    """Feed 1-min bars via on_bar(); returns ShockEvent on trigger.

    Volume baseline: caller supplies a time-of-day baseline function
    (20-day median per minute-of-day) — kept external so backtest and
    live share one precomputed table.
    """

    def __init__(self, params: ShockParams, vol_baseline_fn, sigma_floor: float):
        self.p = params
        self.vol_baseline_fn = vol_baseline_fn      # (ts) -> median window volume
        self.sigma_floor = sigma_floor              # 0.25 × 20d median sigma, precomputed
        self._ewma = EwmaSigma(params.sigma_halflife_min)
        self._bars: deque[Bar] = deque()            # last `window_s` of bars
        self._cooldown_until: dict[int, datetime] = {}  # direction -> ts
        self._counter = 0

    def on_bar(self, bar: Bar, ctx: ContextSnapshot) -> Optional[ShockEvent]:
        self._ewma.update(bar.close)
        self._bars.append(bar)
        cutoff = bar.ts - timedelta(seconds=self.p.window_s)
        while self._bars and self._bars[0].ts < cutoff:
            self._bars.popleft()

        if len(self._bars) < 2 or self._ewma.sigma is None:
            return None

        ref = self._bars[0]
        move = bar.close - ref.open
        sigma = max(self._ewma.sigma, self.sigma_floor)
        scaled_sigma_pts = sigma * math.sqrt(self.p.window_s / 60.0) * bar.close
        threshold_pts = max(
            self.p.k_sigma * scaled_sigma_pts,
            self.p.min_abs_move_pct / 100.0 * bar.close,
        )
        if abs(move) < threshold_pts:
            return None

        direction = 1 if move > 0 else -1
        cd = self._cooldown_until.get(direction)
        if cd is not None and bar.ts < cd:
            return None

        window_vol = sum(b.volume for b in self._bars)
        baseline = self.vol_baseline_fn(bar.ts)
        if baseline <= 0 or window_vol < self.p.vol_multiple * baseline:
            return None

        # trigger
        self._cooldown_until[direction] = bar.ts + timedelta(minutes=self.p.cooldown_min)
        self._counter += 1
        extreme = max(b.high for b in self._bars) if direction == 1 else min(b.low for b in self._bars)
        ev = ShockEvent(
            shock_id=f"SHK-{bar.ts:%Y%m%d}-{self._counter:03d}",
            ts_trigger=bar.ts,
            direction=direction,
            shock_sigma=abs(move) / scaled_sigma_pts if scaled_sigma_pts > 0 else float("inf"),
            impulse_range_pts=abs(move),
            impulse_open=ref.open,
            impulse_extreme=extreme,
            impulse_duration_s=int((bar.ts - ref.ts).total_seconds()) + 60,
            session=ctx.session.value,
            mins_to_session_boundary=ctx.mins_to_session_boundary,
            dist_to_pdh=ctx.dist_to(ctx.levels.pdh, bar.close),
            dist_to_pdl=ctx.dist_to(ctx.levels.pdl, bar.close),
            dist_to_asia_high=ctx.dist_to(ctx.levels.asia_high, bar.close),
            dist_to_asia_low=ctx.dist_to(ctx.levels.asia_low, bar.close),
            dist_to_london_high=ctx.dist_to(ctx.levels.london_high, bar.close),
            dist_to_london_low=ctx.dist_to(ctx.levels.london_low, bar.close),
            dist_to_session_vwap=ctx.dist_to(ctx.levels.session_vwap, bar.close),
            vix_level=ctx.vix_level,
            gamma_regime=ctx.gamma_regime.value,
            econ_flag=ctx.econ_flag,
        )
        return ev
