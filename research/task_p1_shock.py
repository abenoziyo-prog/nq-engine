"""Priority 1 — SHOCK_v1 backtest. Pre-registered detection; bake-off; drift; eff-n.

Detection threshold is FIXED before any outcome is computed (k=4.0; one-step
fallback to 3.5 only if <50 events/direction). Outcomes computed only after.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, statistics
from collections import defaultdict

from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig
from src.data.model import Session
from src.detector.shock import ShockParams
from src.engine.shock_v1 import compute_baselines, detect, run_bakeoff

DATA = "src/data/MNQ_1m_12mo_databento.csv"
bars = load_bars(DATA)
# load_bars zeroes volume; restore it from the csv (SHOCK needs volume)
with open(DATA, newline="") as f:
    for b, row in zip(bars, csv.DictReader(f)):
        b.volume = int(row["volume"])
print(f"1m bars: {len(bars)}  {bars[0].ts.date()}..{bars[-1].ts.date()}")

baselines = compute_baselines(bars)
print(f"sigma_floor={baselines[1]:.2e}")

def counts(evs): return sum(e["dir"] == 1 for e in evs), sum(e["dir"] == -1 for e in evs)

# ---- PRE-REGISTERED detection (count BEFORE outcomes) ----
K = 4.0
events = detect(bars, ShockParams(k_sigma=K), baselines)
up, dn = counts(events)
print(f"\n[PRE-REGISTERED] k={K}: UP={up} DOWN={dn}")
if up < 50 or dn < 50:
    K = 3.5
    events = detect(bars, ShockParams(k_sigma=K), baselines)
    up, dn = counts(events)
    print(f"[one-step fallback] k={K}: UP={up} DOWN={dn}")
print(f"FINAL k={K}  -> UP {'>=50 OK' if up>=50 else 'UNDER-POWERED (<50)'}, "
      f"DOWN {'>=50 OK' if dn>=50 else 'UNDER-POWERED (<50)'}")

res, meta, fills = run_bakeoff(bars, events)

def block(pnls, tss):
    n = len(pnls)
    if n == 0: return None
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    tot = sum(pnls); pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf")
    days = len({t.date() for t in tss})
    srt = sorted(pnls, reverse=True)
    conc = sum(srt[:3]) / tot * 100 if tot > 0 else float("nan")
    return dict(n=n, win=100 * len(wins) / n, total=tot, pf=pf, days=days, conc=conc,
                maxW=max(pnls), maxL=min(pnls))

for d, name in ((1, "UP"), (-1, "DOWN")):
    print(f"\n==== {name}-SHOCK bake-off (k={K}, fills E1/E2/E3={fills[d]['E1']}/{fills[d]['E2']}/{fills[d]['E3']}) ====")
    for s in ("E1", "E2", "E3", "E4"):
        b = block(res[d][s], meta[d][s])
        if not b: print(f"  {s}: n=0"); continue
        print(f"  {s}: n={b['n']:3d} eff_days={b['days']:3d} win%={b['win']:5.1f} "
              f"total={b['total']:+8.1f} PF={b['pf']:5.2f} top3-conc={b['conc']:4.0f}% "
              f"maxW={b['maxW']:.0f} maxL={b['maxL']:.0f}")

# ---- mandatory drift control (harness-based) ----
print("\n==== DRIFT CONTROL ====")
dc = DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=60, n_entries=200, seed=12345)
dr = run_drift(bars, dc); mc = monte_carlo(bars, dc, n_seeds=200)
print(f"  random NY_AM long H=60: PF={dr.stats.pf:.2f} MFE/MAE={dr.mfe_mae_ratio:.3f} (MC pooled {mc.pooled_ratio:.3f})")

# verdict
e3 = block(res[1]["E3"], meta[1]["E3"])
print("\n==== VERDICT ====")
print(f"  UP events={up} (gate=50). Best UP scheme E3: PF {e3['pf']:.2f}, n={e3['n']}, eff_days={e3['days']}.")
print(f"  UP {'UNDER-POWERED (<50 events) -> no verdict forced; stays FINDING' if up<50 else 'adequate n'}.")
