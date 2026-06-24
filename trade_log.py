"""Authoritative trade log — reads IB's OWN execution record (not the bridge log,
which can under-record forced flattens). Pairs fills into flat-to-flat round-trips
with P&L. Read-only; safe to run while the book is live (uses a separate clientId).

Run: .venv/bin/python trade_log.py
"""
from ib_async import IB

POINT_VALUE = 2.0   # MNQ $/pt

ib = IB()
try:
    ib.connect("127.0.0.1", 4002, clientId=20, timeout=15)
    acct = ib.managedAccounts()[0]
    nl = {r.tag: r.value for r in ib.accountSummary(acct)}.get("NetLiquidation")
    ib.sleep(1)
    fills = sorted(ib.fills(), key=lambda f: f.execution.time)

    print(f"account {acct}  NetLiquidation ${nl}")
    print(f"raw fills this session: {len(fills)}")
    for f in fills:
        e = f.execution
        print(f"  {e.time:%H:%M:%S}  {e.side} {e.shares:g} {f.contract.localSymbol} @ {e.price}")

    # pair flat-to-flat round-trips
    pos = 0.0
    op = None
    trips = []
    for f in fills:
        e = f.execution
        signed = e.shares if e.side == "BOT" else -e.shares
        prev = pos
        pos += signed
        if prev == 0 and pos != 0:
            op = {"side": "LONG" if pos > 0 else "SHORT", "etime": e.time,
                  "epx": e.price, "qty": abs(pos), "sym": f.contract.localSymbol}
        elif prev != 0 and pos == 0 and op:
            pts = (e.price - op["epx"]) if op["side"] == "LONG" else (op["epx"] - e.price)
            trips.append({**op, "xtime": e.time, "xpx": e.price, "pts": pts})
            op = None

    print(f"\n==== ROUND-TRIPS ({len(trips)} closed) ====")
    print(f"{'#':>2} {'side':5} {'sym':7} {'entry':>9} {'exit':>9} {'pts':>7} {'$':>7}  held")
    tot = 0.0
    for i, t in enumerate(trips, 1):
        held = t["xtime"] - t["etime"]
        usd = t["pts"] * t["qty"] * POINT_VALUE
        tot += usd
        print(f"{i:>2} {t['side']:5} {t['sym']:7} {t['epx']:>9.2f} {t['xpx']:>9.2f} "
              f"{t['pts']:>+7.2f} {usd:>+7.0f}  {str(held).split('.')[0]}")
    if op:
        print(f" * OPEN {op['side']} {op['qty']:g} {op['sym']} @ {op['epx']:.2f} (not yet closed)")
    print(f"\nclosed round-trips P&L: {tot:+.0f} USD (paper; broker fills — incl. any manual test orders)")
    ib.disconnect()
except Exception as e:
    print("trade_log error:", type(e).__name__, e)
    try:
        ib.disconnect()
    except Exception:
        pass
