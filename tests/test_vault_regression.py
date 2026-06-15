"""T02 — engine regression suite: the guard rail.

Locks the harness's reproduction of each vault strategy's headline stats so no
future engine change silently shifts the numbers. Every assertion names the
vault id and its tolerance. Plain asserts (no pytest in this env); runs via
`python3 tests/test_vault_regression.py`.

If a later task breaks one of these, that task is BLOCKED, not DONE.

Scope note (operator-directed): the 5m strategies are the acceptance gate. The
15m V4 configs are present in the vault but their harness baselines are not yet
calibrated/locked — they are SKIPPED here and reported pending (see
test_15m_v4_configs_pending), never failed.

Two known vault/harness discrepancies are intentionally NOT asserted (flagged to
the operator, not silently reconciled):
  - EMA_PROX_V4_5M results-block (n=22, total 5461, PF 16.01, maxDD -212) predates
    the T01 re-baseline (base = n=21, +4935, PF 5.66). The harness reproduces the
    rules-narrative numbers (base +4935; daily-align lifts PF into the documented
    5.7->8.1 band), not the stale results-block. We lock the harness output.
  - Sharpe: the vault's sharpe_daily_ann uses a different convention than the
    harness daily-grouping Sharpe (e.g. V0B vault 3.81 vs harness ~5.87), so
    Sharpe is excluded from every assertion below.
"""
import sys, os
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from collections import OrderedDict
from zoneinfo import ZoneInfo

from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest
from src.engine.v4 import V4Engine, V4Config, _Ema

ET = ZoneInfo("America/New_York")
# Committed/tracked bar store lives in src/data/ (the untracked top-level data/ is
# not guaranteed on a fresh checkout). Repo-root-relative so CWD doesn't matter.
DATA_5M = os.path.join(_REPO, "src", "data", "MNQ_5m_aggregated_clean.csv")
DATA_15M = os.path.join(_REPO, "src", "data", "MNQ_15m_aggregated_clean.csv")
NO_STOP = 1e9          # stop_atr large enough that the catastrophe stop never fires

# tolerances (a regression guard pins tightly; these absorb only float rounding)
TOL = {"win_pct": 0.5, "total_pts": 5.0, "pf": 0.05, "max_dd": 5.0}

_BARS_5M = load_bars(DATA_5M)
_TUPLES_5M = [(b.ts, b.open, b.high, b.low, b.close) for b in _BARS_5M]


def _daily_gap_fn(bars):
    """Prior-day daily 9x50 EMA gap (gap, rising) keyed by ET calendar date.
    Daily close = last bar close per ET date; prior-day lookup avoids lookahead.
    Drives V4's daily-align +1 sizing."""
    daily = OrderedDict()
    for b in bars:
        daily[b.ts.astimezone(ET).date()] = b.close
    dates = list(daily)
    ef, es = _Ema(9), _Ema(50)
    gap_by_date, prev = {}, None
    for d in dates:
        g = ef.update(daily[d]) - es.update(daily[d])
        gap_by_date[d] = (g, prev is not None and g > prev)
        prev = g
    prior = {d: (gap_by_date[dates[i - 1]] if i > 0 else (0.0, False))
             for i, d in enumerate(dates)}
    return lambda ts: prior[ts.astimezone(ET).date()]


_DAILY_GAP_5M = _daily_gap_fn(_BARS_5M)


def _stats_for(cfg, tuples, daily_gap_fn=None):
    _, st = run_backtest(tuples, V4Engine(cfg), friction_pts=1.0, daily_gap_fn=daily_gap_fn)
    return st


def _assert_stats(vault_id, st, expected):
    """expected: dict of field->value; tolerance from TOL (n is exact)."""
    assert st.n == expected["n"], f"{vault_id}: n {st.n} != {expected['n']}"
    for field, exp in expected.items():
        if field == "n":
            continue
        act = getattr(st, field)
        tol = TOL[field]
        assert abs(act - exp) <= tol, f"{vault_id}.{field}: {act:.4f} vs {exp}±{tol}"


# --------------------------------------------------------------------------
# EMA_PROX_V4_5M — base / daily-align / stop variants
# --------------------------------------------------------------------------
def test_v4_5m_base():
    # vault EMA_PROX_V4_5M base (signal-exit, no stop, no daily-align):
    # rules.exit_study "+4,935"; T01 baseline n=21, PF 5.66.
    st = _stats_for(V4Config(accel=True, daily_align_size=False, stop_atr=NO_STOP), _TUPLES_5M)
    _assert_stats("EMA_PROX_V4_5M/base", st,
                  {"n": 21, "win_pct": 71.43, "total_pts": 4934.75, "pf": 5.66, "max_dd": -736.5})


def test_v4_5m_daily_align():
    # vault EMA_PROX_V4_5M rules.sizing: "+1 when daily 9x50 gap>0 and rising
    # (PF 5.7->8.1)". Harness lifts base PF 5.66 -> 6.96, total 4935 -> 8114
    # (within the documented uplift band). Locked as regression baseline.
    st = _stats_for(V4Config(accel=True, daily_align_size=True, stop_atr=NO_STOP),
                    _TUPLES_5M, _DAILY_GAP_5M)
    _assert_stats("EMA_PROX_V4_5M/daily-align", st,
                  {"n": 21, "win_pct": 71.43, "total_pts": 8113.75, "pf": 6.96, "max_dd": -736.5})
    base = _stats_for(V4Config(accel=True, daily_align_size=False, stop_atr=NO_STOP), _TUPLES_5M)
    assert st.total_pts > base.total_pts and st.pf > base.pf, "daily-align must lift base"


def test_v4_5m_stop_4atr():
    # vault EMA_PROX_V4_5M rules.disaster_stop "4*ATR below entry". Locked
    # regression baseline for the stop path; stop cuts total vs base (4935->2828)
    # and tightens maxDD (-736 -> -305), consistent with the vault narrative.
    st = _stats_for(V4Config(accel=True, daily_align_size=False, stop_atr=4.0), _TUPLES_5M)
    _assert_stats("EMA_PROX_V4_5M/stop-4ATR", st,
                  {"n": 25, "win_pct": 36.0, "total_pts": 2827.79, "pf": 3.88, "max_dd": -305.0})


# --------------------------------------------------------------------------
# EMA_PROX_V0B_5M — exact vault headline reproduction
# --------------------------------------------------------------------------
def test_v0b_5m():
    # vault EMA_PROX_V0B_5M: k=0.75 fixed, no acceleration, no stop. Harness
    # reproduces the published headline exactly: n=40, win 45.0%, total 4380,
    # PF 3.11, maxDD -1248.
    st = _stats_for(V4Config(k_fixed=0.75, accel=False, daily_align_size=False, stop_atr=NO_STOP),
                    _TUPLES_5M)
    _assert_stats("EMA_PROX_V0B_5M", st,
                  {"n": 40, "win_pct": 45.0, "total_pts": 4380.25, "pf": 3.11, "max_dd": -1248.5})


# --------------------------------------------------------------------------
# 15m V4 configs — pending (baselines not yet calibrated); never fails the suite
# --------------------------------------------------------------------------
def test_15m_v4_configs_pending():
    have_15m = os.path.exists(DATA_15M)
    # Vault 15m V4 configs (EMA_PROX_V4_15M k=0.75 / k=1.5, accel ablation) exist
    # but their harness baselines have not been locked under T02 (operator scope:
    # 5m is the gate). Reported pending; not asserted, not failed.
    note = "present" if have_15m else "absent"
    print(f"  [pending] 15m V4 regression baselines not yet calibrated "
          f"(15m CSV {note}) — to be locked in a follow-up.")
    assert True


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} VAULT REGRESSION TESTS PASSED (15m configs pending)")


if __name__ == "__main__":
    _run_all()
