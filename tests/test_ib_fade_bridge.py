"""Tests for ib_fade_bridge — aggregation, order mechanics, and ZERO DRIFT vs the
backtest harness. All offline (DRY_RUN); no Gateway, no real orders.

Run under the venv: .venv/bin/python tests/test_ib_fade_bridge.py
"""
import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ib_fade_bridge import TwoMinAggregator, FadeBridge
from src.bridge.oso import round_tick
from src.backtest.harness import run_backtest
from src.engine.meanrev_fade import MeanRevFadeEngine, MeanRevConfig

_DATA_2M = "src/data/MNQ_2m_12mo_databento.csv"
_TMP = tempfile.mkdtemp()


def _bridge(**kw):
    kw.setdefault("logdir", _TMP)
    kw.setdefault("session_date", "TEST")
    return FadeBridge(**kw)


# ---------------- aggregator ----------------
def test_aggregator_true_ohlc_and_boundary():
    out = []
    agg = TwoMinAggregator(lambda k, o, h, l, c, v: out.append((k, o, h, l, c, v)))
    base = 1_750_000_000
    base -= base % 120                      # align to a 2m boundary
    # bucket A: three 5s sub-bars; true high/low must come from the extremes
    agg.add(base + 0,  100, 101, 99,  100, 1)
    agg.add(base + 5,  100, 105, 98,  103, 2)   # high 105, low 98
    agg.add(base + 115, 103, 104, 102, 102, 3)
    # first sub-bar of bucket B -> bucket A emits
    agg.add(base + 120, 102, 102, 101, 101, 4)
    assert len(out) == 1
    k, o, h, l, c, v = out[0]
    assert k == base and o == 100 and h == 105 and l == 98 and c == 102 and v == 6
    agg.close_final()                        # flush bucket B
    assert len(out) == 2 and out[1][0] == base + 120


def test_aggregator_clock_alignment_matches_resample():
    # a sub-bar at any epoch lands in floor(epoch/120)*120 — same rule as resample.py
    out = []
    agg = TwoMinAggregator(lambda k, *a: out.append(k))
    agg.add(1000, 1, 1, 1, 1)            # 1000 -> 960
    agg.add(1080, 1, 1, 1, 1)            # 1080 -> 1080 (new bucket) -> emits 960
    assert out == [960]
    assert (1000 - 1000 % 120) == 960 and (1080 - 1080 % 120) == 1080


# ---------------- order mechanics (DRY_RUN) ----------------
def test_enter_attaches_disaster_stop():
    b = _bridge(stop_atr=2.5, route_risk=False)
    # warm trackers so atr is real, then drive an entry directly
    for _ in range(20):
        b.ema.update(100.0); atr = b.atr.update(101.0, 99.0, 100.0)
    b._enter(ts="t0", entry=100.0, atr=atr)
    assert b.position == 1
    assert b.stop_price == round_tick(100.0 - 2.5 * atr)
    # one bracket payload logged by the client (entry + stop)
    assert b.client.sent[-1]["payload"]["bracket"]["stopLoss"]["stopPrice"] == b.stop_price


def test_disaster_stop_fires_in_dry_run():
    b = _bridge(stop_atr=2.5, route_risk=False, simulate_stop=True)
    for _ in range(20):
        b.ema.update(100.0); atr = b.atr.update(101.0, 99.0, 100.0)
    b._enter(ts="t0", entry=100.0, atr=atr)
    stop = b.stop_price
    base = 1_750_000_000; base -= base % 120
    # a bar whose LOW pierces the stop -> simulated stop-out at the stop price
    b.on_closed_bar(base, o=100.0, h=100.0, l=stop - 1.0, c=stop - 0.5)
    assert b.position == 0
    t = b.trades[-1]
    assert t["reason"] == "DISASTER_STOP" and t["exit"] == stop


def test_risk_veto_drops_oversized_stop():
    # huge stop_atr -> per-trade $ risk exceeds the $200 ceiling -> risk REJECT, no order
    b = _bridge(stop_atr=50.0, route_risk=True)
    for _ in range(20):
        b.ema.update(100.0); atr = b.atr.update(140.0, 60.0, 100.0)   # big atr
    n_before = len(b.client.sent)
    b._enter(ts="t0", entry=100.0, atr=atr)
    assert b.position == 0 and len(b.client.sent) == n_before        # nothing placed


# ---------------- integrated replay (DRY_RUN) ----------------
def test_dry_run_replay_produces_trades_and_orders():
    if not os.path.exists(_DATA_2M):
        print("  [skip] 2m data not present"); return
    b = _bridge(stop_atr=2.5)
    b.run_dry(_DATA_2M, last_bars=4000)
    assert b.bars_processed > 100
    assert len(b.trades) > 0
    # every entry placed at least one order payload
    assert len(b.client.sent) > 0
    reasons = {t["reason"] for t in b.trades}
    assert reasons <= {"SIGNAL_REVERSION", "DISASTER_STOP"}


# ---------------- ZERO DRIFT vs the backtest harness ----------------
def test_zero_drift_vs_harness():
    """With no stop interference and no risk veto, the bridge must reproduce the
    harness's entry/exit prices exactly — same engine, same bars, no drift."""
    if not os.path.exists(_DATA_2M):
        print("  [skip] 2m data not present"); return
    with open(_DATA_2M, newline="") as f:
        rows = list(csv.DictReader(f))[-5000:]
    bars = [(int(r["time"]), float(r["open"]), float(r["high"]),
             float(r["low"]), float(r["close"])) for r in rows]

    # harness reference (same friction the bridge uses)
    h_trades, _ = run_backtest(bars, MeanRevFadeEngine(MeanRevConfig()), friction_pts=1.0)

    # bridge: isolate engine fidelity (no stop, no risk veto)
    b = _bridge(stop_atr=2.5, simulate_stop=False, route_risk=False)
    for ts, o, h, l, c in bars:
        b.on_closed_bar(ts, o, h, l, c)

    # same engine + bars + friction, no stop/veto => identical trade-by-trade pnl.
    assert len(b.trades) == len(h_trades), (len(b.trades), len(h_trades))
    bridge_pnl = [round(t["pnl_pts"], 6) for t in b.trades]
    harness_pnl = [round(ht["pnl_pts"], 6) for ht in h_trades]
    assert bridge_pnl == harness_pnl, "DRIFT: bridge pnl sequence != harness"
    # and entry timing aligns (harness entry_ts is epoch; bridge is the same instant)
    h_entry_epochs = [int(ht["entry_ts"]) for ht in h_trades]
    b_entry_epochs = [int(t["entry_ts"].timestamp()) for t in b.trades]
    assert b_entry_epochs == h_entry_epochs


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} FADE-BRIDGE TESTS PASSED")


if __name__ == "__main__":
    _run_all()
