"""Task B — V4 on the native 1-minute timeframe (exploratory).

The frozen rule k=0.02*ATR(14) is already volatility-relative, so it transfers to
1m without fitting (1m ATR median 7.48 -> 0.15pt band vs 5m 17.66 -> 0.35pt). That
is the primary 1m config. A sensitivity scan (committed in Task B output) shows
performance degrades monotonically as the band widens, and matching the 5m
*absolute* band (k_mult~0.047) is already PF<1 -- so no k re-derivation rescues it.
Reported here: the k=0.02 block + drift benchmark. No P&L optimization.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig
from src.backtest.harness import run_backtest, _stats
from src.engine.v4 import V4Engine, V4Config
from src.data.model import Session

DATA = "src/data/MNQ_1m_12mo_databento.csv"
IS_START, IS_END = date(2026, 3, 8), date(2026, 6, 12)


def block(label, trades):
    st = _stats(trades)
    print(f"\n[{label}]  n={st.n}", end="")
    if st.n == 0:
        print(" — no trades"); return st
    days = sorted({t["entry_ts"].date() for t in trades})
    pnls = sorted((t["pnl"] for t in trades), reverse=True)
    conc = (sum(pnls[:3]) / st.total_pts * 100) if st.total_pts > 0 else float("nan")
    durs = [(t["exit_ts"] - t["entry_ts"]).total_seconds() / 3600 for t in trades]
    print(f"  eff_days={len(days)}")
    print(f"  win%={st.win_pct:.1f} total={st.total_pts:+.1f} PF={st.pf:.2f} maxDD={st.max_dd:.1f} sharpe={st.sharpe_daily:.2f}")
    print(f"  avgW={st.avg_win:.1f} avgL={st.avg_loss:.1f} maxW={st.max_win:.1f} maxL={st.max_loss:.1f}")
    print(f"  avg_dur={sum(durs)/len(durs):.1f}h max_dur={max(durs):.1f}h top3-conc={conc:.0f}%")
    return st


bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"1m bars: {len(tup)}  range {bars[0].ts.date()}..{bars[-1].ts.date()}")

cfg = V4Config(fast=9, slow=50, atr_len=14, k_atr=0.02, accel=True,
               daily_align_size=False, stop_atr=1e9)
trades, _ = run_backtest(tup, V4Engine(cfg), friction_pts=1.0)

full = block("1m FULL 12mo (k=0.02*ATR)", trades)
oos = block("1m OOS unseen (pre Mar8 2026)",
            [t for t in trades if t["entry_ts"].date() < IS_START])
isw = block("1m IS-overlap (Mar8-Jun12 2026)",
            [t for t in trades if IS_START <= t["entry_ts"].date() <= IS_END])

# drift control, horizon = median 1m hold
hb = sorted(int((t["exit_ts"] - t["entry_ts"]).total_seconds() // 60) for t in trades)
H = hb[len(hb)//2] if hb else 30
dcfg = DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=H,
                   n_entries=200, friction_pts=1.0, seed=12345)
dr = run_drift(bars, dcfg)
mc = monte_carlo(bars, dcfg, n_seeds=200)
print(f"\n================ DRIFT CONTROL (1m) ================")
print(f"  V4 median hold = {H} 1m-bars")
print(f"  drift NY_AM long H={H}: n={dr.n} PF={dr.stats.pf:.2f} win%={dr.stats.win_pct:.1f} MFE/MAE={dr.mfe_mae_ratio:.3f}")
print(f"  drift MC (200 seeds): pooled MFE/MAE={mc.pooled_ratio:.3f} mean={mc.mean_ratio:.3f}")
print(f"\n  V4 1m full PF {full.pf:.2f} vs drift PF {dr.stats.pf:.2f} -> "
      f"{'BEATS' if full.pf > dr.stats.pf else 'does NOT beat'} benchmark")
print(f"  5m IS PF was 5.66; 1m full PF {full.pf:.2f}; 1m OOS PF {oos.pf:.2f}")
