"""Task C — SHOCK_v1 backtest on 12mo 1m databento data (docs/SHOCK_ENGINE_SPEC.md).

Detection params are a-priori per spec (k=4.0, W=180s, m=3.0, A=0.35%, cooldown 30m).
PRE-REGISTRATION: detect at k=4.0 and COUNT events per direction BEFORE any outcome
is computed; only if a direction has <50 events do we drop k to 3.5 (one-step
fallback, spec sec 8). Direction-split UP/DOWN, never pooled. Entry-scheme bake-off
E1-E4, impulse-scaled stops, trail/duration/scratch exits. Honest reporting — no
outcome-driven parameter changes.
"""
import sys, os, math, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import deque, defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from src.backtest.drift_control import load_bars
from src.data.model import Bar, Session, ContextSnapshot, LevelState, tag_session
from src.detector.shock import ShockDetector, ShockParams

ET = ZoneInfo("America/New_York")
TICK = 0.25
FRICTION = 1.0
DATA = "src/data/MNQ_1m_12mo_databento.csv"

bars = load_bars(DATA)
# load_bars sets volume=0; reload volume from the raw csv (drift loader drops it)
import csv as _csv
vols = []
with open(DATA, newline="") as f:
    for r in _csv.DictReader(f):
        vols.append(int(r["volume"]))
for b, v in zip(bars, vols):
    b.volume = v
N = len(bars)
print(f"1m bars: {N}  range {bars[0].ts.date()}..{bars[-1].ts.date()}")

# ---- baselines (a priori, causal) -------------------------------------------
# window (180s = 3-bar) volume per bar
wvol = [0] * N
for i in range(N):
    wvol[i] = bars[i].volume + (bars[i-1].volume if i >= 1 else 0) + (bars[i-2].volume if i >= 2 else 0)
# trailing-~20-day median window-volume per minute-of-day (ET), causal (prior days only)
tod_hist = defaultdict(lambda: deque(maxlen=20))
baseline_by_ts = {}
last_date_for_tod = {}
for i in range(N):
    et = bars[i].ts.astimezone(ET)
    key = et.hour * 60 + et.minute
    dq = tod_hist[key]
    baseline_by_ts[bars[i].ts] = statistics.median(dq) if dq else float("inf")
    # append once per day per TOD
    d = et.date()
    if last_date_for_tod.get(key) != d:
        dq.append(wvol[i]); last_date_for_tod[key] = d
def vol_baseline_fn(ts):
    return baseline_by_ts.get(ts, float("inf"))

# sigma floor = 0.25 * median(|1m log return|) full-sample (quiet-tape guard)
rets = [abs(math.log(bars[i].close / bars[i-1].close)) for i in range(1, N) if bars[i-1].close > 0]
sigma_floor = 0.25 * statistics.median(rets)
print(f"sigma_floor={sigma_floor:.2e}  (0.25 x median|1m logret|)")

# minimal per-bar context (session only; levels not needed for the bake-off P&L)
def ctx_for(b):
    return ContextSnapshot(ts=b.ts, session=tag_session(b.ts), mins_to_session_boundary=0.0,
                           in_moc_window=False, levels=LevelState())

def detect(k):
    det = ShockDetector(ShockParams(k_sigma=k), vol_baseline_fn, sigma_floor)
    evs = []
    for b in bars:
        e = det.on_bar(b, ctx_for(b))
        if e is not None:
            evs.append(e)
    return evs

# ---- PRE-REGISTERED detection + count ---------------------------------------
K = 4.0
events = detect(K)
def counts(evs): return sum(1 for e in evs if e.direction==1), sum(1 for e in evs if e.direction==-1)
up, dn = counts(events)
print(f"\n[PRE-REGISTERED] k={K}: UP={up}  DOWN={dn}  total={len(events)}")
if up < 50 or dn < 50:
    K = 3.5
    events = detect(K)
    up, dn = counts(events)
    print(f"[FALLBACK one-step] k={K}: UP={up}  DOWN={dn}  total={len(events)}  (a direction had <50 at 4.0)")
print(f"FINAL detection threshold k={K}")

idx = {b.ts: i for i, b in enumerate(bars)}

# ---- trade simulation (spec sec 5-6) ----------------------------------------
def manage(entry_i, entry_px, direction, imp_open, imp_extreme, imp_range):
    """Walk forward from entry; return exit pnl in points (net friction) or None."""
    sgn = direction
    retrace50 = imp_extreme - sgn * 0.5 * imp_range          # 50% retrace level
    init_stop = (max(entry_px - 0.45*imp_range, retrace50) if sgn==1
                 else min(entry_px + 0.45*imp_range, retrace50))
    trail = init_stop
    entry_ts = bars[entry_i].ts
    # time guard: next 17:00 ET (globex close) after entry
    et = entry_ts.astimezone(ET)
    guard_date = et.date() if et.hour < 17 else (et + timedelta(days=1)).date()
    from datetime import datetime, time as _t
    guard = datetime.combine(guard_date, _t(17, 0), tzinfo=ET).astimezone(bars[0].ts.tzinfo)
    reached_1R = False
    lows = deque(maxlen=15); highs = deque(maxlen=15)
    j = entry_i + 1
    while j < N:
        b = bars[j]
        # swing-structure trail (ratchets toward price); pnl = sgn*(exit-entry)-friction
        if sgn == 1:
            if lows: trail = max(trail, min(lows))
            if b.low <= trail: return sgn*(trail - entry_px) - FRICTION
            if b.high >= entry_px + imp_range: reached_1R = True
        else:
            if highs: trail = min(trail, max(highs))
            if b.high >= trail: return sgn*(trail - entry_px) - FRICTION
            if b.low <= entry_px - imp_range: reached_1R = True
        lows.append(b.low); highs.append(b.high)
        # time guard
        if b.ts >= guard:
            return sgn*(b.close - entry_px) - FRICTION
        # scratch: neither +1R nor stop within 60 min -> exit market
        if (b.ts - entry_ts) >= timedelta(minutes=60) and not reached_1R:
            return sgn*(b.close - entry_px) - FRICTION
        j += 1
    return sgn*(bars[-1].close - entry_px) - FRICTION   # ran out of data

def entry_E1(it, direction, imp_open, imp_extreme, imp_range):
    if it+1 >= N: return None
    return it+1, bars[it+1].open

def entry_E2(it, direction, imp_open, imp_extreme, imp_range):
    # limit in 25-40% retrace zone within 15 min, extreme not broken first
    zone_far = imp_extreme - direction*0.40*imp_range     # 40% retrace (deepest fill allowed)
    fill = imp_extreme - direction*0.30*imp_range          # 30% retrace target
    for j in range(it+1, min(it+16, N)):
        b = bars[j]
        if direction==1:
            if b.high > imp_extreme: return None            # extreme broken before pullback
            if b.low <= fill: return j, fill                # dipped into zone -> filled at 30%
        else:
            if b.low < imp_extreme: return None
            if b.high >= fill: return j, fill
    return None

def entry_E3(it, direction, imp_open, imp_extreme, imp_range):
    # stop order 2 ticks beyond extreme, armed after 3-min hold, valid 20 min
    trig = imp_extreme + direction*2*TICK
    for j in range(it+3, min(it+3+20, N)):
        b = bars[j]
        if direction==1 and b.high >= trig: return j, trig
        if direction==-1 and b.low <= trig: return j, trig
    return None

schemes = {"E1": entry_E1, "E2": entry_E2, "E3": entry_E3}

def stat_block(pnls):
    n=len(pnls)
    if n==0: return dict(n=0)
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    tot=sum(pnls); pf=(sum(wins)/abs(sum(losses))) if losses and sum(losses)!=0 else float('inf')
    return dict(n=n, win=100*len(wins)/n, total=tot, pf=pf,
                avgW=(sum(wins)/len(wins) if wins else 0), avgL=(sum(losses)/len(losses) if losses else 0),
                maxW=max(pnls), maxL=min(pnls))

results = {d: {s: [] for s in ["E1","E2","E3","E4"]} for d in (1,-1)}
fills = {d: {s: 0 for s in ["E1","E2","E3"]} for d in (1,-1)}
for e in events:
    it = idx.get(e.ts_trigger)
    if it is None: continue
    d = e.direction
    per = {}
    for s, fn in schemes.items():
        r = fn(it, d, e.impulse_open, e.impulse_extreme, e.impulse_range_pts)
        if r is None:
            per[s] = None; continue
        ei, epx = r
        fills[d][s] += 1
        pnl = manage(ei, epx, d, e.impulse_open, e.impulse_extreme, e.impulse_range_pts)
        per[s] = pnl
        if pnl is not None: results[d][s].append(pnl)
    # E4 hybrid = 0.5 E2 + 0.5 E3 (half size each; only legs that filled)
    legs = [per["E2"], per["E3"]]
    legs = [x for x in legs if x is not None]
    if legs:
        results[d]["E4"].append(0.5*sum(legs))

for d, name in ((1,"UP"),(-1,"DOWN")):
    print(f"\n================ {name}-SHOCK bake-off (k={K}) ================")
    print(f"  fills: E1={fills[d]['E1']} E2={fills[d]['E2']} E3={fills[d]['E3']}")
    for s in ["E1","E2","E3","E4"]:
        b=stat_block(results[d][s])
        if b['n']==0: print(f"  {s}: n=0"); continue
        print(f"  {s}: n={b['n']:3d} win%={b['win']:5.1f} total={b['total']:+9.1f} PF={b['pf']:5.2f} "
              f"avgW={b['avgW']:7.1f} avgL={b['avgL']:7.1f} maxW={b['maxW']:7.1f} maxL={b['maxL']:8.1f}")

# session + sigma distribution (context)
print("\nEvent context:")
for name,d in (("UP",1),("DOWN",-1)):
    es=[e for e in events if e.direction==d]
    sess=defaultdict(int)
    for e in es: sess[e.session]+=1
    sig=sorted(e.shock_sigma for e in es)
    rng=sorted(e.impulse_range_pts for e in es)
    if es:
        print(f"  {name}: sessions={dict(sess)} median_sigma={sig[len(sig)//2]:.1f} median_range={rng[len(rng)//2]:.1f}pt")
