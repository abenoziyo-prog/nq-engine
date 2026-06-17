"""T27 — verify MEANREV_FADE_2M in-repo vs operator-external numbers. No tuning.

Full 12mo + strict blind earliest-6mo + recent 6mo + session breakdown + drift.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from collections import defaultdict
from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig
from src.backtest.harness import run_backtest, _stats
from src.engine.meanrev_fade import MeanRevFadeEngine, MeanRevConfig
from src.data.model import Session, tag_session

DATA = "src/data/MNQ_2m_12mo_databento.csv"
SPLIT = date(2025, 12, 15)
EXT = {"full": {"n": 192, "pf": 5.07, "win": 70, "maxdd": -246, "total": 8112},
       "blind": {"n": 111, "pf": 6.98, "win": 74}}

bars = load_bars(DATA)
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"2m bars: {len(tup)}  {bars[0].ts.date()}..{bars[-1].ts.date()}")
trades, _ = run_backtest(tup, MeanRevFadeEngine(MeanRevConfig()), friction_pts=1.0)

def block(label, sub):
    st = _stats(sub)
    days = len({t["entry_ts"].date() for t in sub})
    p = sorted((t["pnl"] for t in sub), reverse=True)
    conc = sum(p[:3]) / st.total_pts * 100 if st.total_pts > 0 else float("nan")
    span_days = (bars[-1].ts.date() - bars[0].ts.date()).days or 1
    print(f"\n[{label}] n={st.n} eff_days={days}", end="")
    if st.n:
        print(f" win%={st.win_pct:.1f} total={st.total_pts:+.1f}pt PF={st.pf:.2f} "
              f"maxDD={st.max_dd:.1f}pt sharpe={st.sharpe_daily:.2f} top3-conc={conc:.0f}%")
    else:
        print(" — none")
    return st

full = block("(a) FULL 12mo", trades)
blind = block("(b) BLIND earliest-6mo (Jun-Dec 2025) — VERDICT", [t for t in trades if t["entry_ts"].date() < SPLIT])
recent = block("(c) RECENT 6mo", [t for t in trades if t["entry_ts"].date() >= SPLIT])
tpd = full.n / ((bars[-1].ts.date() - bars[0].ts.date()).days or 1)
months = defaultdict(float)
for t in trades: months[t["entry_ts"].strftime("%Y-%m")] += t["pnl"]
green = sum(1 for k in months if months[k] > 0)
print(f"  trades/day={tpd:.2f}  green_months={green}/{len(months)}")

# session breakdown on the BLIND slice (entry session)
print("\n[BLIND session breakdown]")
bl = [t for t in trades if t["entry_ts"].date() < SPLIT]
bysess = defaultdict(list)
for t in bl: bysess[tag_session(t["entry_ts"]).value].append(t["pnl"])
for s in ("ASIA", "LONDON", "NY_AM", "NY_PM", "CLOSED"):
    ps = bysess.get(s, [])
    if not ps: continue
    w = sum(x for x in ps if x > 0); l = sum(x for x in ps if x <= 0)
    pf = w / abs(l) if l != 0 else float("inf")
    print(f"  {s:8} n={len(ps):3d} total={sum(ps):+8.1f} PF={pf:.2f}")

print("\n[DRIFT] random NY_AM long")
dc = DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=30, n_entries=200, seed=12345)
dr = run_drift(bars, dc)
print(f"  PF={dr.stats.pf:.2f} MFE/MAE={dr.mfe_mae_ratio:.3f}")

print("\n================ COMPARE TO OPERATOR-EXTERNAL ================")
print(f"  {'':10}{'in-repo':>12}{'external':>12}")
print(f"  full n   {full.n:>12}{EXT['full']['n']:>12}")
print(f"  full PF  {full.pf:>12.2f}{EXT['full']['pf']:>12.2f}")
print(f"  full DD  {full.max_dd:>12.1f}{EXT['full']['maxdd']:>12}")
print(f"  blind n  {blind.n:>12}{EXT['blind']['n']:>12}")
print(f"  blind PF {blind.pf:>12.2f}{EXT['blind']['pf']:>12.2f}")
n_ok = abs(full.n - EXT['full']['n']) <= 0.10 * EXT['full']['n']
pf_ok = abs(full.pf - EXT['full']['pf']) <= 0.5
bpf_ok = abs(blind.pf - EXT['blind']['pf']) <= 0.7
improves = blind.pf > full.pf
print(f"\n  full n within 10%? {n_ok} | full PF within 0.5? {pf_ok} | blind PF within 0.7? {bpf_ok}")
print(f"  blind PF > full PF (anti-overfit signature)? {improves}")
print(f"  => {'MATCH' if (n_ok and pf_ok and bpf_ok) else 'DIVERGENCE'}")
