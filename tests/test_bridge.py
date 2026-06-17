"""T12-T14 — Tradovate demo bridge path tests (dry-run; no network; no live orders).

Plain asserts (no pytest); run: python3 tests/test_bridge.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bridge.tradovate_client import TradovateClient, TradovateConfig
from src.bridge.oso import build_oso, build_flatten, round_tick
from src.bridge.bridge import Bridge, Signal
from src.risk.manager import RiskManager, RiskConfig, AccountState


# ---------------- T12 client ----------------
def test_client_defaults_dry_run_no_creds():
    c = TradovateClient()
    assert c.mode == "DRY_RUN"
    assert c.authenticate()["mode"] == "DRY_RUN"
    ack = c.place_order({"isAutomated": True, "symbol": "MNQ"})
    assert ack["ok"] and ack["mode"] == "DRY_RUN" and ack["orderId"] == "SIM-1"
    assert len(c.sent) == 1                      # paper-logged, not sent live


def test_client_stays_dry_run_even_with_creds():
    # creds present but dry_run not explicitly disabled -> still DRY_RUN (safety default)
    os.environ.update({"TRADOVATE_NAME": "x", "TRADOVATE_PASSWORD": "y",
                       "TRADOVATE_CID": "1", "TRADOVATE_SEC": "z"})
    try:
        c = TradovateClient()
        assert c.has_credentials is True
        assert c.mode == "DRY_RUN"               # must NOT auto-go-live
    finally:
        for k in ("NAME", "PASSWORD", "CID", "SEC"):
            os.environ.pop("TRADOVATE_" + k, None)


def test_client_demo_live_order_is_blocked():
    os.environ.update({"TRADOVATE_NAME": "x", "TRADOVATE_PASSWORD": "y",
                       "TRADOVATE_CID": "1", "TRADOVATE_SEC": "z"})
    try:
        c = TradovateClient(TradovateConfig(dry_run=False))
        assert c.mode == "DEMO_LIVE"
        for call in (c.authenticate, lambda: c.place_order({})):
            try:
                call(); assert False, "DEMO_LIVE must be blocked pending T18"
            except NotImplementedError:
                pass
    finally:
        for k in ("NAME", "PASSWORD", "CID", "SEC"):
            os.environ.pop("TRADOVATE_" + k, None)


# ---------------- T13 OSO ----------------
def test_oso_long_bracket_and_isautomated():
    o = build_oso("MNQU6", "Buy", 1, 21000, 20902, 21196)
    assert o["isAutomated"] is True
    assert o["bracket"]["stopLoss"]["stopPrice"] == 20902
    assert o["bracket"]["takeProfit"]["price"] == 21196
    assert o["bracket"]["stopLoss"]["action"] == "Sell"   # opposite side
    assert o["bracket"]["oco"] is True
    assert o["risk_pts"] == 98 and o["reward_pts"] == 196


def test_oso_tick_rounding_and_bad_geometry():
    o = build_oso("MNQ", "Buy", 2, 21000.13, 20950.07, 21100.11)
    assert o["bracket"]["stopLoss"]["stopPrice"] == round_tick(20950.07)
    for bad in [("Buy", 21000, 21050, 21100),     # stop above entry (long)
                ("Sell", 21000, 20950, 21100)]:    # stop below entry (short)
        try:
            build_oso("MNQ", bad[0], 1, bad[1], bad[2], bad[3]); assert False
        except ValueError:
            pass


def test_flatten_order():
    o = build_flatten("MNQ", open_position=-2)
    assert o["action"] == "Buy" and o["orderQty"] == 2 and o["orderType"] == "Market"


# ---------------- T14 bridge ----------------
def test_bridge_allows_and_builds_paper_oso():
    b = Bridge()
    # 98pt stop @ MNQ $2/pt = $196 < $200 ceiling -> ALLOW 1 (the T04 boundary)
    rec = b.on_signal(Signal("MEANREV", "BUY", "MNQ", 21000, atr=24.5, stop_dist=98),
                      AccountState())
    assert rec["verdict"] == "ALLOW" and rec["approved_qty"] == 1
    assert rec["action"] == "SUBMITTED(paper)"
    assert rec["order"]["isAutomated"] is True
    assert rec["order"]["bracket"]["stopLoss"]["stopPrice"] == 20902   # 21000-98
    assert rec["order"]["bracket"]["takeProfit"]["price"] == 21196     # 2R


def test_bridge_rejects_too_wide_stop_no_order():
    b = Bridge()
    rec = b.on_signal(Signal("X", "BUY", "MNQ", 21000, atr=30, stop_dist=120),  # 120*2=$240>$200
                      AccountState())
    assert rec["verdict"] == "REJECT" and rec["action"] == "DROPPED"
    assert "order" not in rec and len(b.client.sent) == 0               # nothing placed


def test_bridge_halt_blocks_entry_but_flat_allowed():
    b = Bridge()
    halted = AccountState(halted=True, open_position=2)
    rec = b.on_signal(Signal("X", "BUY", "MNQ", 21000, atr=10, stop_dist=40), halted)
    # halted account REJECTs new entries (HALT is reserved for DD/session triggers)
    assert rec["verdict"] == "REJECT" and rec["action"] == "DROPPED"
    assert "order" not in rec
    flat = b.on_signal(Signal("X", "FLAT", "MNQ", 21000), halted)
    assert flat["action"] == "FLATTEN(paper)" and flat["order"]["orderQty"] == 2


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} BRIDGE TESTS PASSED")


if __name__ == "__main__":
    _run_all()
