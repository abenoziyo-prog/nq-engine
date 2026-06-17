"""Edgeful-style reports, reproduced LOCALLY on our own NQ data — fully configurable
so you can test variations. No API/key needed: every report is a deterministic
function over session-grouped OHLC from our databento bars.

Two layers (probability != expectancy):
  LAYER A — the STAT (prev-day range, opening stats, gap fill by size, ORB, weekday).
  LAYER B — the BACKTEST (turn a report into entry/stop/exit; measure PF + drift).

VARYING THINGS (the point of this module): everything lives in ReportConfig —
session window, instrument/timeframe (any CSV in our schema), date range, gap-size
buckets, ORB window, and the fade backtest knobs (which gap sizes/directions to
trade, R:R, friction). `sweep` runs a grid and shows, per variation, the stat AND
the backtest PF on FULL / BLIND-earliest-6mo / RECENT slices + the drift control —
so a sweep can't silently turn into curve-fitting (you see the blind number and the
benchmark for every cell).

Run:
  python -m src.research.edgeful_reports report          # all reports, 3 slices
  python -m src.research.edgeful_reports sweep            # vary the gap-fade backtest
  ... --data src/data/MNQ_5m_12mo_databento.csv --sess 09:30-16:00
"""
from __future__ import annotations
import os, sys, argparse
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, time, datetime
from zoneinfo import ZoneInfo

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from src.backtest.drift_control import load_bars, run_drift, DriftConfig
from src.backtest.harness import _stats
from src.data.model import Session

ET = ZoneInfo("America/New_York")
DATA_1M = "src/data/MNQ_1m_12mo_databento.csv"
# Edgeful's exact gap-fill-by-size buckets (gap % of prior close); labels match their UI
EDGEFUL_BUCKETS = [(0, 0.2, "0-0.19%"), (0.2, 0.4, "0.2-0.39%"), (0.4, 0.7, "0.4-0.69%"),
                   (0.7, 1.0, "0.7-0.99%"), (1.0, 1.5, "1.0-1.49%"), (1.5, 1e9, ">=1.5%")]


@dataclass
class ReportConfig:
    data: str = DATA_1M
    sess_start: tuple = (9, 30)            # ET session open (vary to test custom sessions)
    sess_end: tuple = (16, 0)              # ET session close
    blind_split: date = date(2025, 12, 15)
    buckets: list = field(default_factory=lambda: list(EDGEFUL_BUCKETS))
    or_min: int = 15
    # --- gap-fade backtest knobs (the variations) ---
    fade_min_gap_pct: float = 0.0          # only fade gaps with |gap%| in [min, max)
    fade_max_gap_pct: float = 1e9
    fade_dirs: tuple = ("up", "down")      # which gap directions to fade
    fade_rr: float = 1.0                   # stop = rr * gap distance
    friction: float = 1.0


def load_days(cfg: ReportConfig):
    s, e = time(*cfg.sess_start), time(*cfg.sess_end)
    byday = defaultdict(list)
    for b in load_bars(cfg.data):
        et = b.ts.astimezone(ET)
        if s <= et.time() < e:
            byday[et.date()].append((et, b.open, b.high, b.low, b.close))
    days, prev = [], None
    for d in sorted(byday):
        r = byday[d]
        rec = {"date": d, "weekday": d.weekday(), "open": r[0][1], "high": max(x[2] for x in r),
               "low": min(x[3] for x in r), "close": r[-1][4], "intraday": r}
        if prev:
            rec["prev_high"], rec["prev_low"], rec["prev_close"] = prev["high"], prev["low"], prev["close"]
        days.append(rec); prev = rec
    return [r for r in days if "prev_close" in r]


def _slice(days, lo=None, hi=None):
    return [d for d in days if (lo is None or d["date"] > lo) and (hi is None or d["date"] <= hi)]


def pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


# ---------------- LAYER A ----------------
def report_previous_days_range(days):
    hi = [d for d in days if d["high"] > d["prev_high"]]; lo = [d for d in days if d["low"] < d["prev_low"]]
    g = lambda xs: sum(1 for d in xs if d["close"] >= d["open"])
    n = len(days)
    return {"n": n, "PDH_broken": (len(hi), pct(len(hi), n)), "PDH_green%": pct(g(hi), len(hi)),
            "PDL_broken": (len(lo), pct(len(lo), n)), "PDL_red%": pct(len(lo) - g(lo), len(lo))}


def report_opening_stats(days):
    n = len(days); a = sum(1 for d in days if d["open"] > d["prev_high"]); b = sum(1 for d in days if d["open"] < d["prev_low"])
    return {"totalDays": n, "abovePDH": (a, pct(a, n)), "inside": (n - a - b, pct(n - a - b, n)), "belowPDL": (b, pct(b, n))}


def report_green_red_by_weekday(days):
    wd = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}; out = {}
    for k, nm in wd.items():
        xs = [d for d in days if d["weekday"] == k]; gr = sum(1 for d in xs if d["close"] >= d["open"])
        out[nm] = {"green": gr, "red": len(xs) - gr, "green%": pct(gr, len(xs))}
    return out


def _filled(d):
    return (d["low"] <= d["prev_close"]) if d["open"] > d["prev_close"] else (d["high"] >= d["prev_close"])


def report_gap_fill(days):
    gaps = [d for d in days if d["open"] != d["prev_close"]]
    up = [d for d in gaps if d["open"] > d["prev_close"]]; dn = [d for d in gaps if d["open"] < d["prev_close"]]
    return {"n_gaps": len(gaps), "fill%": pct(sum(1 for d in gaps if _filled(d)), len(gaps)),
            "up_fill%": pct(sum(1 for d in up if _filled(d)), len(up)),
            "down_fill%": pct(sum(1 for d in dn if _filled(d)), len(dn))}


def report_gap_fill_by_size(days, buckets=EDGEFUL_BUCKETS):
    gp = lambda d: abs(d["open"] - d["prev_close"]) / d["prev_close"] * 100
    out = {}
    for lo, hi, label in buckets:
        u = [d for d in days if d["open"] > d["prev_close"] and lo <= gp(d) < hi]
        v = [d for d in days if d["open"] < d["prev_close"] and lo <= gp(d) < hi]
        out[label] = {"up": (len(u), pct(sum(1 for d in u if _filled(d)), len(u))),
                      "down": (len(v), pct(sum(1 for d in v if _filled(d)), len(v)))}
    return out


def report_orb(days, or_min=15):
    n = up = dn = cont = 0; cutoff = time(9, 30 + or_min)
    for d in days:
        orb = [r for r in d["intraday"] if r[0].time() < cutoff]; rest = [r for r in d["intraday"] if r[0].time() >= cutoff]
        if not orb or not rest:
            continue
        n += 1; orh = max(r[2] for r in orb); orl = min(r[3] for r in orb)
        bu = max(r[2] for r in rest) > orh; up += bu; dn += min(r[3] for r in rest) < orl
        if bu and d["close"] >= orh:
            cont += 1
    return {"n": n, "broke_OR_high%": pct(up, n), "broke_OR_low%": pct(dn, n), "upbreak_closed_above%": pct(cont, up)}


# ---------------- LAYER B : configurable gap-fade backtest ----------------
def backtest_gap_fade(days, cfg: ReportConfig):
    trades = []
    for d in days:
        gap = d["open"] - d["prev_close"]
        gpct = abs(gap) / d["prev_close"] * 100
        if not (cfg.fade_min_gap_pct <= gpct < cfg.fade_max_gap_pct):
            continue
        direction = "up" if gap > 0 else "down"
        if direction not in cfg.fade_dirs or gap == 0:
            continue
        entry, target = d["open"], d["prev_close"]
        long = gap < 0
        stop = entry - cfg.fade_rr * abs(gap) if long else entry + cfg.fade_rr * abs(gap)
        pnl = None
        for _, o, h, l, c in d["intraday"]:
            if long:
                if l <= stop: pnl = -(entry - stop) - cfg.friction; break
                if h >= target: pnl = (target - entry) - cfg.friction; break
            else:
                if h >= stop: pnl = -(stop - entry) - cfg.friction; break
                if l <= target: pnl = (entry - target) - cfg.friction; break
        if pnl is None:
            pnl = ((d["close"] - entry) if long else (entry - d["close"])) - cfg.friction
        trades.append({"pnl": pnl, "pnl_pts": pnl, "qty": 1,
                       "entry_ts": datetime.combine(d["date"], time(*cfg.sess_start), tzinfo=ET),
                       "exit_ts": datetime.combine(d["date"], time(*cfg.sess_end), tzinfo=ET)})
    return trades


def _block(trades):
    s = _stats(trades)
    return s if s.n else None


def cmd_report(cfg):
    days = load_days(cfg)
    print(f"session {cfg.sess_start}->{cfg.sess_end} | {cfg.data}\nRTH days: {len(days)}  {days[0]['date']}..{days[-1]['date']}\n")
    for name, lo, hi in [("FULL", None, None), ("BLIND-6mo", None, cfg.blind_split), ("RECENT-6mo", cfg.blind_split, None)]:
        ds = _slice(days, lo, hi)
        print(f"==== {name} (n={len(ds)}) ====")
        print(" prev-day-range:", report_previous_days_range(ds))
        print(" opening-stats :", report_opening_stats(ds))
        print(" gap-fill      :", report_gap_fill(ds))
        for b, v in report_gap_fill_by_size(ds, cfg.buckets).items():
            print(f"   {b:10} up={v['up']} down={v['down']}")
        print(" ORB           :", report_orb(ds, cfg.or_min))
        if name == "FULL":
            print(" green/red wkdy:", report_green_red_by_weekday(ds))
        print()


def cmd_sweep(cfg):
    """Vary the gap-fade backtest and show robustness (full/blind/recent PF) + drift."""
    days = load_days(cfg)
    grid = []
    for mx in (0.4, 0.7, 1.0, 1e9):
        for dirs in (("up", "down"), ("up",), ("down",)):
            grid.append((cfg.fade_min_gap_pct, mx, dirs, cfg.fade_rr))
    print(f"GAP-FADE SWEEP | session {cfg.sess_start}->{cfg.sess_end} | rr={cfg.fade_rr} friction={cfg.friction}")
    print(f"{'gap%range':12}{'dirs':10}{'n':>5}{'PF_full':>9}{'PF_blind':>9}{'PF_recent':>10}{'DD$_full':>10}")
    full = _slice(days, None, None); bl = _slice(days, None, cfg.blind_split); rc = _slice(days, cfg.blind_split, None)
    for lo, hi, dirs, rr in grid:
        c = replace(cfg, fade_min_gap_pct=lo, fade_max_gap_pct=hi, fade_dirs=dirs, fade_rr=rr)
        sf = _block(backtest_gap_fade(full, c)); sb = _block(backtest_gap_fade(bl, c)); sr = _block(backtest_gap_fade(rc, c))
        rng = f"{lo}-{'inf' if hi > 100 else hi}%"
        pf = lambda s: f"{s.pf:.2f}" if s else "—"
        n = sf.n if sf else 0; dd = f"{sf.max_dd*2:.0f}" if sf else "—"
        print(f"{rng:12}{'+'.join(dirs):10}{n:>5}{pf(sf):>9}{pf(sb):>9}{pf(sr):>10}{dd:>10}")
    dr = run_drift(load_bars(cfg.data), DriftConfig(session=Session.NY_AM, direction="long", horizon_bars=30, n_entries=200, seed=12345))
    print(f"\ndrift control (random NY_AM long): PF={dr.stats.pf:.2f}  (a fade must clear this AND PF>1.5 on BLIND, with DD that fits $2K)")


def _parse_sess(s):
    a, b = s.split("-"); h1, m1 = a.split(":"); h2, m2 = b.split(":")
    return (int(h1), int(m1)), (int(h2), int(m2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Edgeful-style reports, local + configurable")
    ap.add_argument("cmd", nargs="?", default="report", choices=["report", "sweep"])
    ap.add_argument("--data", default=DATA_1M)
    ap.add_argument("--sess", default="09:30-16:00", help="ET session window HH:MM-HH:MM")
    ap.add_argument("--rr", type=float, default=1.0)
    a = ap.parse_args()
    ss, se = _parse_sess(a.sess)
    cfg = ReportConfig(data=a.data, sess_start=ss, sess_end=se, fade_rr=a.rr)
    (cmd_sweep if a.cmd == "sweep" else cmd_report)(cfg)
