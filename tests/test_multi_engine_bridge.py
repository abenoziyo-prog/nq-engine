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
    assert "MEANREV_FADE_2M" in ids and len(ids) == 16 # 9 long + 7 short mirrors
    assert "MEANREV_FADE_2M_SHORT" in ids              # short mirrors present
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


def test_heartbeat_covers_all_engines():
    if not os.path.exists(_DATA_1M):
        print("  [skip] 1m data not present"); return
    b = _bridge()
    b.run_dry(_DATA_1M, last_bars=20000)               # populates per-engine bar counts
    # every engine consumed bars at its timeframe (alive), and heartbeat names all 9
    assert all(st["bars"] > 0 for st in b.states)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        b._heartbeat()
    line = buf.getvalue()
    assert "16/16 engines fed" in line
    for st in b.states:
        assert st["spec"].id in line                   # each engine reported


def test_shutdown_flattens_and_summarizes():
    if not os.path.exists(_DATA_1M):
        print("  [skip] 1m data not present"); return
    b = _bridge()
    b.run_dry(_DATA_1M, last_bars=40000)
    b.shutdown()
    assert all(st["pos"] == 0 for st in b.states) and b.net == 0   # flat after shutdown


def test_short_mirror_direction_isolation():
    # short config must emit ONLY short signals; long config ONLY long (zero leakage)
    import csv
    from src.engine.meanrev_fade import MeanRevFadeEngine, MeanRevConfig
    path = "src/data/MNQ_2m_12mo_databento.csv"
    if not os.path.exists(path):
        print("  [skip] 2m data not present"); return
    rows = list(csv.DictReader(open(path)))[-30000:]

    def sigs(cfg):
        e = MeanRevFadeEngine(cfg); out = set()
        for r in rows:
            d = e.on_bar(float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
            if d:
                out.add(str(d["signal"]))
        return out

    s_short = sigs(MeanRevConfig(direction="short"))
    s_long = sigs(MeanRevConfig())
    assert s_short and all("SHORT" in s for s in s_short), s_short
    assert s_long and all("LONG" in s for s in s_long), s_long


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} MULTI-ENGINE TESTS PASSED")


if __name__ == "__main__":
    _run_all()
