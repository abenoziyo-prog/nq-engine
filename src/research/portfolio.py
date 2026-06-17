"""Aggregate portfolio model — runs EVERY strategy with a runnable engine as a
paper sleeve (operator directive 2026-06-17: log everything, gather real-condition
forward data; nothing to lose since this is PAPER only, places NO orders).

Sleeves are TAGGED by tier so the record stays honest:
  CORE            capital-eligible, verified + OOS-surviving
  DIVERSIFIER     verified but small-n / fragile (observation)
  WATCH           weak / OOS-failed / unverified-legacy (observation)
  FALSIFIED-WATCH known dead -> confirm they stay dead forward
  SHOCK           event-driven, volume-based (special driver; exit_ts approx)

Capital eligibility is UNCHANGED by adding sleeves: only CORE earns size. Paper
logging the rest is free and is exactly how the weak/dead ones earn or lose a
place under real conditions. Equal weight, 1 contract/sleeve, long-only, 1pt
friction. The deterministic bridge's risk manager (max_contracts=3, $50K/$2K)
clamps total live size; this harness never places orders.

Strategies that CANNOT be wired (and why):
  EMA_PROX_V4_SHORT_5M  -> short; harness is long-only
  EMA_CROSS_CONFIRMED / EMA_CROSS_CASCADE_RSI55 -> no engine module built
  OB_STRICT_SINGLE_TOUCH / EMA_PROX_V4_SWING    -> PARKED, no engine
  DAY_MAP_V1            -> context/probability map, not a tradeable P&L strategy
  OB_NYOPEN_VOLUME_CONFIRM / _MACRO_WINDOW      -> ablations, no standalone engine
  EMA_PROX_V4_1M_TEST   -> superseded 2-day stub (covered by EMA_PROX_V4_1M)

Run:  python -m src.research.portfolio            # aggregate characterization
      python -m src.research.portfolio --forward  # paper-log post-window trades
"""
from __future__ import annotations
import os, sys, csv, json, argparse

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from datetime import date
from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest, _stats
from src.engine.meanrev_fade import MeanRevFadeEngine, MeanRevConfig
from src.engine.lvl_imb import LvlImbEngine, LvlImbConfig
from src.engine.v4 import V4Engine, V4Config
from src.engine.ob_nyopen import OBNyOpenEngine
from src.engine.ob_reentry import OBReentryEngine
from src.data.model import Session

FRICTION = 1.0
NO_STOP = 1e9
WINDOW_END = date(2026, 6, 14)
BLIND_SPLIT = date(2025, 12, 15)
DATAF = {tf: f"src/data/MNQ_{tf}_12mo_databento.csv" for tf in ("1m", "2m", "5m", "15m")}
LOG_PATH = os.path.join(_REPO, "logs", "portfolio_paper.jsonl")
TALLY_PATH = os.path.join(_REPO, "logs", "portfolio_paper_tally.json")

def S(id, tf, tier, status, capital, make):
    return dict(id=id, tf=tf, tier=tier, status=status, capital=capital, make=make)

SLEEVES = [
    S("MEANREV_FADE_2M", "2m", "CORE", "CANDIDATE", True,
      lambda: MeanRevFadeEngine(MeanRevConfig(entry_dist=-3.0, exit_dist=-0.5))),
    S("LVL_IMB_LONDON_5M", "5m", "CORE", "FINDING", True,
      lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.LONDON))),
    S("LVL_IMB_ASIA_5M", "5m", "DIVERSIFIER", "FINDING", False,
      lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.ASIA))),
    S("EMA_PROX_V4_15M", "15m", "DIVERSIFIER", "CANDIDATE", False,
      lambda: V4Engine(V4Config(k_atr=0.02, accel=True, daily_align_size=False, stop_atr=NO_STOP))),
    S("EMA_PROX_V4_5M", "5m", "WATCH", "FROZEN(OOS-failed)", False,
      lambda: V4Engine(V4Config(k_atr=0.02, accel=True, daily_align_size=False, stop_atr=NO_STOP))),
    S("EMA_PROX_V0B_5M", "5m", "WATCH", "CANDIDATE(legacy)", False,
      lambda: V4Engine(V4Config(k_fixed=0.75, accel=False, daily_align_size=False, stop_atr=NO_STOP))),
    S("EMA_PROX_V4_15M_K075", "15m", "WATCH", "CANDIDATE(legacy)", False,
      lambda: V4Engine(V4Config(k_fixed=0.75, accel=True, daily_align_size=False, stop_atr=NO_STOP))),
    S("EMA_PROX_V4_15M_K15", "15m", "WATCH", "CANDIDATE(legacy)", False,
      lambda: V4Engine(V4Config(k_fixed=1.5, accel=True, daily_align_size=False, stop_atr=NO_STOP))),
    S("EMA_PROX_V0_15M_K15", "15m", "WATCH", "FINDING", False,
      lambda: V4Engine(V4Config(k_fixed=1.5, accel=False, daily_align_size=False, stop_atr=NO_STOP))),
    S("EMA_PROX_V4_1M", "1m", "WATCH", "SPEC_ONLY(fails)", False,
      lambda: V4Engine(V4Config(k_atr=0.02, accel=True, daily_align_size=False, stop_atr=NO_STOP))),
    S("OB_NYOPEN_BULL_1M", "1m", "FALSIFIED-WATCH", "FALSIFIED", False, lambda: OBNyOpenEngine()),
    S("OB_NYOPEN_REENTRY_1M", "1m", "FALSIFIED-WATCH", "FALSIFIED", False, lambda: OBReentryEngine()),
]

_BARS = {}
def bars(tf):
    if tf not in _BARS:
        _BARS[tf] = load_bars(DATAF[tf])
    return _BARS[tf]

def _bars_with_volume(tf):
    b = bars(tf)
    with open(DATAF[tf], newline="") as f:
        for x, r in zip(b, csv.DictReader(f)):
            x.volume = int(r["volume"])
    return b


def shock_sleeve():
    """SHOCK_V1 UP-shock E3 (k=3.5 pre-registered fallback). Volume-driven, event
    engine -> exit_ts approximated as entry_ts for paper logging (flagged)."""
    try:
        from src.engine.shock_v1 import compute_baselines, detect, run_bakeoff
        from src.detector.shock import ShockParams
        b = _bars_with_volume("1m")
        base = compute_baselines(b)
        events = detect(b, ShockParams(k_sigma=3.5), base)
        res, meta, _ = run_bakeoff(b, events)
        out = []
        for pnl, ts in zip(res[1]["E3"], meta[1]["E3"]):
            out.append({"entry_ts": ts, "exit_ts": ts, "pnl": pnl, "sleeve": "SHOCK_V1_UP_E3"})
        return out
    except Exception as e:
        print(f"  [SHOCK sleeve skipped: {e}]")
        return []


def run_all_sleeves():
    allt, per, meta = [], {}, {}
    for s in SLEEVES:
        b = bars(s["tf"])
        tup = [(x.ts, x.open, x.high, x.low, x.close) for x in b]
        eng = s["make"]()
        kw = {"daily_gap_fn": eng.feed_ts} if hasattr(eng, "feed_ts") else {}
        trades, _ = run_backtest(tup, eng, friction_pts=FRICTION, **kw)
        for t in trades:
            t["sleeve"] = s["id"]
        per[s["id"]] = trades; meta[s["id"]] = s; allt.extend(trades)
    sh = shock_sleeve()
    if sh:
        per["SHOCK_V1_UP_E3"] = sh
        meta["SHOCK_V1_UP_E3"] = S("SHOCK_V1_UP_E3", "1m", "SHOCK", "FINDING(under-powered)", False, None)
        allt.extend(sh)
    allt.sort(key=lambda t: t["exit_ts"])
    return allt, per, meta


def agg(trades):
    st = _stats(trades)
    pnls = sorted((t["pnl"] for t in trades), reverse=True)
    conc = sum(pnls[:3]) / st.total_pts * 100 if (st.n and st.total_pts > 0) else float("nan")
    days = len({t["entry_ts"].date() for t in trades})
    return st, days, conc


def max_concurrency(trades):
    evs = []
    for t in trades:
        evs.append((t["entry_ts"], 1)); evs.append((t["exit_ts"], -1))
    evs.sort(key=lambda e: (e[0], e[1]))
    cur = mx = 0
    for _, d in evs:
        cur += d; mx = max(mx, cur)
    return mx


def slice_entry(trades, lo, hi):
    return [t for t in trades if (lo is None or t["entry_ts"].date() > lo) and (hi is None or t["entry_ts"].date() <= hi)]


def report_backtest():
    allt, per, meta = run_all_sleeves()
    names = list(per.keys())
    print(f"AGGREGATE PORTFOLIO — ALL {len(names)} runnable sleeves (paper; 1 contract each, 1pt friction)\n")
    print(f"{'SLEEVE':22}{'tier':16}{'status':20}{'cap':4}{'full n':>7}{'full PF':>8}{'blind n':>8}{'blind PF':>9}")
    for nm in names:
        m = meta[nm]; tr = per[nm]
        full, _, _ = agg(tr); bl, _, _ = agg(slice_entry(tr, None, BLIND_SPLIT))
        cap = "Y" if m["capital"] else "-"
        print(f"{nm:22}{m['tier']:16}{m['status']:20}{cap:4}{full.n:>7}{full.pf:>8.2f}{bl.n:>8}{bl.pf:>9.2f}")

    def aline(label, trades):
        st, days, conc = agg(trades)
        if not st.n: print(f"  {label:30} n=0"); return
        print(f"  {label:30} n={st.n:4d} win%={st.win_pct:5.1f} total={st.total_pts:+9.1f}pt "
              f"PF={st.pf:5.2f} maxDD={st.max_dd:8.1f}pt(${st.max_dd*2:.0f}) sharpe={st.sharpe_daily:5.2f} top3={conc:.0f}%")

    cap_ids = {s["id"] for s in SLEEVES if s["capital"]}
    for sname, lo, hi in [("FULL 12mo", None, None), ("BLIND earliest-6mo", None, BLIND_SPLIT), ("RECENT 6mo", BLIND_SPLIT, None)]:
        sl = slice_entry(allt, lo, hi)
        print(f"\n[{sname}]")
        aline("ALL sleeves (paper)", sl)
        aline("CORE only (capital-eligible)", [t for t in sl if t["sleeve"] in cap_ids])

    print(f"\nmax concurrent open positions: ALL={max_concurrency(allt)}  "
          f"CORE={max_concurrency([t for t in allt if t['sleeve'] in cap_ids])}  "
          f"(risk manager max_contracts=3 clamps total live size)")
    print("Capital eligibility UNCHANGED: only CORE (MEANREV_FADE_2M + LVL_IMB_LONDON_5M) earns size; "
          "all others are observation-only paper sleeves.")


# ---------- forward paper log (post-window, idempotent, NO orders) ----------
def _existing():
    keys = set()
    if os.path.exists(LOG_PATH):
        for ln in open(LOG_PATH):
            if ln.strip():
                r = json.loads(ln); keys.add((r["sleeve"], r["entry_ts"]))
    return keys


def report_forward():
    allt, per, meta = run_all_sleeves()
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    latest = max(bars(tf)[-1].ts.date() for tf in DATAF)
    fwd = [t for t in allt if t["entry_ts"].date() > WINDOW_END]
    if not fwd:
        print(f"no forward data yet — latest bar ~{latest} <= window end {WINDOW_END}. "
              f"Add post-{WINDOW_END} bars (resample 1m -> 2m/5m/15m) to begin the paper record across all {len(per)} sleeves.")
        if os.path.exists(LOG_PATH):
            print(f"current portfolio paper tally: n={sum(1 for l in open(LOG_PATH) if l.strip())}")
        return
    existing = _existing()
    new = [t for t in fwd if (t["sleeve"], t["entry_ts"].isoformat()) not in existing]
    with open(LOG_PATH, "a") as f:
        for t in sorted(new, key=lambda x: x["exit_ts"]):
            f.write(json.dumps({"sleeve": t["sleeve"], "entry_ts": t["entry_ts"].isoformat(),
                                "exit_ts": t["exit_ts"].isoformat(), "pnl_pts": round(t["pnl"], 2)}) + "\n")
    rows = [json.loads(l) for l in open(LOG_PATH) if l.strip()]
    pnls = [r["pnl_pts"] for r in rows]; w = [p for p in pnls if p > 0]; l = [p for p in pnls if p <= 0]
    pf = sum(w) / abs(sum(l)) if l and sum(l) != 0 else float("inf")
    cum = peak = mdd = 0.0
    for p in pnls: cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    tal = {"n": len(rows), "total_pts": round(sum(pnls), 1), "pf": round(pf, 2) if pf != float("inf") else None,
           "max_dd_pts": round(mdd, 1), "max_dd_usd": round(mdd * 2, 0)}
    json.dump(tal, open(TALLY_PATH, "w"), indent=2)
    print(f"logged {len(new)} new forward trade(s) across {len(per)} sleeves. PORTFOLIO PAPER TALLY: {tal}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Aggregate portfolio paper model (all runnable sleeves)")
    ap.add_argument("--forward", action="store_true")
    a = ap.parse_args()
    report_forward() if a.forward else report_backtest()
