"""LVL_IMB zone backtest — three slices + drift, status set by the BLIND slice.

Usage: python research/task_lvl_imb.py LONDON|ASIA
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig
from src.backtest.harness import run_backtest, _stats
from src.engine.lvl_imb import LvlImbEngine, LvlImbConfig
from src.data.model import Session

DATA = "src/data/MNQ_5m_12mo_databento.csv"
SPLIT = date(2025, 12, 15)            # 6 months after data start
which = sys.argv[1] if len(sys.argv) > 1 else "LONDON"
sess = Session.LONDON if which == "LONDON" else Session.ASIA

bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
eng = LvlImbEngine(LvlImbConfig(formation_session=sess))
trades, _ = run_backtest(tup, eng, friction_pts=1.0, daily_gap_fn=eng.feed_ts)
print(f"=== LVL_IMB {which} ===  5m bars {len(tup)}  {bars[0].ts.date()}..{bars[-1].ts.date()}")
print(f"  gated_skips={eng.gated_skips} (tapped but EMA-gate failed)")

def block(label, lo, hi):
    sub = [t for t in trades if lo <= t["entry_ts"].date() < hi]
    st = _stats(sub)
    days = len({t["entry_ts"].date() for t in sub})
    p = sorted((t["pnl"] for t in sub), reverse=True)
    conc = sum(p[:3]) / st.total_pts * 100 if st.total_pts > 0 else float("nan")
    print(f"\n[{label}] n={st.n} eff_days={days}", end="")
    if st.n:
        print(f" win%={st.win_pct:.1f} total={st.total_pts:+.1f}pt PF={st.pf:.2f} "
              f"maxDD={st.max_dd:.1f}pt sharpe={st.sharpe_daily:.2f} top3-conc={conc:.0f}%")
    else:
        print(" — no trades")
    return st, days, conc

a, _, _ = block("(a) FULL 12mo", date(2025, 1, 1), date(2027, 1, 1))
b, b_days, b_conc = block("(b) BLIND earliest-6mo (Jun-Dec 2025) — VERDICT SLICE", date(2025, 1, 1), SPLIT)
c, _, _ = block("(c) RECENT 6mo (Dec 2025-Jun 2026)", SPLIT, date(2027, 1, 1))

dc = DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=24, n_entries=200, seed=12345)
dr = run_drift(bars, dc); mc = monte_carlo(bars, dc, n_seeds=200)
print(f"\n[DRIFT] random NY_AM long H=24: PF={dr.stats.pf:.2f} MFE/MAE={dr.mfe_mae_ratio:.3f} (MC {mc.pooled_ratio:.3f})")

print("\n================ VERDICT (by BLIND slice b) ================")
beats = b.pf > dr.stats.pf
adequate = b.n >= 30
conc_ok = not (b_conc == b_conc) or b_conc < 60   # nan (loser) fails anyway via pf
cand = b.pf > 1.5 and beats and adequate and (b_conc < 60 if b_conc == b_conc else False)
print(f"  blind PF={b.pf:.2f} (>1.5? {b.pf>1.5}) | beats drift {dr.stats.pf:.2f}? {beats} | "
      f"n={b.n} (>=30? {adequate}) | top3-conc={b_conc:.0f}% (<60%? {b_conc<60 if b_conc==b_conc else 'n/a'})")
print(f"  => {'CANDIDATE' if cand else 'FALSIFIED / FINDING(under-powered)'}")
