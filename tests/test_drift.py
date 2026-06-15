"""T07 — drift-control acceptance tests.

Reproduces the recorded ~0.93 NY-morning-long MFE/MAE drift benchmark
(strategy_vault.json: OB_STRICT_SINGLE_TOUCH excursion) and locks determinism.
Plain asserts (no pytest in this env); runs via `python3 tests/test_drift.py`.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.model import Session
from src.backtest.drift_control import load_bars, run_drift, monte_carlo, DriftConfig

BARS = load_bars()   # loaded once; the clean 5m series


def test_ny_am_long_reproduces_093():
    # NY_AM long, 30-min horizon (H=6): recorded drift control ≈ 0.93.
    r = run_drift(BARS, DriftConfig(session=Session.NY_AM, direction="long",
                                    horizon_bars=6, n_entries=500, seed=12345))
    assert r.n == 500, r.n
    assert 0.88 <= r.mfe_mae_ratio <= 0.98, r.mfe_mae_ratio          # ~0.93 band
    # aggregate ratio is algebraically mean(MFE)/mean(MAE)
    assert abs(r.mean_mfe / r.mean_mae - r.mfe_mae_ratio) < 1e-9


def test_determinism_same_seed_identical():
    cfg = DriftConfig(seed=777, n_entries=200)
    a = run_drift(BARS, cfg)
    b = run_drift(BARS, cfg)
    assert a.mfe_mae_ratio == b.mfe_mae_ratio
    assert a.stats.total_pts == b.stats.total_pts
    assert [t["entry_ts"] for t in a.trades] == [t["entry_ts"] for t in b.trades]


def test_monte_carlo_stable_and_reproducible():
    cfg = DriftConfig(horizon_bars=6, n_entries=200)
    mc = monte_carlo(BARS, cfg, n_seeds=200)
    # pooled ratio is the stable drift number (per-seed ratios at n=200 are noisier)
    assert 0.88 <= mc.pooled_ratio <= 0.98, mc.pooled_ratio
    assert 0.88 <= mc.mean_ratio <= 0.98, mc.mean_ratio
    assert mc.std_ratio < 0.15, mc.std_ratio          # sanity bound on per-seed spread
    # deterministic seed derivation -> identical across runs
    mc2 = monte_carlo(BARS, cfg, n_seeds=200)
    assert mc.pooled_ratio == mc2.pooled_ratio
    assert mc.mean_ratio == mc2.mean_ratio


def test_short_direction_runs():
    # mirror direction must produce a well-formed result (symmetry not asserted)
    r = run_drift(BARS, DriftConfig(session=Session.NY_AM, direction="short",
                                    horizon_bars=6, n_entries=200, seed=12345))
    assert r.n == 200
    assert r.mfe_mae_ratio > 0


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} DRIFT TESTS PASSED")


if __name__ == "__main__":
    _run_all()
