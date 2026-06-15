"""T24 — verify OB_NYOPEN_BULL_1M in-repo against the operator-external numbers.

Runs src/engine/ob_nyopen.py through the harness on the 1m databento data.
Does NOT tune anything — reports the in-repo stat block beside the external set.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict

from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest
from src.engine.ob_nyopen import OBNyOpenEngine, OBConfig

DATA = "src/data/MNQ_1m_12mo_databento.csv"
EXT = {"n": 798, "pf": 2.26, "total_pts": 7984.0, "max_dd_pts": -162.0, "green": "13/13"}

bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"1m bars: {len(tup)}  {bars[0].ts.date()}..{bars[-1].ts.date()}")

eng = OBNyOpenEngine(OBConfig())
trades, st = run_backtest(tup, eng, friction_pts=1.0, daily_gap_fn=eng.feed_ts)

# green months by entry month
m = defaultdict(float)
for t in trades:
    k = t["entry_ts"].astimezone().strftime("%Y-%m")
    m[k] += t["pnl"]
months = sorted(m)
green = sum(1 for k in months if m[k] > 0)
days = sorted({t["entry_ts"].date() for t in trades})
pnls = sorted((t["pnl"] for t in trades), reverse=True)
top3 = (sum(pnls[:3]) / st.total_pts * 100) if st.total_pts > 0 else float("nan")
durs = [(t["exit_ts"] - t["entry_ts"]).total_seconds() / 60 for t in trades]

print("\n================ IN-REPO STAT BLOCK ================")
print(f"  n={st.n}  eff_days={len(days)}")
print(f"  win%={st.win_pct:.1f}  total={st.total_pts:+.1f}pt  PF={st.pf:.2f}  maxDD={st.max_dd:.1f}  sharpe={st.sharpe_daily:.2f}")
print(f"  avgW={st.avg_win:.1f}  avgL={st.avg_loss:.1f}  maxW={st.max_win:.1f}  maxL={st.max_loss:.1f}")
if durs:
    print(f"  avg_dur={sum(durs)/len(durs):.1f}min  max_dur={max(durs):.0f}min  top3-conc={top3:.0f}%")
print(f"  green months={green}/{len(months)}")

print("\n================ COMPARE TO OPERATOR-EXTERNAL ================")
print(f"  {'metric':10} {'in-repo':>12} {'external':>12}")
print(f"  {'n':10} {st.n:>12} {EXT['n']:>12}")
print(f"  {'PF':10} {st.pf:>12.2f} {EXT['pf']:>12.2f}")
print(f"  {'total pts':10} {st.total_pts:>12.1f} {EXT['total_pts']:>12.1f}")
print(f"  {'maxDD pts':10} {st.max_dd:>12.1f} {EXT['max_dd_pts']:>12.1f}")
print(f"  {'green':10} {str(green)+'/'+str(len(months)):>12} {EXT['green']:>12}")

# tolerance: n +-5%, PF +-0.15, total +-5%
n_ok = abs(st.n - EXT["n"]) <= 0.05 * EXT["n"]
pf_ok = abs(st.pf - EXT["pf"]) <= 0.15
tot_ok = abs(st.total_pts - EXT["total_pts"]) <= 0.05 * abs(EXT["total_pts"])
print(f"\n  within tolerance? n:{n_ok} PF:{pf_ok} total:{tot_ok}  => "
      f"{'MATCH' if (n_ok and pf_ok and tot_ok) else 'MISMATCH'}")
