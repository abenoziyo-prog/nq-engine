"""Read-only IBKR paper account check (T18). No orders — observe only.

Run after ib_test.py to confirm the paper account is healthy before starting the
bridge. Connects on clientId=3 (see START_IBKR.md reference table).
"""
from ib_async import IB

HOST, PORT, CLIENT_ID = "127.0.0.1", 4002, 3   # paper Gateway

ib = IB()
ib.connect(HOST, PORT, clientId=CLIENT_ID)
ib.reqMarketDataType(3)   # delayed; no subscription needed

accounts = ib.managedAccounts()
print("managedAccounts:", accounts)
acct = accounts[0] if accounts else None

summary = {row.tag: row.value for row in ib.accountSummary(acct)}
for tag in ("NetLiquidation", "AvailableFunds", "BuyingPower",
            "UnrealizedPnL", "RealizedPnL"):
    print(f"  {tag:16} {summary.get(tag)}")

positions = ib.positions(acct)
if not positions:
    print("positions: FLAT")
else:
    for p in positions:
        sym = getattr(p.contract, "localSymbol", p.contract.symbol)
        print(f"  {sym}: {p.position} @ avgCost {p.avgCost}")

ib.disconnect()
print("done.")
