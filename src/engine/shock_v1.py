"""SHOCK_v1 engine — docs/SHOCK_ENGINE_SPEC.md, productionized.

Detection lives in src/detector/shock.py (a-priori params, tested). This module
adds the trade layer the spec requires: direction-split UP/DOWN, the entry-scheme
bake-off (E1 immediate / E2 pullback / E3 extreme-break / E4 hybrid), impulse-scaled
stops, and trail/duration/scratch exits (sec 4-6).

HARNESS NOTE: src/backtest/harness.py streams (ts,o,h,l,c) only — it carries no
volume and is long-only single-position. SHOCK's trigger needs volume and its DOWN
setup is short, and the bake-off runs four schemes per event in parallel. None of
that fits the OHLC-only harness, so this engine is driven by its own event-driven
loop over Bar objects (which carry volume). The engine logic is identical to what a
live feed would drive; the harness is used only for the mandatory drift control.

Baselines are causal/a-priori. No parameter is fit to outcomes.
"""
from __future__ import annotations
import math
import statistics
from collections import deque, defaultdict
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from src.data.model import Bar, Session, ContextSnapshot, LevelState, tag_session
from src.detector.shock import ShockDetector, ShockParams

ET = ZoneInfo("America/New_York")
TICK = 0.25
FRICTION = 1.0


def compute_baselines(bars: list[Bar]):
    """Return (vol_baseline_fn, sigma_floor), both causal/a-priori.

    vol_baseline_fn(ts): trailing ~20-day median of the 180s (3-bar) window volume
    at the same ET minute-of-day (prior days only). sigma_floor: 0.25 x full-sample
    median |1m log return| (quiet-tape guard)."""
    n = len(bars)
    wvol = [0] * n
    for i in range(n):
        wvol[i] = bars[i].volume + (bars[i - 1].volume if i >= 1 else 0) + (bars[i - 2].volume if i >= 2 else 0)
    tod_hist = defaultdict(lambda: deque(maxlen=20))
    last_date = {}
    baseline_by_ts = {}
    for i in range(n):
        et = bars[i].ts.astimezone(ET)
        key = et.hour * 60 + et.minute
        dq = tod_hist[key]
        baseline_by_ts[bars[i].ts] = statistics.median(dq) if dq else float("inf")
        d = et.date()
        if last_date.get(key) != d:
            dq.append(wvol[i]); last_date[key] = d
    rets = [abs(math.log(bars[i].close / bars[i - 1].close))
            for i in range(1, n) if bars[i - 1].close > 0]
    sigma_floor = 0.25 * statistics.median(rets)
    return (lambda ts: baseline_by_ts.get(ts, float("inf"))), sigma_floor


def _ctx(b: Bar) -> ContextSnapshot:
    return ContextSnapshot(ts=b.ts, session=tag_session(b.ts),
                           mins_to_session_boundary=0.0, in_moc_window=False, levels=LevelState())


def detect(bars: list[Bar], params: ShockParams, baselines=None) -> list[dict]:
    """Run the detector over bars; return event dicts (a-priori; counted before outcomes)."""
    if baselines is None:
        baselines = compute_baselines(bars)
    vol_fn, sig_floor = baselines
    det = ShockDetector(params, vol_fn, sig_floor)
    out = []
    for b in bars:
        ev = det.on_bar(b, _ctx(b))
        if ev is not None:
            out.append({"i": None, "ts": ev.ts_trigger, "dir": ev.direction,
                        "open": ev.impulse_open, "extreme": ev.impulse_extreme,
                        "range": ev.impulse_range_pts, "session": ev.session,
                        "sigma": ev.shock_sigma})
    return out


# ---- entry schemes (return (entry_index, entry_price) or None) --------------
def _entry_E1(bars, it, d, op, ext, rng):
    return (it + 1, bars[it + 1].open) if it + 1 < len(bars) else None


def _entry_E2(bars, it, d, op, ext, rng):
    fill = ext - d * 0.30 * rng                      # 30% retrace of the impulse leg
    for j in range(it + 1, min(it + 16, len(bars))):  # within 15 min
        b = bars[j]
        if d == 1:
            if b.high > ext: return None             # extreme broken first
            if b.low <= fill: return (j, fill)
        else:
            if b.low < ext: return None
            if b.high >= fill: return (j, fill)
    return None


def _entry_E3(bars, it, d, op, ext, rng):
    trig = ext + d * 2 * TICK                          # 2 ticks beyond extreme
    for j in range(it + 3, min(it + 3 + 20, len(bars))):  # armed after 3m, valid 20m
        b = bars[j]
        if d == 1 and b.high >= trig: return (j, trig)
        if d == -1 and b.low <= trig: return (j, trig)
    return None


SCHEMES = {"E1": _entry_E1, "E2": _entry_E2, "E3": _entry_E3}


def manage(bars, entry_i, entry_px, d, imp_open, imp_extreme, imp_range, max_hold_min=None):
    """Impulse-scaled stop + swing trail + session time-guard + 60-min scratch (sec 5-6).
    Returns pnl in points net of friction. pnl = d*(exit-entry) - FRICTION."""
    n = len(bars)
    retrace50 = imp_extreme - d * 0.5 * imp_range
    init_stop = (max(entry_px - 0.45 * imp_range, retrace50) if d == 1
                 else min(entry_px + 0.45 * imp_range, retrace50))
    trail = init_stop
    entry_ts = bars[entry_i].ts
    et = entry_ts.astimezone(ET)
    guard_date = et.date() if et.hour < 17 else (et + timedelta(days=1)).date()
    guard = datetime.combine(guard_date, dtime(17, 0), tzinfo=ET).astimezone(bars[0].ts.tzinfo)
    reached_1R = False
    lows, highs = deque(maxlen=15), deque(maxlen=15)
    j = entry_i + 1
    while j < n:
        b = bars[j]
        if d == 1:
            if lows: trail = max(trail, min(lows))
            if b.low <= trail: return d * (trail - entry_px) - FRICTION
            if b.high >= entry_px + imp_range: reached_1R = True
        else:
            if highs: trail = min(trail, max(highs))
            if b.high >= trail: return d * (trail - entry_px) - FRICTION
            if b.low <= entry_px - imp_range: reached_1R = True
        lows.append(b.low); highs.append(b.high)
        if b.ts >= guard:
            return d * (b.close - entry_px) - FRICTION
        if (b.ts - entry_ts) >= timedelta(minutes=60) and not reached_1R:
            return d * (b.close - entry_px) - FRICTION
        j += 1
    return d * (bars[-1].close - entry_px) - FRICTION


def run_bakeoff(bars: list[Bar], events: list[dict]):
    """Per (direction x scheme) pnl lists + per-trade meta (entry_ts) for eff-n/concentration."""
    idx = {b.ts: i for i, b in enumerate(bars)}
    res = {d: {s: [] for s in ("E1", "E2", "E3", "E4")} for d in (1, -1)}
    meta = {d: {s: [] for s in ("E1", "E2", "E3", "E4")} for d in (1, -1)}
    fills = {d: {s: 0 for s in ("E1", "E2", "E3")} for d in (1, -1)}
    for e in events:
        it = idx.get(e["ts"])
        if it is None:
            continue
        d = e["dir"]
        per = {}
        for s, fn in SCHEMES.items():
            r = fn(bars, it, d, e["open"], e["extreme"], e["range"])
            if r is None:
                per[s] = None; continue
            ei, epx = r
            fills[d][s] += 1
            pnl = manage(bars, ei, epx, d, e["open"], e["extreme"], e["range"])
            per[s] = pnl
            res[d][s].append(pnl); meta[d][s].append(bars[ei].ts)
        legs = [x for x in (per["E2"], per["E3"]) if x is not None]
        if legs:
            res[d]["E4"].append(0.5 * sum(legs)); meta[d]["E4"].append(bars[it].ts)
    return res, meta, fills
