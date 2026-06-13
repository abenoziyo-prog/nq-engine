"""Risk manager — the veto layer between signal and broker.

Every order proposal passes through here. It can downsize, reject, or halt.
Encodes the $50K/$2K prop constraints and the V4 sizing/stop rules.
This layer NEVER relaxes a limit because the signal is confident — limits are hard.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    DOWNSIZE = "DOWNSIZE"
    REJECT = "REJECT"
    HALT = "HALT"          # account-level stop; no further entries this session


@dataclass
class RiskConfig:
    instrument: str = "MNQ"           # MNQ = $2/pt; NQ = $20/pt
    point_value: float = 2.0
    account_size: float = 50_000.0
    trailing_dd: float = 2_000.0      # firm trailing drawdown
    max_risk_per_trade: float = 200.0 # $ ceiling per trade (10% of DD)
    max_contracts: int = 3
    base_contracts: int = 1
    add_buffer_usd: float = 400.0     # banked profit required before sizing up
    catastrophe_atr_mult: float = 4.0
    daily_loss_halt: float = 600.0    # halt entries if day's realized loss exceeds this (30% DD)


@dataclass
class AccountState:
    """Updated from broker fills/positions; the source of truth for risk decisions."""
    realized_pnl_session: float = 0.0     # $ this session
    realized_pnl_total: float = 0.0       # $ since account start (for trailing high-water)
    high_water: float = 0.0               # peak total equity seen
    open_position: int = 0                # signed contracts currently held
    halted: bool = False

    @property
    def trailing_drawdown_room(self) -> float:
        """$ remaining before the trailing DD is breached."""
        equity = self.realized_pnl_total
        return (self.high_water - equity)  # how far below peak we are


@dataclass
class OrderProposal:
    action: str           # "BUY" / "SELL" / "FLAT"
    requested_qty: int
    price: float
    atr: float
    stop_dist: float      # points (from signal: 4*ATR)
    daily_aligned: bool


@dataclass
class RiskDecision:
    verdict: Verdict
    approved_qty: int
    stop_price: float
    reason: str


class RiskManager:
    def __init__(self, cfg: RiskConfig = RiskConfig()):
        self.cfg = cfg

    def evaluate(self, prop: OrderProposal, acct: AccountState) -> RiskDecision:
        c = self.cfg

        # 0. hard halt states
        if acct.halted:
            return RiskDecision(Verdict.REJECT, 0, 0.0, "account halted this session")

        # exits always allowed (closing risk is good risk)
        if prop.action == "FLAT":
            return RiskDecision(Verdict.ALLOW, abs(acct.open_position), 0.0, "flatten")

        # 1. trailing drawdown proximity — halt new entries if too close to breach
        room = c.trailing_dd - acct.trailing_drawdown_room
        if room <= c.max_risk_per_trade:
            return RiskDecision(Verdict.HALT, 0, 0.0,
                f"trailing DD room ${room:.0f} <= per-trade risk ${c.max_risk_per_trade:.0f}; halt entries")

        # 2. session loss halt
        if acct.realized_pnl_session <= -c.daily_loss_halt:
            return RiskDecision(Verdict.HALT, 0, 0.0,
                f"session loss ${acct.realized_pnl_session:.0f} hit halt threshold")

        # 3. determine sizing tier
        qty = c.base_contracts
        if prop.daily_aligned and acct.realized_pnl_session >= c.add_buffer_usd:
            qty = min(prop.requested_qty, c.base_contracts + 1)  # +1 only with buffer
        qty = min(qty, c.max_contracts)

        # 4. per-trade risk ceiling — shrink qty until catastrophe stop fits the $ ceiling
        stop_risk_per_contract = prop.stop_dist * c.point_value
        if stop_risk_per_contract <= 0:
            return RiskDecision(Verdict.REJECT, 0, 0.0, "invalid stop distance")
        max_qty_by_risk = int(c.max_risk_per_trade // stop_risk_per_contract)
        if max_qty_by_risk < 1:
            return RiskDecision(Verdict.REJECT, 0, 0.0,
                f"one contract risk ${stop_risk_per_contract:.0f} exceeds ceiling ${c.max_risk_per_trade:.0f}")

        final_qty = min(qty, max_qty_by_risk)
        verdict = Verdict.ALLOW if final_qty == qty else Verdict.DOWNSIZE

        side = 1 if prop.action == "BUY" else -1
        stop_price = prop.price - side * prop.stop_dist

        reason = (f"qty {final_qty} (tier {qty}, risk-cap {max_qty_by_risk}); "
                  f"stop {stop_price:.2f} risks ${stop_risk_per_contract*final_qty:.0f}")
        return RiskDecision(verdict, final_qty, stop_price, reason)
