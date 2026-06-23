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
def test_enter_places_market_only_no_stop():
    # STOPLESS: entry is a plain MarketOrder — no bracket / stop attached
    b = _bridge(route_risk=False)
    for _ in range(20):
        b.ema.update(100.0); atr = b.atr.update(101.0, 99.0, 100.0)
    b._enter(ts="t0", entry=100.0, atr=atr)
    assert b.position == 1 and not hasattr(b, "stop_price")
    payload = b.client.sent[-1]["payload"]
    assert payload["orderType"] == "Market" and payload["orderQty"] == 1
    assert "bracket" not in payload                       # no stop attached
    assert payload["source"] == "operator-external/paper"


def test_no_intrabar_stop_out():
    # a deep low after entry must NOT close the position — there is no stop anymore
    b = _bridge(route_risk=False)
    for _ in range(20):
        b.ema.update(100.0); atr = b.atr.update(101.0, 99.0, 100.0)
    b._enter(ts="t0", entry=100.0, atr=atr)
    base = 1_750_000_000; base -= base % 120
    b.on_closed_bar(base, o=100.0, h=100.0, l=50.0, c=60.0)   # huge drawdown bar
    assert b.position == 1 and len(b.trades) == 0            # still long, no stop-out


def test_risk_veto_on_extreme_atr():
    # account catastrophe sizing (4*ATR) exceeds the $200/trade ceiling -> REJECT
    b = _bridge(route_risk=True)
    for _ in range(20):
        b.ema.update(100.0); atr = b.atr.update(140.0, 60.0, 100.0)   # atr ~80
    n_before = len(b.client.sent)
    b._enter(ts="t0", entry=100.0, atr=atr)
    assert b.position == 0 and len(b.client.sent) == n_before         # nothing placed


# ---------------- delayed reqMktData polling (offline) ----------------
class _FakeIB:
    def sleep(self, n):                 # no real waiting in tests
        pass


class _FakeTicker:
    def __init__(self, lasts, close):
        self._lasts = list(lasts); self._i = 0; self.close = close
    @property
    def last(self):
        v = self._lasts[min(self._i, len(self._lasts) - 1)]
        self._i += 1
        return v


def test_poll_builds_window_ohlc():
    # 4 polls over a 20s window -> O=first, H=max, L=min, C=last
    t = _FakeTicker([100.0, 105.0, 98.0, 102.0], close=99.0)
    bar = FadeBridge._poll_one_bar(_FakeIB(), t, window_s=20, poll_s=5)
    assert bar == (100.0, 105.0, 98.0, 102.0)


def test_poll_nan_falls_back_to_close():
    nan = float("nan")
    t = _FakeTicker([nan, 105.0, 98.0, 102.0], close=99.0)   # first last nan -> close
    o, h, l, c = FadeBridge._poll_one_bar(_FakeIB(), t, window_s=20, poll_s=5)
    assert o == 99.0 and h == 105.0 and l == 98.0 and c == 102.0


def test_poll_all_nan_returns_none():
    nan = float("nan")
    t = _FakeTicker([nan, nan], close=nan)
    assert FadeBridge._poll_one_bar(_FakeIB(), t, window_s=10, poll_s=5) is None


# ---------------- integrated replay (DRY_RUN) ----------------
def test_dry_run_replay_produces_trades_and_orders():
    if not os.path.exists(_DATA_2M):
        print("  [skip] 2m data not present"); return
    b = _bridge()
    b.run_dry(_DATA_2M, last_bars=4000)
    assert b.bars_processed > 100
    assert len(b.trades) > 0
    # every entry placed at least one order payload
    assert len(b.client.sent) > 0
    reasons = {t["reason"] for t in b.trades}
    assert reasons == {"SIGNAL_REVERSION"}               # stopless: signal exits only


# ---------------- ZERO DRIFT vs the backtest harness ----------------
def test_zero_drift_vs_harness():
    """Stopless bridge with no risk veto must reproduce the harness's trades
    exactly — same engine, same bars, signal-only exits, no drift."""
    if not os.path.exists(_DATA_2M):
        print("  [skip] 2m data not present"); return
    with open(_DATA_2M, newline="") as f:
        rows = list(csv.DictReader(f))[-5000:]
    bars = [(int(r["time"]), float(r["open"]), float(r["high"]),
             float(r["low"]), float(r["close"])) for r in rows]

    # harness reference (same friction the bridge uses)
    h_trades, _ = run_backtest(bars, MeanRevFadeEngine(MeanRevConfig()), friction_pts=1.0)

    # bridge: isolate engine fidelity (no risk veto)
    b = _bridge(route_risk=False)
    for ts, o, h, l, c in bars:
        b.on_closed_bar(ts, o, h, l, c)

    # same engine + bars + friction, stopless/no-veto => identical trade-by-trade pnl.
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
