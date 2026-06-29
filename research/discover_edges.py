"""discover_edges — systematic EDGE DISCOVERY (framework Stage 0).

The framework's job is to *find* edges, not just test ideas you already have. This
scans a library of LOCATION / TIMING / REGIME conditions and measures the forward
return after each (long and short, multiple horizons). It surfaces the conditions
whose forward edge is statistically reliable and beats the unconditional baseline —
each surfaced row is a candidate hypothesis to turn into an engine and run through
validate_strategy.py.

This is the "edge lives in location + timing, not indicators" principle made
mechanical: test many (where, when, regime) conditions, keep the ones with signal.

Usage:  .venv/bin/python research/discover_edges.py --tf 5 --min-n 80 --min-t 3.0
"""
import argparse
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.drift_control import load_bars
from src.engine.v4 import _Ema, _Atr
from src.data.model import tag_session

FRICTION = 1.0
HORIZONS = (6, 12, 24)        # bars forward (5m -> 30/60/120 min)
ROLL = 60                     # lookback window for location features


def features(bars):
    """Per-bar feature dict arrays (causal — uses only past/current)."""
    n = len(bars)
    e9, e50, atr = _Ema(9), _Ema(50), _Atr(14)
    c = [b.close for b in bars]
    f = {k: [None] * n for k in
         ("sess", "dist_ema9", "gap_atr", "dist_hi", "dist_lo", "mom3", "hivol")}
    atr_hist = []
    for i, b in enumerate(bars):
        f9, f50, a = e9.update(b.close), e50.update(b.close), atr.update(b.high, b.low, b.close)
        f["sess"][i] = tag_session(b.ts).value
        if a and a > 0 and i >= ROLL:
            f["dist_ema9"][i] = (b.close - f9) / a
            f["gap_atr"][i] = (f9 - f50) / a
            hi = max(x.high for x in bars[i - ROLL:i]); lo = min(x.low for x in bars[i - ROLL:i])
            f["dist_hi"][i] = (b.close - hi) / a       # <= 0 (0 = at the high)
            f["dist_lo"][i] = (b.close - lo) / a       # >= 0 (0 = at the low)
            f["mom3"][i] = (b.close - c[i - 3]) / a
            atr_hist.append(a)
            med = statistics.median(atr_hist[-ROLL:])
            f["hivol"][i] = a > med
    return f, c


# (name, predicate over the per-bar feature dict at index i). Single, interpretable conditions.
def conditions(f):
    g = lambda k, i: f[k][i]
    def ok(i): return f["dist_ema9"][i] is not None
    return {
        "session=ASIA":        lambda i: ok(i) and g("sess", i) == "ASIA",
        "session=LONDON":      lambda i: ok(i) and g("sess", i) == "LONDON",
        "session=NY_AM":       lambda i: ok(i) and g("sess", i) == "NY_AM",
        "session=NY_PM":       lambda i: ok(i) and g("sess", i) == "NY_PM",
        "stretched_>=3ATR_below_ema9": lambda i: ok(i) and g("dist_ema9", i) <= -3,
        "stretched_>=3ATR_above_ema9": lambda i: ok(i) and g("dist_ema9", i) >= 3,
        "near_60bar_high(<=0.3ATR)":   lambda i: ok(i) and g("dist_hi", i) >= -0.3,
        "near_60bar_low(<=0.3ATR)":    lambda i: ok(i) and g("dist_lo", i) <= 0.3,
        "ema9>>ema50 (gap>2ATR)":      lambda i: ok(i) and g("gap_atr", i) > 2,
        "ema9<<ema50 (gap<-2ATR)":     lambda i: ok(i) and g("gap_atr", i) < -2,
        "3-bar momentum up (>1ATR)":   lambda i: ok(i) and g("mom3", i) > 1,
        "3-bar momentum down (<-1ATR)":lambda i: ok(i) and g("mom3", i) < -1,
        "high-vol regime":             lambda i: ok(i) and g("hivol", i) is True,
        "low-vol regime":              lambda i: ok(i) and g("hivol", i) is False,
        "NY_AM + near 60bar low":      lambda i: ok(i) and g("sess", i) == "NY_AM" and g("dist_lo", i) <= 0.3,
        "LONDON + stretched below":    lambda i: ok(i) and g("sess", i) == "LONDON" and g("dist_ema9", i) <= -2,
    }


def scan(bars):
    f, c = features(bars)
    n = len(bars)
    conds = conditions(f)
    # unconditional baselines per (direction, horizon)
    base = {}
    for H in HORIZONS:
        for d in (1, -1):
            vals = [d * (c[i + H] - c[i]) - FRICTION for i in range(n - H) if f["dist_ema9"][i] is not None]
            base[(d, H)] = statistics.fmean(vals) if vals else 0.0
    rows = []
    for name, pred in conds.items():
        idx = [i for i in range(n) if pred(i)]
        for H in HORIZONS:
            ii = [i for i in idx if i + H < n]
            if len(ii) < 30:
                continue
            for d, dname in ((1, "LONG"), (-1, "SHORT")):
                v = [d * (c[i + H] - c[i]) - FRICTION for i in ii]
                m = statistics.fmean(v)
                sd = statistics.pstdev(v) or 1e-9
                t = m / sd * (len(v) ** 0.5)
                win = sum(1 for x in v if x > 0) / len(v) * 100
                rows.append(dict(cond=name, dir=dname, H=H, n=len(v), mean=m,
                                 t=t, win=win, edge=m - base[(d, H)]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", type=int, default=5)
    ap.add_argument("--min-n", type=int, default=80)
    ap.add_argument("--min-t", type=float, default=3.0)
    args = ap.parse_args()
    bars = load_bars(f"src/data/MNQ_{args.tf}m_12mo_databento.csv")
    rows = scan(bars)
    # keep: reliably positive forward return (after friction) that beats baseline
    cand = [r for r in rows if r["n"] >= args.min_n and r["t"] >= args.min_t
            and r["mean"] > 0 and r["edge"] > 0]
    cand.sort(key=lambda r: -r["t"])
    print(f"\n=== EDGE DISCOVERY — {args.tf}m, {len(bars):,} bars "
          f"({bars[0].ts.date()}..{bars[-1].ts.date()}) ===")
    print(f"scanned {len(rows)} (condition x direction x horizon) cells; "
          f"candidates: n>={args.min_n}, t>={args.min_t}, mean>0, beats baseline\n")
    print(f"{'condition':32} {'dir':5} {'H':>3} {'n':>5} {'mean_pt':>8} {'t':>6} {'win%':>5} {'edge_vs_base':>12}")
    print("-" * 92)
    for r in cand[:20]:
        print(f"{r['cond']:32} {r['dir']:5} {r['H']:>3} {r['n']:>5} {r['mean']:>+8.2f} "
              f"{r['t']:>6.1f} {r['win']:>4.0f}% {r['edge']:>+12.2f}")
    if not cand:
        print("(no conditions cleared the gates — tighten/loosen --min-t / --min-n)")
    print("\nEach row = a candidate hypothesis. Build it as an engine "
          "(src/engine/_template_engine.py), then validate_strategy.py. "
          "Beware multiple testing: confirm on a holdout / drift control before trusting.\n")


if __name__ == "__main__":
    main()
