"""Event-driven backtest harness — shared engine code, backtest + live identical.

T01 deliverable. Streams bars to any engine with on_bar(); applies friction;
computes the standard stat block. ATR convention = simple rolling-mean (validated).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Optional
import math


class Engine(Protocol):
    def on_bar(self, o: float, h: float, l: float, c: float,
               daily_gap: float = 0.0, daily_rising: bool = False) -> Optional[dict]: ...


@dataclass
class Stats:
    n: int; win_pct: float; total_pts: float; pf: float; max_dd: float
    sharpe_daily: float; avg_win: float; avg_loss: float
    max_win: float; max_loss: float

    def __str__(self):
        return (f"n={self.n} win={self.win_pct:.0f}% total={self.total_pts:+.0f} "
                f"PF={self.pf:.2f} maxDD={self.max_dd:.0f} sharpe={self.sharpe_daily:.2f}")


def run_backtest(bars, engine: Engine, friction_pts: float = 1.0,
                 daily_gap_fn=None) -> tuple[list, Stats]:
    """bars: iterable of (ts, o, h, l, c). daily_gap_fn(ts)->(gap,rising) optional.
    Returns (trades, stats). trades carry pnl in points (net of friction) and exit ts."""
    trades = []
    entry_px = None
    entry_ts = None
    entry_qty = 1
    entry_side = 0          # +1 long, -1 short (0 = flat)

    for row in bars:
        ts, o, h, l, c = row[0], row[1], row[2], row[3], row[4]
        dg, dr = (daily_gap_fn(ts) if daily_gap_fn else (0.0, False))
        dec = engine.on_bar(o, h, l, c, dg, dr)
        if dec is None:
            continue
        sig = str(dec["signal"])
        if sig.endswith("ENTER_LONG"):
            entry_px = dec["price"]; entry_ts = ts; entry_qty = int(dec.get("qty", 1)); entry_side = 1
        elif sig.endswith("ENTER_SHORT"):
            entry_px = dec["price"]; entry_ts = ts; entry_qty = int(dec.get("qty", 1)); entry_side = -1
        elif sig.endswith("EXIT_LONG") and entry_side == 1:
            pnl_pts = dec["price"] - entry_px - friction_pts   # per-contract points
            trades.append({"pnl": pnl_pts * entry_qty, "pnl_pts": pnl_pts,
                           "qty": entry_qty, "exit_ts": ts, "entry_ts": entry_ts})
            entry_px = None; entry_ts = None; entry_qty = 1; entry_side = 0
        elif sig.endswith("EXIT_SHORT") and entry_side == -1:
            pnl_pts = entry_px - dec["price"] - friction_pts   # short: profit when price falls
            trades.append({"pnl": pnl_pts * entry_qty, "pnl_pts": pnl_pts,
                           "qty": entry_qty, "exit_ts": ts, "entry_ts": entry_ts})
            entry_px = None; entry_ts = None; entry_qty = 1; entry_side = 0

    return trades, _stats(trades)


def _stats(trades) -> Stats:
    if not trades:
        return Stats(0,0,0,0,0,0,0,0,0,0)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf")
    # max drawdown on cumulative
    cum = 0.0; peak = 0.0; mdd = 0.0
    for p in pnls:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    # daily Sharpe: group by exit date
    from collections import defaultdict
    import datetime as _dt
    daily = defaultdict(float)
    for t in trades:
        d = t["exit_ts"]
        key = d.date() if hasattr(d, "date") else d
        daily[key] += t["pnl"]
    vals = list(daily.values())
    if len(vals) > 1:
        mean = sum(vals)/len(vals)
        var = sum((v-mean)**2 for v in vals)/(len(vals)-1)
        sd = math.sqrt(var)
        sharpe = (mean/sd*math.sqrt(252)) if sd > 0 else 0.0
    else:
        sharpe = 0.0
    return Stats(
        n=len(trades), win_pct=len(wins)/len(trades)*100, total_pts=total,
        pf=pf, max_dd=mdd, sharpe_daily=sharpe,
        avg_win=sum(wins)/len(wins) if wins else 0,
        avg_loss=sum(losses)/len(losses) if losses else 0,
        max_win=max(pnls), max_loss=min(pnls),
    )
