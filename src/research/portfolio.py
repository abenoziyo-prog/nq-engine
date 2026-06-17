"""Aggregate portfolio model — runs the deployable/promising sleeves as one model
and (a) characterizes the combined edge over the 12mo history, (b) paper-logs
forward trades (post-backtest window) to logs/portfolio_paper.jsonl.

Sleeves = strategies with a genuine verified / OOS-surviving edge (FALSIFIED,
PARKED, OOS-failed, and unverified-legacy entries are deliberately excluded):
  - MEANREV_FADE_2M    2m  MeanRev fade (verified config: entry -3.0, exit -0.5)
  - LVL_IMB_LONDON_5M  5m  London OB+FVG zone (verified, robust blind)
  - LVL_IMB_ASIA_5M    5m  Asia zone (verified, under-powered)
  - EMA_PROX_V4_15M    15m V4 proximity base (verified, low-n)

Equal weight, 1 contract per sleeve, long-only, 1pt friction. Sleeves can be long
concurrently; the deterministic bridge's risk manager (max_contracts=3, $50K/$2K)
would clamp total size live. This harness places NO orders — paper record only.

Run:  python -m src.research.portfolio            # aggregate backtest characterization
      python -m src.research.portfolio --forward  # paper-log post-window trades
"""
from __future__ import annotations
import os, sys, json, argparse
from datetime import date, datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest, _stats
from src.engine.meanrev_fade import MeanRevFadeEngine, MeanRevConfig
from src.engine.lvl_imb import LvlImbEngine, LvlImbConfig
from src.engine.v4 import V4Engine, V4Config
from src.data.model import Session

FRICTION = 1.0
WINDOW_END = date(2026, 6, 14)        # 12mo backtest end / forward boundary
BLIND_SPLIT = date(2025, 12, 15)      # earliest-6mo = strict blind
DATAF = {tf: f"src/data/MNQ_{tf}_12mo_databento.csv" for tf in ("2m", "5m", "15m")}
LOG_PATH = os.path.join(_REPO, "logs", "portfolio_paper.jsonl")
TALLY_PATH = os.path.join(_REPO, "logs", "portfolio_paper_tally.json")

SLEEVES = [
    ("MEANREV_FADE_2M", "2m", lambda: MeanRevFadeEngine(MeanRevConfig(entry_dist=-3.0, exit_dist=-0.5))),
    ("LVL_IMB_LONDON_5M", "5m", lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.LONDON))),
    ("LVL_IMB_ASIA_5M", "5m", lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.ASIA))),
    ("EMA_PROX_V4_15M", "15m", lambda: V4Engine(V4Config(k_atr=0.02, accel=True, daily_align_size=False, stop_atr=1e9))),
]

_BARS = {}
def bars(tf):
    if tf not in _BARS:
        _BARS[tf] = load_bars(DATAF[tf])
    return _BARS[tf]


def run_all_sleeves():
    """Return every sleeve's trades, each tagged with 'sleeve'. One model, one trade list."""
    allt = []
    per = {}
    for name, tf, factory in SLEEVES:
        b = bars(tf)
        tup = [(x.ts, x.open, x.high, x.low, x.close) for x in b]
        eng = factory()
        kw = {"daily_gap_fn": eng.feed_ts} if hasattr(eng, "feed_ts") else {}
        trades, _ = run_backtest(tup, eng, friction_pts=FRICTION, **kw)
        for t in trades:
            t["sleeve"] = name
        per[name] = trades
        allt.extend(trades)
    allt.sort(key=lambda t: t["exit_ts"])
    return allt, per


def block(trades):
    st = _stats(trades)
    days = len({t["entry_ts"].date() for t in trades}) if trades else 0
    return st, days


def max_concurrency(trades):
    """Max simultaneous open positions across sleeves (entry_ts..exit_ts intervals)."""
    evs = []
    for t in trades:
        evs.append((t["entry_ts"], 1)); evs.append((t["exit_ts"], -1))
    evs.sort(key=lambda e: (e[0], e[1]))
    cur = mx = 0
    for _, d in evs:
        cur += d; mx = max(mx, cur)
    return mx


def slice_by_entry(trades, lo=None, hi=None):
    return [t for t in trades if (lo is None or t["entry_ts"].date() > lo) and (hi is None or t["entry_ts"].date() <= hi)]


def report_backtest():
    allt, per = run_all_sleeves()
    print("AGGREGATE PORTFOLIO MODEL — 12mo characterization (1 contract/sleeve, 1pt friction)\n")
    print(f"sleeves: {[s[0] for s in SLEEVES]}\n")

    def line(label, trades):
        st, days = block(trades)
        if st.n == 0:
            print(f"  {label:30} n=0"); return
        pnls = sorted((t['pnl'] for t in trades), reverse=True)
        conc = sum(pnls[:3]) / st.total_pts * 100 if st.total_pts > 0 else float('nan')
        print(f"  {label:30} n={st.n:4d} win%={st.win_pct:5.1f} total={st.total_pts:+8.1f}pt "
              f"PF={st.pf:5.2f} maxDD={st.max_dd:7.1f}pt(${st.max_dd*2:.0f}) sharpe={st.sharpe_daily:5.2f} "
              f"days={days} top3={conc:.0f}%")

    for slice_name, lo, hi in [("FULL 12mo", None, None),
                               ("BLIND earliest-6mo", None, BLIND_SPLIT),
                               ("RECENT 6mo", BLIND_SPLIT, None)]:
        sl = slice_by_entry(allt, lo, hi)
        print(f"[{slice_name}] AGGREGATE")
        line("  portfolio (all sleeves)", sl)
        for name, _, _ in SLEEVES:
            line(name, [t for t in sl if t["sleeve"] == name])
        print()

    print(f"max concurrent open positions (full): {max_concurrency(allt)}  "
          f"(risk manager max_contracts=3 would clamp beyond this)")
    # per-sleeve daily-PnL diversification (overlap of active days)
    from collections import defaultdict
    daysets = {name: {t['entry_ts'].date() for t in per[name]} for name, _, _ in SLEEVES}
    print("active trading days per sleeve:", {k: len(v) for k, v in daysets.items()})


# ---------- forward paper-logging (post-window, idempotent, NO orders) ----------
def _existing_keys():
    keys = set()
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            for ln in f:
                if ln.strip():
                    r = json.loads(ln); keys.add((r["sleeve"], r["entry_ts"]))
    return keys


def report_forward():
    allt, _ = run_all_sleeves()
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    latest = max(bars(tf)[-1].ts.date() for _, tf, _ in SLEEVES)   # last available bar
    fwd = [t for t in allt if t["entry_ts"].date() > WINDOW_END]
    if not fwd:
        print(f"no forward data yet — latest bar ~{latest} <= window end {WINDOW_END}. "
              f"Add post-{WINDOW_END} bars to src/data/ (resample 1m -> 2m/5m/15m).")
        if os.path.exists(LOG_PATH):
            rows = [json.loads(l) for l in open(LOG_PATH) if l.strip()]
            print(f"current portfolio paper tally: n={len(rows)}")
        return
    existing = _existing_keys()
    new = [t for t in fwd if (t["sleeve"], t["entry_ts"].isoformat()) not in existing]
    with open(LOG_PATH, "a") as f:
        for t in sorted(new, key=lambda x: x["exit_ts"]):
            f.write(json.dumps({"sleeve": t["sleeve"], "entry_ts": t["entry_ts"].isoformat(),
                                "exit_ts": t["exit_ts"].isoformat(), "pnl_pts": round(t["pnl"], 2)}) + "\n")
    rows = [json.loads(l) for l in open(LOG_PATH) if l.strip()]
    pnls = [r["pnl_pts"] for r in rows]
    w = [p for p in pnls if p > 0]; l = [p for p in pnls if p <= 0]
    pf = sum(w) / abs(sum(l)) if l and sum(l) != 0 else float("inf")
    cum = peak = mdd = 0.0
    for p in pnls:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    tal = {"n": len(rows), "win_pct": round(100*len(w)/len(rows), 1) if rows else 0,
           "total_pts": round(sum(pnls), 1), "pf": round(pf, 2) if pf != float("inf") else None,
           "max_dd_pts": round(mdd, 1), "max_dd_usd": round(mdd*2, 0)}
    json.dump(tal, open(TALLY_PATH, "w"), indent=2)
    print(f"logged {len(new)} new forward trade(s). PORTFOLIO PAPER TALLY: {tal}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Aggregate portfolio paper model")
    ap.add_argument("--forward", action="store_true", help="paper-log post-window trades")
    a = ap.parse_args()
    report_forward() if a.forward else report_backtest()
