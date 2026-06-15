"""Priority 3 — verify the V4_long_15m OOS claim (PF 3.67, DD -$1,080) in-repo.

Runs V4 through the harness on resampled 15m databento data. The operator number
is ambiguous on which k, so test the frozen base (k=0.02*ATR) and the k=0.75/1.5
variants; report which (if any) matches. DD shown in pts and in MNQ $ ($2/pt) for
the $2K-prop lens. No tuning.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig
from src.backtest.harness import run_backtest, _stats
from src.engine.v4 import V4Engine, V4Config
from src.data.model import Session

DATA = "src/data/MNQ_15m_12mo_databento.csv"
NO_STOP = 1e9
IS_START = date(2026, 3, 8)
bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"15m bars: {len(tup)}  {bars[0].ts.date()}..{bars[-1].ts.date()}")

def conc(trades, st):
    p = sorted((t["pnl"] for t in trades), reverse=True)
    return sum(p[:3]) / st.total_pts * 100 if st.total_pts > 0 else float("nan")

def run(label, cfg):
    trades, st = run_backtest(tup, V4Engine(cfg), friction_pts=1.0)
    days = len({t["entry_ts"].date() for t in trades})
    print(f"\n[{label}]")
    print(f"  n={st.n} eff_days={days} win%={st.win_pct:.1f} total={st.total_pts:+.1f}pt "
          f"PF={st.pf:.2f} maxDD={st.max_dd:.1f}pt (=${st.max_dd*2:.0f} @ $2/pt) "
          f"sharpe={st.sharpe_daily:.2f} top3={conc(trades,st):.0f}%")
    # OOS-unseen slice (pre Mar 2026)
    oos = [t for t in trades if t["entry_ts"].date() < IS_START]
    so = _stats(oos)
    print(f"  OOS-unseen (pre Mar8): n={so.n} PF={so.pf:.2f} total={so.total_pts:+.1f} maxDD={so.max_dd:.1f}pt")
    return st

run("V4 base k=0.02*ATR, accel, no stop/align", V4Config(k_atr=0.02, accel=True, daily_align_size=False, stop_atr=NO_STOP))
run("V4 k=0.75 fixed, accel, no stop/align", V4Config(k_fixed=0.75, accel=True, daily_align_size=False, stop_atr=NO_STOP))
run("V4 k=1.5 fixed, accel, no stop/align", V4Config(k_fixed=1.5, accel=True, daily_align_size=False, stop_atr=NO_STOP))
run("V4 base k=0.02*ATR + 4ATR stop", V4Config(k_atr=0.02, accel=True, daily_align_size=False, stop_atr=4.0))

print("\n==== DRIFT CONTROL (15m) ====")
dc = DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=120, n_entries=200, seed=12345)
dr = run_drift(bars, dc); mc = monte_carlo(bars, dc, n_seeds=200)
print(f"  random NY_AM long H=120 (15m bars): PF={dr.stats.pf:.2f} MFE/MAE={dr.mfe_mae_ratio:.3f} (MC {mc.pooled_ratio:.3f})")

print("\n==== OPERATOR CLAIM ====")
print("  V4_long_15m OOS PF 3.67, maxDD -$1,080 (= -540pt @ $2/pt). Compare to rows above.")
