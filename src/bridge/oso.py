"""T13 — OSO bracket builder (isAutomated:true).

Constructs a Tradovate-style entry order with a linked protective bracket
(stop-loss + take-profit, OCO). Pure construction — no I/O, fully testable.
Every order carries isAutomated:true (required for automated routing). Prices are
rounded to the NQ/MNQ tick (0.25). Geometry is validated so a long can't be built
with the stop above entry or target below it (and mirror for shorts).
"""
from __future__ import annotations

TICK = 0.25


def round_tick(px: float) -> float:
    return round(round(px / TICK) * TICK, 2)


def build_oso(symbol: str, side: str, qty: int, entry_price: float,
              stop_price: float, target_price: float, *,
              account_spec: str = "DEMO", entry_type: str = "Market") -> dict:
    if side not in ("Buy", "Sell"):
        raise ValueError(f"side must be Buy/Sell, got {side!r}")
    if qty <= 0:
        raise ValueError(f"qty must be > 0, got {qty}")
    e, s, t = round_tick(entry_price), round_tick(stop_price), round_tick(target_price)
    if side == "Buy":
        if not (s < e < t):
            raise ValueError(f"long bracket geometry invalid: need stop {s} < entry {e} < target {t}")
        exit_action = "Sell"
    else:
        if not (t < e < s):
            raise ValueError(f"short bracket geometry invalid: need target {t} < entry {e} < stop {s}")
        exit_action = "Buy"
    return {
        "accountSpec": account_spec,
        "symbol": symbol,
        "action": side,
        "orderQty": int(qty),
        "orderType": entry_type,
        "isAutomated": True,
        "bracket": {
            "stopLoss": {"action": exit_action, "orderType": "Stop", "stopPrice": s, "isAutomated": True},
            "takeProfit": {"action": exit_action, "orderType": "Limit", "price": t, "isAutomated": True},
            "oco": True,
        },
        "risk_pts": round(abs(e - s), 2),
        "reward_pts": round(abs(t - e), 2),
    }


def build_flatten(symbol: str, open_position: int, *, account_spec: str = "DEMO") -> dict:
    """Market order to flatten an existing position (closing risk is always allowed)."""
    if open_position == 0:
        raise ValueError("no position to flatten")
    return {
        "accountSpec": account_spec,
        "symbol": symbol,
        "action": "Sell" if open_position > 0 else "Buy",
        "orderQty": abs(int(open_position)),
        "orderType": "Market",
        "isAutomated": True,
        "reason": "flatten",
    }
