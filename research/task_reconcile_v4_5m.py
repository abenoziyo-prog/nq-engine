"""Reconcile the V4_5m OOS discrepancy (full PF 2.39 vs blind-slice PF 0.99).

Frozen V4 base (k=0.02*ATR, accel, long-only, NO stop, NO daily-align, 1pt friction)
through the harness on resampled 5m databento. Split by ENTRY date:
  (a) full sample (Jun 2025 - Jun 2026)
  (b) earliest 6 months (Jun-Dec 2025) -- strict blind OOS, never used for tuning
  (c) recent 6 months (Dec 2025 - Jun 2026) -- contains the Mar-Jun 2026 tuning window
No tuning; report what the engine produces.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest, _stats
from src.engine.v4 import V4Engine, V4Config

DATA = "src/data/MNQ_5m_12mo_databento.csv"
SPLIT = date(2025, 12, 15)        # 6 months after data start (2025-06-15)
NO_STOP = 1e9

bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"5m bars: {len(tup)}  {bars[0].ts.date()}..{bars[-1].ts.date()}  split={SPLIT}")

cfg = V4Config(fast=9, slow=50, atr_len=14, k_atr=0.02, accel=True,
               daily_align_size=False, stop_atr=NO_STOP)
trades, _ = run_backtest(tup, V4Engine(cfg), friction_pts=1.0)

def block(label, ts_lo, ts_hi):
    sub = [t for t in trades if ts_lo <= t["entry_ts"].date() < ts_hi]
    st = _stats(sub)
    days = len({t["entry_ts"].date() for t in sub})
    p = sorted((t["pnl"] for t in sub), reverse=True)
    conc = sum(p[:3]) / st.total_pts * 100 if st.total_pts > 0 else float("nan")
    print(f"\n[{label}]  n={st.n} eff_days={days}")
    if st.n:
        print(f"  win%={st.win_pct:.1f} total={st.total_pts:+.1f}pt PF={st.pf:.2f} "
              f"maxDD={st.max_dd:.1f}pt (${st.max_dd*2:.0f}@$2/pt) sharpe={st.sharpe_daily:.2f} top3-conc={conc:.0f}%")
    return st

a = block("(a) FULL 12mo", date(2025, 1, 1), date(2027, 1, 1))
b = block("(b) EARLIEST 6mo (Jun-Dec 2025) — STRICT BLIND OOS", date(2025, 1, 1), SPLIT)
c = block("(c) RECENT 6mo (Dec 2025-Jun 2026) — contains tuning window", SPLIT, date(2027, 1, 1))

print("\n================ RECONCILIATION ================")
print(f"  (a) full PF      = {a.pf:.2f}  (n={a.n}, total {a.total_pts:+.0f}pt)")
print(f"  (b) blind 6mo PF = {b.pf:.2f}  (n={b.n}, total {b.total_pts:+.0f}pt)")
print(f"  (c) recent 6mo PF= {c.pf:.2f}  (n={c.n}, total {c.total_pts:+.0f}pt)")
print(f"  verdict: edge is {'REGIME-DEPENDENT (real in some windows)' if b.pf>1.0 else 'NOT present in the blind window'}; "
      f"full PF is {'inflated by the recent window' if c.pf>b.pf else 'not recent-window driven'}.")
