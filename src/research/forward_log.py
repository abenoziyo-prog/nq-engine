"""Forward-logging harness for LVL_IMB_LONDON_5M — its 2nd out-of-sample window.

This is a PAPER record only. It loads the VERIFIED engine (src/engine/lvl_imb.py)
with its EXACT frozen config (the one that produced the blind-slice PF 2.16 / n=69)
and runs it forward over any 5m bars dated AFTER the 12-month backtest window
(2026-06-14). For every would-be signal it logs the zone, intended stop, intended
target (+1R), and the mark-to-close outcome to logs/forward_london.jsonl, then
reports a running forward tally to compare against the blind-slice PF 2.16.

Constitution: research only. NEVER places an order. Logs every result win or lose.
NEVER tunes the frozen config. Idempotent — re-running the same day does not
double-log (de-dup by entry timestamp).

Engine warm-up: the engine is fed the FULL available history in order so its
ATR(14)/EMA(200)/zone state is correct at the forward boundary; only trades whose
ENTRY is after the backtest window are logged/counted as forward.

Run:  python -m src.research.forward_log [--since YYYY-MM-DD]
"""
from __future__ import annotations
import os, sys, csv, json, glob, argparse
from datetime import datetime, date, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from src.engine.lvl_imb import LvlImbEngine, LvlImbConfig, Signal
from src.data.model import Session

# ---- frozen, verified config (DO NOT CHANGE — this is the blind PF 2.16 engine) ----
FROZEN_CFG = LvlImbConfig(formation_session=Session.LONDON)   # all defaults = verified config
FRICTION = 1.0
WINDOW_END = date(2026, 6, 14)            # last date of the verified 12mo backtest
DATA_DIR = os.path.join(_REPO, "src", "data")
BASE_5M = os.path.join(DATA_DIR, "MNQ_5m_12mo_databento.csv")   # verified continuation source
LOG_PATH = os.path.join(_REPO, "logs", "forward_london.jsonl")
TALLY_PATH = os.path.join(_REPO, "logs", "forward_london_tally.json")
BLIND_PF = 2.16                           # reference: blind earliest-6mo PF


def _load_csv(path):
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            ts = datetime.fromisoformat(r["ts_utc"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append((ts, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    return out


def load_forward_5m():
    """Verified databento 5m series + any appended forward files (MNQ_5m_forward*.csv).
    Merged by timestamp (dedup), chronological. Same-source continuation only — the
    TradingView aggregated_clean file is deliberately NOT mixed in."""
    sources = ([BASE_5M] if os.path.exists(BASE_5M) else []) + \
              sorted(glob.glob(os.path.join(DATA_DIR, "MNQ_5m_forward*.csv")))
    merged = {}
    for p in sources:
        for row in _load_csv(p):
            merged[row[0]] = row
    return [merged[k] for k in sorted(merged)], sources


def run_engine(bars):
    """Drive the frozen engine bar-by-bar; return (closed_trades, open_trade_or_None)."""
    eng = LvlImbEngine(FROZEN_CFG)
    trades, cur = [], None
    for ts, o, h, l, c in bars:
        eng.feed_ts(ts)
        dec = eng.on_bar(o, h, l, c)
        if dec is None:
            continue
        if str(dec["signal"]).endswith("ENTER_LONG"):
            entry, stop, risk = dec["price"], eng.stop, eng.risk
            height = risk / 1.25                       # entry=mid, stop=low-0.75h => risk=1.25h
            cur = {"entry_ts": ts, "entry": round(entry, 2), "stop": round(stop, 2),
                   "risk_pts": round(risk, 2), "target_1R": round(entry + risk, 2),
                   "zone_low": round(entry - height / 2, 2), "zone_high": round(entry + height / 2, 2)}
        elif str(dec["signal"]).endswith("EXIT_LONG") and cur is not None:
            exit_px = dec["price"]
            trades.append({**cur, "exit_ts": ts, "exit": round(exit_px, 2),
                           "pnl_pts": round(exit_px - cur["entry"] - FRICTION, 2), "status": "CLOSED"})
            cur = None
    open_trade = None
    if eng.in_pos and cur is not None and bars:
        last_close = bars[-1][4]
        open_trade = {**cur, "exit_ts": None, "exit": round(last_close, 2),
                      "pnl_pts": round(last_close - cur["entry"] - FRICTION, 2), "status": "OPEN_MTM"}
    return trades, open_trade


def _existing_entry_keys():
    keys = set()
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    keys.add(json.loads(line)["entry_ts"])
    return keys


def _read_logged_pnls():
    rows = []
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    rows.sort(key=lambda r: r["entry_ts"])
    return rows


def tally(rows):
    pnls = [r["pnl_pts"] for r in rows]
    n = len(pnls)
    if n == 0:
        return {"n": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")
    cum = peak = mdd = 0.0
    for p in pnls:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    days = len({r["entry_ts"][:10] for r in rows})
    return {"n": n, "eff_days": days, "win_pct": round(100 * len(wins) / n, 1),
            "total_pts": round(sum(pnls), 1), "pf": (round(pf, 2) if pf != float("inf") else None),
            "max_dd_pts": round(mdd, 1)}


def main():
    ap = argparse.ArgumentParser(description="LVL_IMB_LONDON_5M forward paper-log (2nd OOS window)")
    ap.add_argument("--since", default=None, help="only log entries on/after this YYYY-MM-DD (default: day after backtest window)")
    args = ap.parse_args()
    since = datetime.fromisoformat(args.since).date() if args.since else None

    bars, sources = load_forward_5m()
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    print(f"sources: {[os.path.basename(p) for p in sources]}")
    if not bars:
        print("no forward data yet (no 5m bars found in src/data/).")
        return
    latest = bars[-1][0].date()
    forward_present = [b for b in bars if b[0].date() > WINDOW_END]
    if not forward_present:
        print(f"no forward data yet — latest bar {latest} <= backtest window end {WINDOW_END}. "
              f"Drop post-{WINDOW_END} 5m databento bars into src/data/ (MNQ_5m_forward*.csv or append to the 12mo file).")
        t = tally(_read_logged_pnls())
        print(f"current forward tally: {t}")
        return

    closed, open_trade = run_engine(bars)
    # forward = entry strictly after the backtest window (and >= --since if given)
    def is_fwd(r):
        d = datetime.fromisoformat(r["entry_ts"]).date() if isinstance(r["entry_ts"], str) else r["entry_ts"].date()
        return d > WINDOW_END and (since is None or d >= since)
    for r in closed:                       # normalize ts -> iso for logging/compare
        r["entry_ts"] = r["entry_ts"].isoformat(); r["exit_ts"] = r["exit_ts"].isoformat()
    fwd_closed = [r for r in closed if is_fwd(r)]

    existing = _existing_entry_keys()
    new = [r for r in fwd_closed if r["entry_ts"] not in existing]
    with open(LOG_PATH, "a") as f:
        for r in new:
            f.write(json.dumps(r) + "\n")
    print(f"forward window: {len([b for b in forward_present])} bars after {WINDOW_END} (latest {latest})")
    print(f"logged {len(new)} new forward trade(s); {len(fwd_closed)} forward closed total in log scope")

    rows = _read_logged_pnls()
    t = tally(rows)
    with open(TALLY_PATH, "w") as f:
        json.dump(t, f, indent=2)
    print(f"\n=== RUNNING FORWARD TALLY (LVL_IMB_LONDON_5M, paper) ===")
    print(f"  {t}")
    if t.get("n"):
        pf = t["pf"]
        print(f"  vs blind-slice PF {BLIND_PF}: forward PF {pf} "
              f"({'tracking/above' if pf and pf >= 1.0 else 'below 1.0'})")
    if open_trade is not None and open_trade["entry_ts"].date() > WINDOW_END \
            and (since is None or open_trade["entry_ts"].date() >= since):
        ot = dict(open_trade); ot["entry_ts"] = ot["entry_ts"].isoformat()
        print(f"  OPEN position (mark-to-close, unrealized, NOT in realized tally): {ot}")


if __name__ == "__main__":
    main()
