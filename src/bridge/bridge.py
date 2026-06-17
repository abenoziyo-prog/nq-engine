"""T14 — bridge receiver: signal -> risk manager -> OSO bracket -> client.

The single chokepoint between a strategy signal (internal or TradingView webhook)
and the broker. Every signal passes through the risk manager (the $50K/$2K veto
layer); only ALLOW/DOWNSIZE with qty>0 produces an order, which is built as an
isAutomated OSO bracket and handed to the Tradovate client. The client is DRY_RUN
by default, so this places NO live orders — it logs the paper order and returns a
simulated ack. FLAT signals always flatten (closing risk is allowed even when halted).
"""
from __future__ import annotations
from dataclasses import dataclass

from src.risk.manager import (RiskManager, AccountState, OrderProposal, Verdict)
from src.bridge.oso import build_oso, build_flatten
from src.bridge.tradovate_client import TradovateClient


@dataclass
class Signal:
    strategy: str
    action: str               # "BUY" / "SELL" / "FLAT"
    symbol: str
    price: float
    atr: float = 0.0
    stop_dist: float = 0.0    # points (from the strategy, e.g. structural / 4*ATR)
    requested_qty: int = 1
    daily_aligned: bool = False
    target_R: float = 2.0     # take-profit at entry + target_R * risk


class Bridge:
    def __init__(self, risk: RiskManager | None = None, client: TradovateClient | None = None):
        self.risk = risk or RiskManager()
        self.client = client or TradovateClient()
        self.client.authenticate()
        self.log: list[dict] = []

    def on_signal(self, sig: Signal, acct: AccountState) -> dict:
        # FLAT: bypass sizing — flatten existing position (risk mgr allows even when halted)
        if sig.action == "FLAT":
            if acct.open_position == 0:
                rec = {"strategy": sig.strategy, "verdict": "ALLOW", "action": "NOOP", "reason": "flat: no position"}
                self.log.append(rec); return rec
            order = build_flatten(sig.symbol, acct.open_position, account_spec=self.client.cfg.account_spec)
            ack = self.client.place_order(order)
            rec = {"strategy": sig.strategy, "verdict": "ALLOW", "action": "FLATTEN(paper)", "order": order, "ack": ack}
            self.log.append(rec); return rec

        prop = OrderProposal(action=sig.action, requested_qty=sig.requested_qty, price=sig.price,
                             atr=sig.atr, stop_dist=sig.stop_dist, daily_aligned=sig.daily_aligned)
        d = self.risk.evaluate(prop, acct)
        rec = {"strategy": sig.strategy, "verdict": d.verdict.value, "approved_qty": d.approved_qty,
               "reason": d.reason}

        if d.verdict in (Verdict.REJECT, Verdict.HALT) or d.approved_qty <= 0:
            rec["action"] = "DROPPED"
            self.log.append(rec); return rec

        side = "Buy" if sig.action == "BUY" else "Sell"
        entry, stop = sig.price, d.stop_price
        risk_pts = abs(entry - stop)
        target = entry + sig.target_R * risk_pts if side == "Buy" else entry - sig.target_R * risk_pts
        order = build_oso(sig.symbol, side, d.approved_qty, entry, stop, target,
                          account_spec=self.client.cfg.account_spec)
        ack = self.client.place_order(order)
        rec["action"] = "SUBMITTED(paper)" if ack.get("mode") == "DRY_RUN" else "SUBMITTED"
        rec["order"] = order; rec["ack"] = ack
        self.log.append(rec); return rec
