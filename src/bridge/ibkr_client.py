"""T18 — IBKR client (TWS / IB Gateway socket), PAPER_LIVE unblocked 2026-06-23.

Mirror of TradovateClient: same surface (authenticate / place_order /
sync_request / .mode / .has_credentials / .sent / .cfg.account_spec) so it is a
drop-in for the Bridge.

Constitution status (see CLAUDE.md "Operator amendments"): rule 1 is PARTIALLY
overridden — this client may place PAPER orders on the IBKR demo account, and
ONLY paper. The safety posture is unchanged in every other respect:
  - DRY_RUN is the default. It records the order payload (paper log) and returns a
    simulated ack; it performs NO network I/O and imports no network library.
  - PAPER_LIVE (real `ib_async` calls) requires BOTH an explicit opt-in
    (dry_run=False) AND a safe paper target (DU* account on a paper port).
  - Two independent guards stand between this code and a real-money book and MUST
    NOT be removed: live ports (7496/4001) are hard-refused, and only paper ("DU")
    accounts are accepted. There is no path to a live/real-money order here.

IBKR specifics: there is no REST key — "auth" is a socket connection to a running
TWS or IB Gateway session (host/port/clientId); the account id identifies the book.
Uses ib_async (2.1.0); ib_insync is archived and breaks on Python 3.14 — do not use.
ib_async is imported lazily inside the live methods so DRY_RUN stays network- and
dependency-free.

Credentials/config are read from env (IBKR_*); paper details live in .env (gitignored).
"""
from __future__ import annotations
import os
import time
from dataclasses import dataclass

# Known IB paper-trading ports. TWS paper = 7497, IB Gateway paper = 4002.
# Live ports (TWS 7496, Gateway 4001) are intentionally NOT listed — connecting
# to one is refused below, so this client can never talk to a live session.
PAPER_PORTS = (7497, 4002)
LIVE_PORTS = (7496, 4001)
CRED_KEYS = ("HOST", "PORT", "CLIENT_ID", "ACCOUNT")


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env_file(path: str | None = None) -> dict:
    """Load KEY=VALUE lines from a repo-root .env into the environment (does NOT
    override already-set vars). No-op if absent. The .env file is gitignored."""
    path = path or os.path.join(_repo_root(), ".env")
    loaded: dict[str, str] = {}
    if not os.path.exists(path):
        return loaded
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
            loaded[k] = v
    return loaded


@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 7497                 # TWS paper by default; must be a PAPER_PORT
    client_id: int = 7
    dry_run: bool = True             # NEVER auto-disable; must be explicitly set False
    env_prefix: str = "IBKR_"
    account_spec: str = "PAPER"      # logical label echoed onto order payloads
    market_data_type: int = 3        # 3 = delayed (no subscription needed)
    fill_timeout_s: float = 8.0      # how long to wait for an order to confirm a fill
    # front-month MNQ contract (operator-verified 2026-06-23: MNQU6 conId 793356225)
    contract_symbol: str = "MNQ"
    contract_expiry: str = "20260918"
    contract_exchange: str = "CME"
    contract_currency: str = "USD"


class IBKRClient:
    def __init__(self, cfg: IBKRConfig = IBKRConfig()):
        self.cfg = cfg
        self._connected = False
        self._ib = None              # ib_async.IB instance (PAPER_LIVE only)
        self._contract = None        # qualified Future (PAPER_LIVE only)
        load_env_file()   # pull repo-root .env into the environment if present
        p = cfg.env_prefix
        # env overrides config defaults when present
        self._host = os.environ.get(p + "HOST", cfg.host)
        self._port = int(os.environ.get(p + "PORT", cfg.port))
        self._client_id = int(os.environ.get(p + "CLIENT_ID", cfg.client_id))
        self._account = os.environ.get(p + "ACCOUNT")   # e.g. DU1234567 (paper)
        self.sent: list[dict] = []   # paper log of every order payload seen

    # -- safety predicates -------------------------------------------------
    @property
    def is_paper_account(self) -> bool:
        # IB paper accounts are prefixed "DU"; live are "U" (no "D"). Refuse non-paper.
        return bool(self._account) and self._account.upper().startswith("DU")

    @property
    def is_paper_port(self) -> bool:
        return self._port in PAPER_PORTS

    @property
    def has_credentials(self) -> bool:
        # "credentials" for IBKR = enough to reach a *paper* session safely.
        return self.is_paper_account and self.is_paper_port

    @property
    def mode(self) -> str:
        # DRY_RUN unless explicitly opted out AND a safe paper target is configured.
        return "PAPER_LIVE" if (not self.cfg.dry_run and self.has_credentials) else "DRY_RUN"

    def _assert_not_live_port(self) -> None:
        # Independent, non-removable guard: never proceed toward a live port.
        if self._port in LIVE_PORTS:
            raise ValueError(
                f"refusing IBKR live port {self._port}: this client is paper-only "
                f"(use a PAPER_PORT {PAPER_PORTS})")

    # -- client surface (mirrors TradovateClient) --------------------------
    def authenticate(self) -> dict:
        self._assert_not_live_port()
        if self.mode == "DRY_RUN":
            self._connected = False
            return {"ok": True, "mode": "DRY_RUN",
                    "note": "no socket; awaiting paper IBKR (IBKR_ACCOUNT=DU*, paper port) "
                            "+ explicit opt-in (dry_run=False)"}

        # PAPER_LIVE: real handshake against the running paper Gateway.
        from ib_async import IB, Future          # lazy import — keeps DRY_RUN clean
        ib = IB()
        ib.connect(self._host, self._port, clientId=self._client_id)
        ib.reqMarketDataType(self.cfg.market_data_type)   # 3 = delayed, free
        # Defensive cross-check: the connected session must manage our paper account.
        managed = ib.managedAccounts()
        if self._account not in managed:
            ib.disconnect()
            raise ValueError(
                f"connected session manages {managed}, not paper account {self._account!r}")
        fut = Future(symbol=self.cfg.contract_symbol,
                     lastTradeDateOrContractMonth=self.cfg.contract_expiry,
                     exchange=self.cfg.contract_exchange, currency=self.cfg.contract_currency)
        qualified = ib.qualifyContracts(fut)
        self._ib = ib
        self._contract = qualified[0] if qualified else fut
        self._connected = True
        return {"ok": True, "mode": "PAPER_LIVE", "account": self._account,
                "managed": managed, "contract": getattr(self._contract, "localSymbol", None),
                "conId": getattr(self._contract, "conId", None),
                "marketDataType": self.cfg.market_data_type}

    # -- order translation -------------------------------------------------
    @staticmethod
    def _ib_side(action: str) -> str:
        return "BUY" if action.lower() == "buy" else "SELL"

    def _build_ib_orders(self, payload: dict) -> list:
        """Translate an OSO payload (src/bridge/oso.py) into ib_async orders.
        Entry is Market; a bracket adds OCA-linked children — a take-profit (Limit)
        and/or a stop (Stop). The fade runner uses a STOP-ONLY bracket (no TP: the
        exit is signal-driven). A flatten payload (no bracket) is a lone Market."""
        from ib_async import MarketOrder, LimitOrder, StopOrder
        side = self._ib_side(payload["action"])
        qty = int(payload["orderQty"])
        parent = MarketOrder(side, qty)
        parent.orderId = self._ib.client.getReqId()
        parent.account = self._account
        br = payload.get("bracket")
        if not br:
            parent.transmit = True
            return [parent]

        tp, sl = br.get("takeProfit"), br.get("stopLoss")
        if not (tp or sl):
            parent.transmit = True
            return [parent]
        exit_side = self._ib_side((tp or sl)["action"])
        oca = f"oso-{parent.orderId}"
        parent.transmit = False
        children = []
        if tp:
            children.append(LimitOrder(exit_side, qty, tp["price"]))
        if sl:
            children.append(StopOrder(exit_side, qty, sl["stopPrice"]))
        for i, o in enumerate(children):
            o.orderId = self._ib.client.getReqId()
            o.parentId = parent.orderId
            o.account = self._account
            o.ocaGroup = oca; o.ocaType = 1
            o.transmit = (i == len(children) - 1)   # last leg transmits the whole set
        return [parent, *children]

    def place_order(self, payload: dict) -> dict:
        """Record + (DRY_RUN) simulate, or (PAPER_LIVE) submit a paper order.
        NEVER places a live/real-money order (guarded by mode + port + account)."""
        rec = {"seq": len(self.sent) + 1, "ts": time.time(), "mode": self.mode, "payload": payload}
        self.sent.append(rec)
        if self.mode == "DRY_RUN":
            return {"ok": True, "mode": "DRY_RUN", "orderId": f"SIM-{rec['seq']}",
                    "filled": True, "fill_price": None,   # simulated fill
                    "isAutomated": payload.get("isAutomated"), "payload": payload}

        # PAPER_LIVE — submit to the paper account only.
        self._assert_not_live_port()
        if not self.is_paper_account:
            raise ValueError(f"refusing non-paper account {self._account!r}")
        if self._ib is None or not self._connected:
            raise RuntimeError("not connected — call authenticate() first")
        orders = self._build_ib_orders(payload)
        trades = [self._ib.placeOrder(self._contract, o) for o in orders]
        # CONFIRM the fill — wait for the parent (entry/flatten) to actually execute.
        # An execution (parent.fills) is the truth; robust to the TIF-preset cancel/
        # resubmit churn (Error 10349). Returns filled=False if nothing executes, so the
        # bridge never assumes a position it doesn't hold.
        parent = trades[0]
        for _ in range(int(self.cfg.fill_timeout_s / 0.5)):
            self._ib.sleep(0.5)
            if parent.fills:
                break
        filled = bool(parent.fills)
        if filled:
            sh = sum(f.execution.shares for f in parent.fills)
            fill_price = sum(f.execution.shares * f.execution.price for f in parent.fills) / sh
        else:
            fill_price = None
        legs = [{"orderId": t.order.orderId, "action": t.order.action,
                 "qty": t.order.totalQuantity, "type": t.order.orderType,
                 "status": getattr(t.orderStatus, "status", None)} for t in trades]
        return {"ok": True, "mode": "PAPER_LIVE", "account": self._account,
                "filled": filled, "fill_price": fill_price,
                "orderId": parent.order.orderId, "legs": legs,
                "isAutomated": payload.get("isAutomated"), "payload": payload}

    def sync_request(self) -> dict:
        """Position/account sync. Stubbed in DRY_RUN; real read in PAPER_LIVE."""
        if self.mode == "DRY_RUN":
            return {"mode": "DRY_RUN", "positions": [], "account": self._account,
                    "note": "stub — no live socket"}
        if self._ib is None or not self._connected:
            raise RuntimeError("not connected — call authenticate() first")
        positions = [{"symbol": getattr(p.contract, "localSymbol", p.contract.symbol),
                      "conId": p.contract.conId, "position": p.position,
                      "avgCost": p.avgCost} for p in self._ib.positions(self._account)]
        summary = {row.tag: row.value for row in self._ib.accountSummary(self._account)}
        def _f(tag):
            try:
                return float(summary[tag])
            except (KeyError, ValueError, TypeError):
                return None
        return {"mode": "PAPER_LIVE", "account": self._account, "positions": positions,
                "NetLiquidation": _f("NetLiquidation"),
                "UnrealizedPnL": _f("UnrealizedPnL"),
                "RealizedPnL": _f("RealizedPnL")}

    def cancel_open_orders(self) -> dict:
        """Cancel resting orders on our contract (e.g. a protective stop before a
        signal-driven flatten). Stubbed in DRY_RUN."""
        if self.mode == "DRY_RUN":
            return {"mode": "DRY_RUN", "cancelled": 0, "note": "stub — no live socket"}
        if self._ib is None or not self._connected:
            raise RuntimeError("not connected — call authenticate() first")
        our_id = getattr(self._contract, "conId", None)
        n = 0
        for t in self._ib.openTrades():
            if getattr(t.contract, "conId", None) == our_id:
                self._ib.cancelOrder(t.order); n += 1
        self._ib.sleep(0)
        return {"mode": "PAPER_LIVE", "cancelled": n}

    def disconnect(self) -> None:
        if self._ib is not None and self._connected:
            self._ib.disconnect()
        self._connected = False
