"""Registry integrity for the multi-engine paper book. Offline; no broker.

Run: .venv/bin/python tests/test_engine_registry.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bridge.engine_registry import REGISTRY, enabled_specs


def test_all_ten_registered():
    assert len(REGISTRY) == 10
    ids = {s.id for s in REGISTRY}
    assert "MEANREV_FADE_2M" in ids and "SHOCK_V1" in ids


def test_shock_disabled_with_reason():
    shock = next(s for s in REGISTRY if s.id == "SHOCK_V1")
    assert shock.enabled is False and shock.blocked_reason
    assert "volume" in shock.blocked_reason.lower()
    assert shock not in enabled_specs()


def test_enabled_engines_construct_and_have_on_bar():
    for s in enabled_specs():
        eng = s.make()
        assert eng is not None and hasattr(eng, "on_bar")
        if s.needs_ts:                       # session-aware engines expose feed_ts
            assert hasattr(eng, "feed_ts")


def test_every_spec_has_gate_status_and_valid_tf():
    for s in REGISTRY:
        assert s.gate_status and s.tf_min in (1, 2, 5, 15)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} REGISTRY TESTS PASSED")


if __name__ == "__main__":
    _run_all()
