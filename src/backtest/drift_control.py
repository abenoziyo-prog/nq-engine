"""T07 — drift control: the random same-session-entry benchmark.

Constitution rule 4 (CLAUDE.md): no strategy is judged on absolute P&L alone —
it must beat a drift control of random same-session entries. Buy-and-hold is
RETIRED (operator directive 2026-06-12) and deliberately NOT implemented here.

For a given session window (default NY_AM) and direction (default long), this
draws N seeded random entries, holds each a fixed horizon, and reports the
standard stat block (reused from the harness) plus the MFE/MAE excursion ratio.
Single-seed runs are deterministic; monte_carlo() pools many seeds.

Calibrated 2026-06-13 on data/MNQ_5m_aggregated_clean.csv: NY_AM long, the
floor-at-0 MFE/MAE over the full candidate population is ~0.929 at horizon_bars=6
(30 min), drifting to ~0.90 at longer horizons. This reproduces the recorded
"drift control 0.93" NY-morning-long number (strategy_vault.json: OB_STRICT_SINGLE_TOUCH).
The Mar-Jun up-tape does not push the ratio above 1.0 because excursion is a
volatility statistic — intrabar lows dip below the entry close about as much as
highs exceed it, even while closes trend up.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import csv
import random
import statistics

from src.backtest.harness import Stats, _stats
from src.data.model import Bar, Session

DEFAULT_DATA = "data/MNQ_5m_aggregated_clean.csv"
DRIFT_VOLUME = 0       # CSV carries no volume column; constant placeholder for Bar
EPS = 1e-9             # MAE floor to avoid div-by-zero on the aggregate ratio


@dataclass(frozen=True)
class DriftConfig:
    session: Session = Session.NY_AM
    direction: str = "long"        # "long" | "short"
    horizon_bars: int = 6          # LOCKED default (≈0.929 NY_AM long) — see module docstring
    n_entries: int = 200
    friction_pts: float = 1.0      # repo convention: 1.0 pt round-trip
    seed: int = 12345              # canonical deterministic seed
    replace: bool = False          # sample without replacement when the pool allows


@dataclass
class DriftResult:
    stats: Stats
    mfe_mae_ratio: float
    mean_mfe: float
    mean_mae: float
    n: int
    seed: int
    horizon_bars: int
    trades: list = field(default_factory=list)   # _stats-compatible trade dicts


@dataclass
class MonteCarloResult:
    pooled_ratio: float            # sum(all MFE) / sum(all MAE) across every seed
    mean_ratio: float              # mean of per-seed ratios
    std_ratio: float
    pct: dict                      # {5, 25, 50, 75, 95: ratio}
    per_seed: list                 # list[DriftResult]
    n_seeds: int
    n_entries_per_seed: int


def load_bars(path: str = DEFAULT_DATA) -> list[Bar]:
    """Parse the clean 5m CSV into session-tagged Bars, chronological order.

    Header: time,ts_utc,ts_et,open,high,low,close  (no volume column)."""
    bars: list[Bar] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["ts_utc"])   # "2026-03-08 22:55:00+00:00"
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bars.append(Bar(ts=ts, open=float(row["open"]), high=float(row["high"]),
                            low=float(row["low"]), close=float(row["close"]),
                            volume=DRIFT_VOLUME))
    bars.sort(key=lambda b: b.ts)   # defensive; CSV is already sorted
    return bars


def candidate_indices(bars: list[Bar], cfg: DriftConfig) -> list[int]:
    """Bars in the target session that have >= horizon_bars of forward data, so the
    excursion window and exit are always well-defined."""
    last = len(bars) - 1
    return [i for i, b in enumerate(bars)
            if b.session is cfg.session and i + cfg.horizon_bars <= last]


def _excursion(bars: list[Bar], i: int, cfg: DriftConfig) -> tuple[float, float, float]:
    """(mfe, mae, exit_close) for an entry at bar i's close over the next horizon_bars.

    Long:  MFE = max(0, max_high - entry_close), MAE = max(0, entry_close - min_low)
    Short: symmetric (favorable on the downside, adverse on the upside).
    Excursion is measured over bars AFTER entry (exclusive of the entry bar)."""
    entry_close = bars[i].close
    window = bars[i + 1 : i + 1 + cfg.horizon_bars]
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    if cfg.direction == "long":
        mfe = max(hi - entry_close, 0.0)
        mae = max(entry_close - lo, 0.0)
    else:
        mfe = max(entry_close - lo, 0.0)
        mae = max(hi - entry_close, 0.0)
    return mfe, mae, bars[i + cfg.horizon_bars].close


def run_drift(bars: list[Bar], cfg: DriftConfig) -> DriftResult:
    """One deterministic drift sample: N random same-session entries, fixed horizon."""
    pool = candidate_indices(bars, cfg)
    if not pool:
        raise ValueError(f"no candidate entries for {cfg.session} horizon={cfg.horizon_bars}")

    rng = random.Random(cfg.seed)   # LOCAL instance — never touch the global RNG
    if cfg.replace or cfg.n_entries > len(pool):
        chosen = [rng.choice(pool) for _ in range(cfg.n_entries)]
    else:
        chosen = rng.sample(pool, cfg.n_entries)
    chosen.sort()   # chronological -> deterministic, meaningful DD/Sharpe (ratio is order-free)

    trades, mfes, maes = [], [], []
    for i in chosen:
        mfe, mae, exit_close = _excursion(bars, i, cfg)
        mfes.append(mfe)
        maes.append(mae)
        entry_close = bars[i].close
        pnl_pts = ((exit_close - entry_close) if cfg.direction == "long"
                   else (entry_close - exit_close)) - cfg.friction_pts
        trades.append({"pnl": pnl_pts, "pnl_pts": pnl_pts, "qty": 1,
                       "entry_ts": bars[i].ts, "exit_ts": bars[i + cfg.horizon_bars].ts})

    sum_mae = sum(maes)
    ratio = sum(mfes) / sum_mae if sum_mae > EPS else float("inf")
    return DriftResult(
        stats=_stats(trades), mfe_mae_ratio=ratio,
        mean_mfe=statistics.fmean(mfes), mean_mae=statistics.fmean(maes),
        n=len(trades), seed=cfg.seed, horizon_bars=cfg.horizon_bars, trades=trades)


def monte_carlo(bars: list[Bar], cfg: DriftConfig,
                seeds: Optional[list[int]] = None, n_seeds: int = 200) -> MonteCarloResult:
    """Run many seeds and report pooled + per-seed ratio distribution. When seeds is
    None they are derived deterministically from cfg.seed, so the whole MC is reproducible."""
    if seeds is None:
        master = random.Random(cfg.seed)
        seeds = [master.randint(0, 2**31 - 1) for _ in range(n_seeds)]

    per_seed, ratios, pooled_mfe, pooled_mae = [], [], 0.0, 0.0
    for s in seeds:
        r = run_drift(bars, DriftConfig(**{**cfg.__dict__, "seed": s}))
        per_seed.append(r)
        ratios.append(r.mfe_mae_ratio)
        pooled_mfe += r.mean_mfe * r.n
        pooled_mae += r.mean_mae * r.n

    ratios_sorted = sorted(ratios)
    if len(ratios_sorted) >= 2:
        q = statistics.quantiles(ratios_sorted, n=100, method="inclusive")
        pct = {5: q[4], 25: q[24], 50: q[49], 75: q[74], 95: q[94]}
    else:
        pct = {k: ratios_sorted[0] for k in (5, 25, 50, 75, 95)}

    return MonteCarloResult(
        pooled_ratio=pooled_mfe / pooled_mae if pooled_mae > EPS else float("inf"),
        mean_ratio=statistics.fmean(ratios),
        std_ratio=statistics.pstdev(ratios) if len(ratios) > 1 else 0.0,
        pct=pct, per_seed=per_seed, n_seeds=len(seeds), n_entries_per_seed=cfg.n_entries)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Drift control — random same-session entries benchmark")
    p.add_argument("--session", default="NY_AM")
    p.add_argument("--direction", default="long", choices=["long", "short"])
    p.add_argument("--horizon", type=int, default=6)
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--mc", type=int, default=0, help="run N seeds in Monte-Carlo mode")
    p.add_argument("--data", default=DEFAULT_DATA)
    a = p.parse_args()

    bars = load_bars(a.data)
    cfg = DriftConfig(session=Session[a.session], direction=a.direction,
                      horizon_bars=a.horizon, n_entries=a.n, seed=a.seed)
    if a.mc:
        mc = monte_carlo(bars, cfg, n_seeds=a.mc)
        print(f"DRIFT MC {a.session} {a.direction} H={a.horizon} seeds={a.mc}  "
              f"pooled={mc.pooled_ratio:.3f} mean={mc.mean_ratio:.3f}±{mc.std_ratio:.3f} "
              f"p5/50/95={mc.pct[5]:.3f}/{mc.pct[50]:.3f}/{mc.pct[95]:.3f}")
    else:
        r = run_drift(bars, cfg)
        print(f"DRIFT {a.session} {a.direction} H={a.horizon} seed={a.seed}  "
              f"MFE/MAE={r.mfe_mae_ratio:.3f}  meanMFE={r.mean_mfe:.1f} meanMAE={r.mean_mae:.1f}")
        print(r.stats)
