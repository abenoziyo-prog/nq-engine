"""T15/T18 — IBKR paper bridge tests.

Safety paths (DRY_RUN default, live-port/live-account refusal) need no broker.
PAPER_LIVE paths are exercised OFFLINE by patching ib_async.IB with a mock — no
socket, no Gateway, no real orders. Real ib_async Order classes are used so the
OSO->IB translation is tested for real.

Run under the venv (ib_async must import): .venv/bin/python tests/test_ibkr.py
"""
import sys, os
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bridge.ibkr_client import IBKRClient, IBKRConfig
from src.bridge.bridge import Bridge, Signal
from src.bridge.oso import build_oso, build_flatten
from src.risk.manager import AccountState

_PAPER = {"IBKR_ACCOUNT": "DU1234567", "IBKR_PORT": "4002"}


def _set(env):
    os.environ.update(env)


def _clear():
    for k in ("IBKR_ACCOUNT", "IBKR_PORT", "IBKR_HOST", "IBKR_CLIENT_ID"):
        os.environ.pop(k, None)


# ---- offline mock of ib_async.IB ----
class _MockClient:
    def __init__(self):
        self._id = 0
    def getReqId(self):
        self._id += 1
        return self._id


class _MockIB:
    """Records calls; returns plausible paper responses. No network."""
    def __init__(self, managed=("DU1234567",)):
        self._managed = list(managed)
        self.client = _MockClient()
        self.connected = False
        self.market_data_type = None
        self.placed = []          # (contract, order) tuples
        self._open = []           # resting trades
        self.cancelled = []
        self.disconnected = False
    def connect(self, host, port, clientId):
        self.connected = True
        self.connect_args = (host, port, clientId)
    def reqMarketDataType(self, n):
        self.market_data_type = n
    def managedAccounts(self):
        return self._managed
    def qualifyContracts(self, fut):
        return [SimpleNamespace(localSymbol="MNQU6", conId=793356225, symbol="MNQ")]
    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        trade = SimpleNamespace(order=order, contract=contract,
                                orderStatus=SimpleNamespace(status="PreSubmitted"))
        self._open.append(trade)
        return trade
    def openTrades(self):
        return list(self._open)
    def cancelOrder(self, order):
        self.cancelled.append(order)
        self._open = [t for t in self._open if t.order is not order]
    def positions(self, account):
        return [SimpleNamespace(
            contract=SimpleNamespace(localSymbol="MNQU6", symbol="MNQ", conId=793356225),
            position=1.0, avgCost=21000.0)]
    def accountSummary(self, account):
        return [SimpleNamespace(tag="NetLiquidation", value="1000086.0"),
                SimpleNamespace(tag="UnrealizedPnL", value="12.5"),
                SimpleNamespace(tag="RealizedPnL", value="-4.0")]
    def sleep(self, n):
        pass
    def disconnect(self):
        self.disconnected = True
        self.connected = False


def _patch_ib(managed=("DU1234567",)):
    return mock.patch("ib_async.IB", lambda: _MockIB(managed))


# ---------------- DRY_RUN + safety (no broker) ----------------
def test_client_defaults_dry_run_no_creds():
    _clear()
    c = IBKRClient()
    assert c.has_credentials is False
    assert c.mode == "DRY_RUN"
    assert c.authenticate()["mode"] == "DRY_RUN"
    ack = c.place_order({"isAutomated": True, "symbol": "MNQ"})
    assert ack["ok"] and ack["mode"] == "DRY_RUN" and ack["orderId"] == "SIM-1"
    assert len(c.sent) == 1


def test_client_stays_dry_run_even_with_paper_creds():
    # paper acct + paper port present, but dry_run not disabled -> still DRY_RUN
    _set(_PAPER)
    try:
        c = IBKRClient()
        assert c.has_credentials is True
        assert c.mode == "DRY_RUN"               # must NOT auto-go-live
    finally:
        _clear()


def test_live_account_id_refused():
    # a real-money account id ("U…", not "DU…") must never count as credentialed
    _set({"IBKR_ACCOUNT": "U7654321", "IBKR_PORT": "4002"})
    try:
        c = IBKRClient(IBKRConfig(dry_run=False))
        assert c.is_paper_account is False
        assert c.has_credentials is False and c.mode == "DRY_RUN"
    finally:
        _clear()


def test_live_port_hard_refused():
    # even with a paper account, a live port (7496) is refused at authenticate()
    _set({"IBKR_ACCOUNT": "DU1234567", "IBKR_PORT": "7496"})
    try:
        c = IBKRClient(IBKRConfig(dry_run=False))
        assert c.is_paper_port is False and c.mode == "DRY_RUN"
        try:
            c.authenticate(); assert False, "live port must raise"
        except ValueError:
            pass
    finally:
        _clear()


def test_gateway_paper_port_ok():
    _set({"IBKR_ACCOUNT": "DU999", "IBKR_PORT": "4002"})   # IB Gateway paper
    try:
        c = IBKRClient()
        assert c.is_paper_port is True and c.has_credentials is True
    finally:
        _clear()


# ---------------- PAPER_LIVE (mocked ib_async) ----------------
def test_authenticate_paper_live_connects():
    _set(_PAPER)
    try:
        with _patch_ib():
            c = IBKRClient(IBKRConfig(dry_run=False))
            assert c.mode == "PAPER_LIVE"
            res = c.authenticate()
            assert res["mode"] == "PAPER_LIVE" and res["ok"]
            assert res["contract"] == "MNQU6" and res["conId"] == 793356225
            assert res["marketDataType"] == 3            # delayed wired on connect
            assert c._connected is True
            assert c._ib.connect_args == ("127.0.0.1", 4002, 7)
    finally:
        _clear()


def test_authenticate_refuses_account_mismatch():
    # connected session manages a different account -> refuse + disconnect
    _set(_PAPER)
    try:
        with _patch_ib(managed=("DUOTHER999",)):
            c = IBKRClient(IBKRConfig(dry_run=False))
            try:
                c.authenticate(); assert False, "mismatch must raise"
            except ValueError:
                pass
    finally:
        _clear()


def test_place_order_paper_live_submits_bracket():
    _set(_PAPER)
    try:
        with _patch_ib():
            c = IBKRClient(IBKRConfig(dry_run=False))
            c.authenticate()
            payload = build_oso("MNQU6", "Buy", 1, 21000, 20902, 21196, account_spec="PAPER")
            ack = c.place_order(payload)
            assert ack["mode"] == "PAPER_LIVE" and ack["ok"]
            assert len(ack["legs"]) == 3                  # parent + TP + SL
            parent, tp, sl = ack["legs"]
            assert parent["action"] == "BUY" and parent["type"] == "MKT"
            assert tp["action"] == "SELL" and sl["action"] == "SELL"
            # all three routed to the paper account, with OCA-linked children
            placed = c._ib.placed
            assert len(placed) == 3
            assert all(o.account == "DU1234567" for _, o in placed)
            assert placed[1][1].lmtPrice == 21196 and placed[2][1].auxPrice == 20902
    finally:
        _clear()


def test_place_order_paper_live_flatten_single():
    _set(_PAPER)
    try:
        with _patch_ib():
            c = IBKRClient(IBKRConfig(dry_run=False))
            c.authenticate()
            ack = c.place_order(build_flatten("MNQU6", open_position=2, account_spec="PAPER"))
            assert ack["mode"] == "PAPER_LIVE" and len(ack["legs"]) == 1
            assert ack["legs"][0]["action"] == "SELL" and ack["legs"][0]["qty"] == 2
    finally:
        _clear()


def test_place_order_paper_live_stop_only_bracket():
    # fade runner: entry Market + disaster Stop, NO take-profit (exit is signal-driven)
    _set(_PAPER)
    try:
        with _patch_ib():
            c = IBKRClient(IBKRConfig(dry_run=False))
            c.authenticate()
            payload = {"accountSpec": "PAPER", "symbol": "MNQU6", "action": "Buy",
                       "orderQty": 1, "orderType": "Market", "isAutomated": True,
                       "bracket": {"stopLoss": {"action": "Sell", "orderType": "Stop",
                                                "stopPrice": 20950, "isAutomated": True}}}
            ack = c.place_order(payload)
            assert len(ack["legs"]) == 2                  # parent + stop only
            assert ack["legs"][1]["action"] == "SELL"
            assert c._ib.placed[1][1].auxPrice == 20950 and c._ib.placed[1][1].transmit is True
    finally:
        _clear()


def test_cancel_open_orders_paper_live():
    _set(_PAPER)
    try:
        with _patch_ib():
            c = IBKRClient(IBKRConfig(dry_run=False))
            c.authenticate()
            c.place_order(build_flatten("MNQU6", 1, account_spec="PAPER"))
            res = c.cancel_open_orders()
            assert res["cancelled"] == 1 and len(c._ib.cancelled) == 1
    finally:
        _clear()


def test_cancel_open_orders_dry_run_stub():
    _clear()
    c = IBKRClient()
    assert c.cancel_open_orders()["mode"] == "DRY_RUN"


def test_sync_request_paper_live():
    _set(_PAPER)
    try:
        with _patch_ib():
            c = IBKRClient(IBKRConfig(dry_run=False))
            c.authenticate()
            s = c.sync_request()
            assert s["mode"] == "PAPER_LIVE" and s["account"] == "DU1234567"
            assert s["NetLiquidation"] == 1000086.0 and s["UnrealizedPnL"] == 12.5
            assert s["positions"][0]["conId"] == 793356225
    finally:
        _clear()


def test_place_order_paper_live_refuses_when_not_connected():
    _set(_PAPER)
    try:
        c = IBKRClient(IBKRConfig(dry_run=False))   # never authenticated
        try:
            c.place_order(build_flatten("MNQU6", 1)); assert False, "must require connect"
        except RuntimeError:
            pass
    finally:
        _clear()


# ---------------- bridge drop-in (DRY_RUN) ----------------
def test_bridge_defaults_to_ibkr_and_builds_paper_oso():
    _clear()
    b = Bridge()
    assert isinstance(b.client, IBKRClient)
    rec = b.on_signal(Signal("MEANREV", "BUY", "MNQ", 21000, atr=24.5, stop_dist=98),
                      AccountState())
    assert rec["verdict"] == "ALLOW" and rec["approved_qty"] == 1
    assert rec["action"] == "SUBMITTED(paper)"
    assert rec["order"]["isAutomated"] is True
    assert rec["order"]["accountSpec"] == "PAPER"
    assert rec["order"]["bracket"]["stopLoss"]["stopPrice"] == 20902   # 21000-98
    assert rec["order"]["bracket"]["takeProfit"]["price"] == 21196     # 2R


def test_bridge_flat_allowed_when_halted():
    _clear()
    b = Bridge()
    halted = AccountState(halted=True, open_position=2)
    flat = b.on_signal(Signal("X", "FLAT", "MNQ", 21000), halted)
    assert flat["action"] == "FLATTEN(paper)" and flat["order"]["orderQty"] == 2


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ALL {len(tests)} IBKR TESTS PASSED")


if __name__ == "__main__":
    _run_all()
