"""Multi-engine paper router tests. Offline (DRY_RUN); no Gateway, no real orders.

Run under venv: .venv/bin/python tests/test_multi_engine_bridge.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from multi_engine_bridge import MultiEngineBridge, BarAggregator

_DATA_1M = "src/data/MNQ_1m_12mo_databento.csv"
_TMP = tempfile.mkdtemp()


def _bridge():
    return MultiEngineBridge(dry_run=True, logdir=_TMP, session_date="TEST")


# ---- aggregator (generic step) ----
def test_aggregator_15m_step():
    out = []
    agg = BarAggregator(900, lambda k, o, h, l, c, v: out.append((k, o, h, l, c)))
    base = 1_750_000_000; base -= base % 900
    agg.add(base + 0,   100, 101, 99, 100)
    agg.add(base + 600, 100, 108, 95, 104)     # same 15m bucket: H=108 L=95
    agg.add(base + 900, 104, 104, 103, 103)    # next bucket -> emit first
    assert out == [(base, 100, 108, 95, 104)]


# ---- book wiring ----
def test_book_excludes_shock_and_has_engines():
    b = _bridge()
    ids = {st["spec"].id for st in b.states}
    assert "SHOCK_V1" not in ids                       # disabled (no volume)
    assert "MEANREV_FADE_2M" in ids and len(ids) == 9  # all feed-feasible engines
    assert set(b.by_tf) == {2, 5, 15}                  # three timeframes wired


def test_dry_run_book_trades_tagged_and_netted():
    if not os.path.exists(_DATA_1M):
        print("  [skip] 1m data not present"); return
    b = _bridge()
    b.run_dry(_DATA_1M, last_bars=40000)               # ~4 weeks of 1m bars
    assert b.bars_seen > 1000
    assert len(b.trades) > 0
    strategies = {t["strategy"] for t in b.trades}
    assert len(strategies) >= 3                         # several engines fired
    # every fill is attributable: tagged with id + gate_status
    for t in b.trades:
        assert t["strategy"] and t["gate_status"]
    # net exposure is an int and consistent with open positions
    assert isinstance(b.net, int)
    assert b.net == sum(st["pos"] for st in b.states)


def test_shutdown_flattens_and_summarizes():
    if not os.path.exists(_DATA_1M):
        print("  [skip] 1m data not present"); return
    b = _bridge()
    b.run_dry(_DATA_1M, last_bars=40000)
    b.shutdown()
    assert all(st["pos"] == 0 for st in b.states) and b.net == 0   # flat after shutdown


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} MULTI-ENGINE TESTS PASSED")


if __name__ == "__main__":
    _run_all()
