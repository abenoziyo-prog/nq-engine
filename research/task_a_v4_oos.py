"""Task A — frozen V4 (base) blind out-of-sample validation on 12mo databento 5m.

Frozen config EMA_PROX_V4_5M base: 9x50, k=0.02*ATR(14), accel ON, long-only,
NO daily-align, NO stop, friction 1.0pt. The vault V4 was tuned on 2026-03-08..06-12
(TradingView). This runs the SAME engine on 12 months of exchange-direct data; the
pre-Mar-2026 portion is genuinely out-of-sample.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig
from src.backtest.harness import run_backtest, _stats
from src.engine.v4 import V4Engine, V4Config
from src.data.model import Session

DATA = "src/data/MNQ_5m_12mo_databento.csv"
IS_START, IS_END = date(2026, 3, 8), date(2026, 6, 12)   # vault in-sample window
NO_STOP = 1e9


def block(label, trades):
    st = _stats(trades)
    days = sorted({t["entry_ts"].date() for t in trades})
    pnls = sorted((t["pnl"] for t in trades), reverse=True)
    top3 = sum(pnls[:3])
    conc = (top3 / st.total_pts * 100) if st.total_pts > 0 else float("nan")
    durs = [(t["exit_ts"] - t["entry_ts"]).total_seconds() / 3600 for t in trades]
    print(f"\n[{label}]  n={st.n}  eff_days={len(days)}")
    if st.n == 0:
        return st
    print(f"  win%={st.win_pct:.1f}  total={st.total_pts:+.1f}pt  PF={st.pf:.2f}  "
          f"maxDD={st.max_dd:.1f}  sharpe={st.sharpe_daily:.2f}")
    print(f"  avgW={st.avg_win:.1f}  avgL={st.avg_loss:.1f}  maxW={st.max_win:.1f}  maxL={st.max_loss:.1f}")
    print(f"  avg_dur={sum(durs)/len(durs):.1f}h  max_dur={max(durs):.1f}h  "
          f"top3-conc={conc:.0f}% of profit")
    return st


bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"5m bars: {len(tup)}  range {bars[0].ts.date()} .. {bars[-1].ts.date()}")

cfg = V4Config(fast=9, slow=50, atr_len=14, k_atr=0.02, k_fixed=None,
               accel=True, daily_align_size=False, stop_atr=NO_STOP)
trades, _ = run_backtest(tup, V4Engine(cfg), friction_pts=1.0)

def slc(lo, hi):
    return [t for t in trades if lo <= t["entry_ts"].date() <= hi]

full = block("FULL 12mo (Jun2025-Jun2026)", trades)
oos_unseen = block("OOS UNSEEN (pre-IS: Jun2025-Mar7 2026 + post Jun13)",
                   [t for t in trades if t["entry_ts"].date() < IS_START or t["entry_ts"].date() > IS_END])
aug_feb = block("Aug2025-Feb2026 (never seen)", slc(date(2025, 8, 1), date(2026, 2, 28)))
feb = block("February 2026 (correction month)", slc(date(2026, 2, 1), date(2026, 2, 28)))
is_overlap = block("IS-overlap window on NEW data (Mar8-Jun12 2026)", slc(IS_START, IS_END))

# OOS/IS PF ratio — compare unseen-window PF to the vault base in-sample PF (5.66)
VAULT_IS_PF = 5.66
print("\n================ OOS/IS COMPARISON ================")
print(f"  vault IS base PF (TradingView Mar-Jun)      = {VAULT_IS_PF}")
print(f"  IS-overlap PF on new data (Mar8-Jun12)      = {is_overlap.pf:.2f}")
print(f"  OOS unseen PF                               = {oos_unseen.pf:.2f}")
print(f"  Aug2025-Feb2026 PF                          = {aug_feb.pf:.2f}")
print(f"  OOS/IS PF ratio (unseen / vault 5.66)       = {oos_unseen.pf / VAULT_IS_PF:.2f}")
print(f"  OOS/IS PF ratio (unseen / new-data IS)      = {oos_unseen.pf / is_overlap.pf:.2f}" if is_overlap.pf else "")

# Drift control benchmark — NY_AM long, horizon matched to V4 median hold (5m bars)
med_hold_bars = sorted(int((t["exit_ts"] - t["entry_ts"]).total_seconds() // 300) for t in trades)
H = med_hold_bars[len(med_hold_bars)//2] if med_hold_bars else 12
print(f"\n================ DRIFT CONTROL ================")
print(f"  V4 median hold = {H} 5m-bars")
dcfg = DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=H,
                   n_entries=200, friction_pts=1.0, seed=12345)
dr = run_drift(bars, dcfg)
mc = monte_carlo(bars, dcfg, n_seeds=200)
print(f"  drift NY_AM long H={H}: n={dr.n} PF={dr.stats.pf:.2f} win%={dr.stats.win_pct:.1f} "
      f"total={dr.stats.total_pts:+.1f} MFE/MAE={dr.mfe_mae_ratio:.3f}")
print(f"  drift Monte-Carlo (200 seeds): pooled MFE/MAE={mc.pooled_ratio:.3f} mean={mc.mean_ratio:.3f}")
print(f"\n  V4 full PF {full.pf:.2f} vs drift PF {dr.stats.pf:.2f} -> "
      f"{'BEATS' if full.pf > dr.stats.pf else 'does NOT beat'} benchmark")
