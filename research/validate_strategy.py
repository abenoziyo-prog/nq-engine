"""validate_strategy — the framework's one-command gate battery (docs/STRATEGY_FRAMEWORK.md §3).

Backtests any engine on the databento data and prints the gates: PF, effective
(day-level) sample, top-3 concentration, blind-OOS compression, and the $2K prop-fit
screen. Records nothing — you read the gates and decide / log to the vault.

Usage:
  .venv/bin/python research/validate_strategy.py src.engine.meanrev_fade:MeanRevFadeEngine --tf 2
  .venv/bin/python research/validate_strategy.py src.engine.ema_cross:EmaCrossEngine --tf 5
"""
import argparse
import importlib
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest, _stats

PV = 2.0           # MNQ $/pt
DD_LIMIT = 2000.0  # $2K trailing prop limit


def block(trades):
    st = _stats(trades)
    if st.n == 0:
        return None
    days = len({t["entry_ts"].date() for t in trades})
    p = sorted((t["pnl"] for t in trades), reverse=True)
    conc = (sum(p[:3]) / st.total_pts * 100) if st.total_pts > 0 else float("nan")
    return dict(n=st.n, eff_days=days, win=st.win_pct, total=st.total_pts, pf=st.pf,
                dd=st.max_dd, dd_usd=st.max_dd * PV, conc=conc, sharpe=st.sharpe_daily)


def gate(ok):
    return "PASS ✅" if ok else "FAIL ❌"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("engine", help="module:Class, e.g. src.engine.ema_cross:EmaCrossEngine")
    ap.add_argument("--tf", type=int, default=5, help="bar timeframe minutes (data file)")
    args = ap.parse_args()

    modname, clsname = args.engine.split(":")
    Engine = getattr(importlib.import_module(modname), clsname)
    data = f"src/data/MNQ_{args.tf}m_12mo_databento.csv"
    bars = load_bars(data)
    tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]

    eng = Engine()
    dg = eng.feed_ts if hasattr(eng, "feed_ts") else None
    trades, _ = run_backtest(tup, eng, friction_pts=1.0, daily_gap_fn=dg)

    mid = bars[len(bars) // 2].ts.date()
    full = block(trades)
    blind = block([t for t in trades if t["entry_ts"].date() < mid])    # earliest half = blind
    recent = block([t for t in trades if t["entry_ts"].date() >= mid])

    print(f"\n=== validate {args.engine}  ({args.tf}m, {len(bars):,} bars, "
          f"{bars[0].ts.date()}..{bars[-1].ts.date()}) ===")
    if not full:
        print("no trades — engine never fired. Check warmup / signal."); return
    print(f"  n={full['n']}  eff_days={full['eff_days']}  trades/day={full['n']/((bars[-1].ts.date()-bars[0].ts.date()).days or 1):.2f}")
    print(f"  win%={full['win']:.0f}  total={full['total']:+.0f}pt  PF={full['pf']:.2f}  "
          f"sharpe={full['sharpe']:.2f}")
    print(f"  maxDD={full['dd']:.0f}pt = ${full['dd_usd']:+,.0f}   top3-conc={full['conc']:.0f}%")
    if blind:
        print(f"  blind earliest-half: PF={blind['pf']:.2f} (n={blind['n']})   "
              f"recent-half: PF={recent['pf']:.2f} (n={recent['n']})" if recent else "")

    print("\n  GATES:")
    print(f"    PF > 1.5 .................. {gate(full['pf'] > 1.5)}  (PF {full['pf']:.2f})")
    print(f"    effective sample (>=30d) . {gate(full['eff_days'] >= 30)}  ({full['eff_days']} days)")
    print(f"    concentration < 60% ...... {gate(full['conc'] < 60)}  ({full['conc']:.0f}%)")
    print(f"    blind-OOS PF > 1.0 ....... {gate(bool(blind) and blind['pf'] > 1.0)}  "
          f"({blind['pf']:.2f})" if blind else "    blind-OOS ................ (no blind trades)")
    print(f"    PROP-FIT (DD >= -$2k) .... {gate(full['dd_usd'] >= -DD_LIMIT)}  (${full['dd_usd']:+,.0f})")
    print("\n  Reminder: also run a drift control and a timing sweep before any verdict;")
    print("  record the result (pass OR fail) in strategy_vault.json. (framework §3-4)\n")


if __name__ == "__main__":
    main()
