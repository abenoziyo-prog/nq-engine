"""Priority 2 — OB_NYOPEN_REENTRY_1M backtest via the unmodified harness + drift.

Watch the overcounting risk: report effective day-level n, distinct zones, entries
per zone, and profit concentration. A high raw n from re-entries on few zones is a
red flag (constitution rule 7).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import Counter

from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig
from src.backtest.harness import run_backtest
from src.data.model import Session
from src.engine.ob_reentry import OBReentryEngine, OBReentryConfig

DATA = "src/data/MNQ_1m_12mo_databento.csv"
bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"1m bars: {len(tup)}  {bars[0].ts.date()}..{bars[-1].ts.date()}")

eng = OBReentryEngine(OBReentryConfig())
trades, st = run_backtest(tup, eng, friction_pts=1.0, daily_gap_fn=eng.feed_ts)

days = sorted({t["entry_ts"].date() for t in trades})
months = sorted({t["entry_ts"].strftime("%Y-%m") for t in trades})
from collections import defaultdict
mpnl = defaultdict(float)
for t in trades:
    mpnl[t["entry_ts"].strftime("%Y-%m")] += t["pnl"]
green = sum(1 for k in mpnl if mpnl[k] > 0)
pnls = sorted((t["pnl"] for t in trades), reverse=True)
top3 = sum(pnls[:3]) / st.total_pts * 100 if st.total_pts > 0 else float("nan")
durs = [(t["exit_ts"] - t["entry_ts"]).total_seconds() / 60 for t in trades]

print("\n================ STAT BLOCK ================")
print(f"  n={st.n}  eff_days={len(days)}  months={len(months)}")
print(f"  win%={st.win_pct:.1f} total={st.total_pts:+.1f}pt PF={st.pf:.2f} maxDD={st.max_dd:.1f} sharpe={st.sharpe_daily:.2f}")
print(f"  avgW={st.avg_win:.1f} avgL={st.avg_loss:.1f} maxW={st.max_win:.1f} maxL={st.max_loss:.1f}")
if durs: print(f"  avg_dur={sum(durs)/len(durs):.1f}min max_dur={max(durs):.0f}min top3-conc={top3:.0f}% green={green}/{len(months)}")

print("\n================ OVERCOUNTING INSTRUMENTATION ================")
epz = eng.entries_per_zone
zones_used = len(epz)
ent_counts = sorted(epz.values(), reverse=True)
print(f"  distinct zones that produced >=1 entry: {zones_used}")
print(f"  total entries: {sum(ent_counts)}  (=n)  | entries/zone: max={ent_counts[0] if ent_counts else 0} "
      f"median={ent_counts[len(ent_counts)//2] if ent_counts else 0}")
dist = Counter(ent_counts)
print(f"  entries-per-zone distribution (entries:count): {dict(sorted(dist.items()))}")
print(f"  trades from re-entries (n - distinct zones): {st.n - zones_used} "
      f"({100*(st.n-zones_used)/st.n:.0f}% of trades are re-entries)" if st.n else "")
print(f"  skipped taps (in-position / same-bar contention): {eng.skipped}")

print("\n================ DRIFT CONTROL ================")
dc = DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=60, n_entries=200, seed=12345)
dr = run_drift(bars, dc); mc = monte_carlo(bars, dc, n_seeds=200)
print(f"  random NY_AM long H=60: PF={dr.stats.pf:.2f} MFE/MAE={dr.mfe_mae_ratio:.3f} (MC pooled {mc.pooled_ratio:.3f})")

print("\n================ VERDICT GATE ================")
beats = st.pf > dr.stats.pf
print(f"  PF {st.pf:.2f} vs drift {dr.stats.pf:.2f} -> {'beats' if beats else 'does NOT beat'}; PF>1.5? {st.pf>1.5}")
print(f"  => {'CANDIDATE' if (beats and st.pf>1.5) else 'FALSIFIED'} (subject to concentration/eff-n review)")
