"""T04 — risk-manager boundary tests.

Proves the risk manager (src/risk/manager.py) vetoes correctly at every limit
before it ever sees a live order. Encodes the exact $50K/$2K/MNQ numbers from
the spec. Plain asserts so it runs under `python3 tests/test_risk.py` (no pytest
in this env) and under pytest if installed.

Covered boundaries (spec T04):
  - per-trade $ ceiling downsizing
  - trailing-DD proximity HALT
  - session-loss HALT
  - daily-align +1 only with buffer
  - max-contracts clamp
  - catastrophe-stop-too-wide REJECT
  - FLAT always allowed even when halted
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.risk.manager import (
    RiskManager, RiskConfig, AccountState, OrderProposal, RiskDecision, Verdict,
)


def mgr(**cfg):
    return RiskManager(RiskConfig(**cfg)) if cfg else RiskManager()


def buy(stop_dist, qty=1, price=21000.0, atr=24.5, daily_aligned=False):
    return OrderProposal("BUY", qty, price, atr, stop_dist, daily_aligned)


def sell(stop_dist, qty=1, price=21000.0, atr=24.5, daily_aligned=False):
    return OrderProposal("SELL", qty, price, atr, stop_dist, daily_aligned)


# --------------------------------------------------------------------------
# FLAT always allowed even when halted
# --------------------------------------------------------------------------
def test_flat_allowed_when_halted():
    # halted account, holding -2 contracts: closing risk must always be allowed.
    d = mgr().evaluate(OrderProposal("FLAT", 0, 21000.0, 24.5, 98.0, False),
                       AccountState(halted=True, open_position=-2))
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 2          # abs(open_position)
    assert d.reason == "flatten"


def test_flat_allowed_under_trailing_dd_breach_and_session_loss():
    # even with DD blown and session loss past the halt, FLAT still passes.
    acct = AccountState(realized_pnl_session=-5_000, realized_pnl_total=-1_950,
                        high_water=0.0, open_position=3)
    d = mgr().evaluate(OrderProposal("FLAT", 0, 21000.0, 24.5, 98.0, False), acct)
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 3


# --------------------------------------------------------------------------
# Hard halt blocks NEW entries (but not FLAT, tested above)
# --------------------------------------------------------------------------
def test_halted_account_rejects_new_entry():
    d = mgr().evaluate(buy(40.0), AccountState(halted=True))
    assert d.verdict is Verdict.REJECT
    assert d.approved_qty == 0
    assert "halted" in d.reason


# --------------------------------------------------------------------------
# Per-trade $ ceiling — the exact spec numbers
#   4*ATR = 98pt stop @ $2/pt = $196/contract < $200 ceiling
# --------------------------------------------------------------------------
def test_per_trade_ceiling_one_lot_allow():
    # $196 < $200 ceiling -> 1 lot ALLOW.
    d = mgr().evaluate(buy(98.0, qty=1), AccountState())
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 1
    assert d.stop_price == 21000.0 - 98.0   # long stop sits below entry
    assert "$196" in d.reason               # 98 * $2 * 1 contract


def test_per_trade_ceiling_two_lots_downsize_to_one():
    # tier-2 sizing (daily-aligned + buffer) requesting 2 lots: 2*$196 = $392 > $200
    # ceiling -> DOWNSIZE to 1.
    acct = AccountState(realized_pnl_session=400.0, realized_pnl_total=400.0,
                        high_water=0.0)
    d = mgr().evaluate(buy(98.0, qty=2, daily_aligned=True), acct)
    assert d.verdict is Verdict.DOWNSIZE
    assert d.approved_qty == 1
    assert "$196" in d.reason               # downsized risk = 1 * $196


def test_ceiling_allows_two_lots_when_risk_fits():
    # 40pt stop @ $2 = $80/contract; 2 lots = $160 < $200 -> tier-2 ALLOW 2.
    acct = AccountState(realized_pnl_session=400.0, realized_pnl_total=400.0,
                        high_water=0.0)
    d = mgr().evaluate(buy(40.0, qty=2, daily_aligned=True), acct)
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 2


# --------------------------------------------------------------------------
# Catastrophe-stop-too-wide REJECT (one-contract risk exceeds the ceiling)
#   boundary: 100pt @ $2 = $200 == ceiling -> ALLOW; 100.5pt = $201 -> REJECT.
# --------------------------------------------------------------------------
def test_stop_exactly_at_ceiling_allows_one():
    d = mgr().evaluate(buy(100.0, qty=1), AccountState())
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 1
    assert "$200" in d.reason


def test_stop_too_wide_rejects():
    d = mgr().evaluate(buy(100.5, qty=1), AccountState())
    assert d.verdict is Verdict.REJECT
    assert d.approved_qty == 0
    assert "exceeds ceiling" in d.reason


def test_invalid_stop_distance_rejects():
    for bad in (0.0, -5.0):
        d = mgr().evaluate(buy(bad), AccountState())
        assert d.verdict is Verdict.REJECT, bad
        assert d.reason == "invalid stop distance"


# --------------------------------------------------------------------------
# Trailing-DD proximity HALT
#   room = trailing_dd(2000) - (high_water - equity); HALT when room <= $200.
# --------------------------------------------------------------------------
def test_trailing_dd_proximity_halts_at_boundary():
    # high_water 1800, equity 0 -> drawdown 1800 -> room = $200 (== per-trade) -> HALT.
    acct = AccountState(high_water=1800.0, realized_pnl_total=0.0)
    d = mgr().evaluate(buy(40.0), acct)
    assert d.verdict is Verdict.HALT
    assert d.approved_qty == 0
    assert "trailing DD room" in d.reason


def test_trailing_dd_one_dollar_more_room_allows():
    # high_water 1799 -> room = $201 > $200 -> entries still permitted.
    acct = AccountState(high_water=1799.0, realized_pnl_total=0.0)
    d = mgr().evaluate(buy(40.0), acct)
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 1


# --------------------------------------------------------------------------
# Session-loss HALT
#   HALT when realized_pnl_session <= -daily_loss_halt ($600).
# --------------------------------------------------------------------------
def test_session_loss_halts_at_boundary():
    # session -600 exactly; total -600 keeps DD room clear so this is the binding halt.
    acct = AccountState(realized_pnl_session=-600.0, realized_pnl_total=-600.0,
                        high_water=0.0)
    d = mgr().evaluate(buy(40.0), acct)
    assert d.verdict is Verdict.HALT
    assert "session loss" in d.reason


def test_session_loss_one_dollar_short_allows():
    acct = AccountState(realized_pnl_session=-599.0, realized_pnl_total=-599.0,
                        high_water=0.0)
    d = mgr().evaluate(buy(40.0), acct)
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 1


# --------------------------------------------------------------------------
# Daily-align +1 only with buffer
#   +1 contract requires daily_aligned AND session pnl >= add_buffer ($400).
# --------------------------------------------------------------------------
def test_plus_one_granted_with_alignment_and_buffer():
    acct = AccountState(realized_pnl_session=400.0, realized_pnl_total=400.0,
                        high_water=0.0)
    d = mgr().evaluate(buy(40.0, qty=2, daily_aligned=True), acct)
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 2          # base 1 + buffered 1


def test_plus_one_denied_without_buffer():
    # aligned but $399 < $400 buffer -> stays at base 1.
    acct = AccountState(realized_pnl_session=399.0, realized_pnl_total=399.0,
                        high_water=0.0)
    d = mgr().evaluate(buy(40.0, qty=2, daily_aligned=True), acct)
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 1


def test_plus_one_denied_without_alignment():
    # plenty of buffer but not daily-aligned -> no +1, stays at base 1.
    acct = AccountState(realized_pnl_session=1_000.0, realized_pnl_total=1_000.0,
                        high_water=0.0)
    d = mgr().evaluate(buy(40.0, qty=2, daily_aligned=False), acct)
    assert d.verdict is Verdict.ALLOW
    assert d.approved_qty == 1


# --------------------------------------------------------------------------
# Max-contracts clamp
#   the tier ceiling is hard: even aligned+buffered, qty cannot exceed max_contracts.
# --------------------------------------------------------------------------
def test_max_contracts_clamp_binds():
    acct = AccountState(realized_pnl_session=400.0, realized_pnl_total=400.0,
                        high_water=0.0)
    prop = buy(40.0, qty=2, daily_aligned=True)
    # default max_contracts=3 leaves the +1 tier intact -> qty 2.
    assert mgr().evaluate(prop, acct).approved_qty == 2
    # max_contracts=1 clamps the same aligned+buffered request back down to 1.
    clamped = mgr(max_contracts=1).evaluate(prop, acct)
    assert clamped.verdict is Verdict.ALLOW
    assert clamped.approved_qty == 1


# --------------------------------------------------------------------------
# Stop-price geometry — long stops below entry, short stops above.
# --------------------------------------------------------------------------
def test_stop_price_sides():
    long_d = mgr().evaluate(buy(40.0, price=21000.0), AccountState())
    assert long_d.stop_price == 21000.0 - 40.0
    short_d = mgr().evaluate(sell(40.0, price=21000.0), AccountState())
    assert short_d.stop_price == 21000.0 + 40.0


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} RISK TESTS PASSED")


if __name__ == "__main__":
    _run_all()
