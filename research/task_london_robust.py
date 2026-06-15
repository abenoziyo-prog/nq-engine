"""Concentration-robustness check — LVL_IMB_LONDON_5M, strict blind earliest-6mo.

Re-run the engine (no tuning), isolate the blind slice (Jun-Dec 2025), then report
the slice stats (a) with all trades and (b) with the top-3 winning trades removed.
If PF>1 and total>0 without the top 3, the edge is robust beyond the outliers.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest, _stats
from src.engine.lvl_imb import LvlImbEngine, LvlImbConfig
from src.data.model import Session

DATA = "src/data/MNQ_5m_12mo_databento.csv"
SPLIT = date(2025, 12, 15)

bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
eng = LvlImbEngine(LvlImbConfig(formation_session=Session.LONDON))
trades, _ = run_backtest(tup, eng, friction_pts=1.0, daily_gap_fn=eng.feed_ts)

blind = [t for t in trades if t["entry_ts"].date() < SPLIT]
pnls = sorted((t["pnl"] for t in blind), reverse=True)
top3 = pnls[:3]
ex = pnls[3:]

st_all = _stats(blind)
# rebuild stat block on the trades minus the 3 largest winners
keep = sorted(blind, key=lambda t: t["pnl"], reverse=True)[3:]
st_ex = _stats(keep)

def pf(ps):
    w = sum(p for p in ps if p > 0); l = sum(p for p in ps if p <= 0)
    return (w / abs(l)) if l != 0 else float("inf")

print(f"LVL_IMB_LONDON_5M — blind earliest-6mo (Jun-Dec 2025)")
print(f"  n={st_all.n}, top-3 winners = {[round(x,1) for x in top3]} (sum {sum(top3):+.1f}pt)")
print()
print(f"(a) ALL trades:           n={st_all.n}  total={st_all.total_pts:+.1f}pt  PF={st_all.pf:.2f}  "
      f"win%={st_all.win_pct:.1f}  maxDD={st_all.max_dd:.1f}")
print(f"(b) MINUS top-3 winners:  n={st_ex.n}  total={st_ex.total_pts:+.1f}pt  PF={st_ex.pf:.2f}  "
      f"win%={st_ex.win_pct:.1f}  maxDD={st_ex.max_dd:.1f}")
print()
robust = st_ex.total_pts > 0 and st_ex.pf > 1.0
print(f"  top-3 = {sum(top3)/st_all.total_pts*100:.0f}% of blind profit")
print(f"  VERDICT: {'ROBUST — stays positive PF>1 without its top 3' if robust else 'NOT robust — edge collapses without the top 3'}")
