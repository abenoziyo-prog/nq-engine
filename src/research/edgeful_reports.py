"""Edgeful-style probability reports, reproduced on our own NQ data (zero API needed).

Two layers per the project ethos (probability != expectancy):
  LAYER A — the STAT: reproduce Edgeful's probability reports (matching their field
            definitions, captured from the live API for the 3 plan-accessible reports)
            on our 12mo databento data, split full / blind-earliest-6mo / recent so
            regime stability is visible (Edgeful shows one number; we show the split).
  LAYER B — the BACKTEST: turn a report into entry/stop/exit and measure PF + drift
            (demonstrated on gap-fill). A 70% fill rate is NOT an edge until R:R +
            friction are accounted for.

Sessions: RTH cash (09:30-16:00 ET). "Day" OHLC = RTH open/high/low/close. Gap =
today's RTH open - yesterday's RTH close. Green = close >= open.
"""
from __future__ import annotations
import os, sys
from collections import defaultdict
from datetime import date, time
from zoneinfo import ZoneInfo

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from src.backtest.drift_control import load_bars, run_drift, DriftConfig
from src.backtest.harness import _stats
from src.data.model import Session

ET = ZoneInfo("America/New_York")
RTH_START, RTH_END = time(9, 30), time(16, 0)
BLIND_SPLIT = date(2025, 12, 15)
DATA_1M = "src/data/MNQ_1m_12mo_databento.csv"


def load_rth_days(path=DATA_1M):
    """Build per-ET-date RTH day records with intraday path + prior-day levels."""
    bars = load_bars(path)
    byday = defaultdict(list)
    for b in bars:
        et = b.ts.astimezone(ET)
        if RTH_START <= et.time() < RTH_END:
            byday[et.date()].append((et, b.open, b.high, b.low, b.close))
    days = []
    prev = None
    for d in sorted(byday):
        rows = byday[d]
        o = rows[0][1]; h = max(r[2] for r in rows); l = min(r[3] for r in rows); c = rows[-1][4]
        rec = {"date": d, "weekday": d.weekday(), "open": o, "high": h, "low": l, "close": c,
               "intraday": rows}
        if prev:
            rec["prev_high"], rec["prev_low"], rec["prev_close"] = prev["high"], prev["low"], prev["close"]
        days.append(rec); prev = rec
    return [r for r in days if "prev_close" in r]   # drop first day (no prior)


def _slice(days, lo=None, hi=None):
    return [d for d in days if (lo is None or d["date"] > lo) and (hi is None or d["date"] <= hi)]


def pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


# ---------------- LAYER A : reports ----------------
def report_previous_days_range(days):
    hi_brk = [d for d in days if d["high"] > d["prev_high"]]
    lo_brk = [d for d in days if d["low"] < d["prev_low"]]
    green = lambda xs: sum(1 for d in xs if d["close"] >= d["open"])
    n = len(days)
    return {"n": n,
            "prevDayHigh_broken": (len(hi_brk), pct(len(hi_brk), n)),
            "highBroken_green": pct(green(hi_brk), len(hi_brk)), "highBroken_red": pct(len(hi_brk) - green(hi_brk), len(hi_brk)),
            "prevDayLow_broken": (len(lo_brk), pct(len(lo_brk), n)),
            "lowBroken_green": pct(green(lo_brk), len(lo_brk)), "lowBroken_red": pct(len(lo_brk) - green(lo_brk), len(lo_brk))}


def report_opening_stats(days):
    n = len(days)
    above = sum(1 for d in days if d["open"] > d["prev_high"])
    below = sum(1 for d in days if d["open"] < d["prev_low"])
    inside = n - above - below
    return {"totalDays": n, "abovePrevHigh": (above, pct(above, n)),
            "betweenHighLow": (inside, pct(inside, n)), "belowPrevLow": (below, pct(below, n))}


def report_green_red_by_weekday(days):
    wd = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
    out = {}
    for k, name in wd.items():
        xs = [d for d in days if d["weekday"] == k]
        g = sum(1 for d in xs if d["close"] >= d["open"])
        out[name] = {"green": g, "red": len(xs) - g, "green_pct": pct(g, len(xs))}
    return out


def report_gap_fill(days):
    gaps = [d for d in days if d["open"] != d["prev_close"]]
    def filled(d):
        return (d["low"] <= d["prev_close"]) if d["open"] > d["prev_close"] else (d["high"] >= d["prev_close"])
    f = sum(1 for d in gaps if filled(d))
    ups = [d for d in gaps if d["open"] > d["prev_close"]]; dns = [d for d in gaps if d["open"] < d["prev_close"]]
    # by size bucket (gap as % of prev_close)
    buckets = [(0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 99)]
    bk = {}
    for lo, hi in buckets:
        xs = [d for d in gaps if lo <= abs(d["open"] - d["prev_close"]) / d["prev_close"] * 100 < hi]
        bk[f"{lo}-{hi}%"] = (len(xs), pct(sum(1 for d in xs if filled(d)), len(xs)))
    return {"n_gaps": len(gaps), "fill_pct": pct(f, len(gaps)),
            "up_fill_pct": pct(sum(1 for d in ups if filled(d)), len(ups)),
            "down_fill_pct": pct(sum(1 for d in dns if filled(d)), len(dns)),
            "fill_by_size": bk}


def report_orb(days, or_min=15):
    n = up = dn = up_cont = 0
    cutoff = time(9, 30 + or_min)
    for d in days:
        orb = [r for r in d["intraday"] if r[0].time() < cutoff]
        rest = [r for r in d["intraday"] if r[0].time() >= cutoff]
        if not orb or not rest:
            continue
        n += 1
        orh = max(r[2] for r in orb); orl = min(r[3] for r in orb)
        broke_up = max(r[2] for r in rest) > orh
        broke_dn = min(r[3] for r in rest) < orl
        up += broke_up; dn += broke_dn
        if broke_up and d["close"] >= orh:
            up_cont += 1
    return {"n": n, "broke_OR_high_pct": pct(up, n), "broke_OR_low_pct": pct(dn, n),
            "upbreak_closed_above_pct": pct(up_cont, up)}


# ---------------- LAYER B : gap-fill fade backtest ----------------
def backtest_gap_fill_fade(days, friction=1.0, rr=1.0, min_gap_pts=2.0):
    """Fade the gap toward prior close. target=prev_close (reward=gap), stop=rr*gap the
    other side. Intraday path decides fill-vs-stop (stop-first on same-bar tie = conservative)."""
    trades = []
    for d in days:
        gap = d["open"] - d["prev_close"]
        if abs(gap) < min_gap_pts:
            continue
        entry = d["open"]; target = d["prev_close"]
        if gap > 0:   # gap up -> short, stop above
            stop = entry + rr * abs(gap); long = False
        else:         # gap down -> long, stop below
            stop = entry - rr * abs(gap); long = True
        pnl = None
        for _, o, h, l, c in d["intraday"]:
            if long:
                if l <= stop: pnl = -(entry - stop) - friction; break
                if h >= target: pnl = (target - entry) - friction; break
            else:
                if h >= stop: pnl = -(stop - entry) - friction; break
                if l <= target: pnl = (entry - target) - friction; break
        if pnl is None:   # neither hit -> exit at close
            pnl = ((d["close"] - entry) if long else (entry - d["close"])) - friction
        from datetime import datetime
        trades.append({"pnl": pnl, "pnl_pts": pnl, "qty": 1,
                       "entry_ts": datetime.combine(d["date"], RTH_START, tzinfo=ET),
                       "exit_ts": datetime.combine(d["date"], RTH_END, tzinfo=ET)})
    return trades


def _bt_line(label, trades):
    st = _stats(trades)
    if not st.n:
        print(f"  {label:28} n=0"); return
    print(f"  {label:28} n={st.n:3d} win%={st.win_pct:5.1f} total={st.total_pts:+8.1f}pt "
          f"PF={st.pf:5.2f} maxDD={st.max_dd:7.1f}pt(${st.max_dd*2:.0f})")


def main():
    days = load_rth_days()
    print(f"RTH days: {len(days)}  {days[0]['date']}..{days[-1]['date']}\n")
    slices = [("FULL", None, None), ("BLIND earliest-6mo", None, BLIND_SPLIT), ("RECENT 6mo", BLIND_SPLIT, None)]

    for name, lo, hi in slices:
        ds = _slice(days, lo, hi)
        print(f"================ {name}  (n_days={len(ds)}) ================")
        print(" prev-day-range:", report_previous_days_range(ds))
        print(" opening-stats :", report_opening_stats(ds))
        print(" gap-fill      :", {k: report_gap_fill(ds)[k] for k in ("n_gaps", "fill_pct", "up_fill_pct", "down_fill_pct")})
        print(" gap-fill/size :", report_gap_fill(ds)["fill_by_size"])
        print(" ORB(15m)      :", report_orb(ds))
        if name == "FULL":
            print(" green/red wkdy:", report_green_red_by_weekday(ds))
        print()

    print("================ LAYER B: gap-fill FADE backtest (probability != expectancy) ================")
    for name, lo, hi in slices:
        _bt_line(name, backtest_gap_fill_fade(_slice(days, lo, hi)))
    bars = load_bars(DATA_1M)
    dr = run_drift(bars, DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=30, n_entries=200, seed=12345))
    print(f"  drift control (random NY_AM long): PF={dr.stats.pf:.2f}")


if __name__ == "__main__":
    main()
