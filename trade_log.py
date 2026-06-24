"""Authoritative trade log — reads IB's OWN execution record (not the bridge log,
which can under-record forced flattens). Pairs fills into flat-to-flat round-trips
with P&L, labels each with its strategy (matched from the bridge log), prints a
ledger, and (re)writes TRADES.md — a clean markdown log that auto-refreshes on each
run. Read-only on the broker; safe while the book is live (separate clientId).

Run: .venv/bin/python trade_log.py
"""
import glob
import os
from datetime import datetime, timezone

from ib_async import IB

POINT_VALUE = 2.0   # MNQ $/pt
REPO = os.path.dirname(os.path.abspath(__file__))


def bridge_entries():
    """(datetime, side, strategy) for every 'FILL ENTER' the bridge logged, across
    all multi_engine session logs — used to label broker round-trips by strategy."""
    out = []
    for path in glob.glob(os.path.join(REPO, "logs", "multi_engine_session_*.log")):
        with open(path) as f:
            for line in f:
                if "FILL ENTER " not in line:
                    continue
                try:
                    ts = datetime.fromisoformat(line.split(" ", 1)[0])
                    parts = line.split("FILL ENTER ", 1)[1].split()
                    side, strat = parts[0], parts[1]      # "LONG"/"SHORT", strategy id
                    out.append((ts, side, strat))
                except (ValueError, IndexError):
                    continue
    return out


def label(trip, entries):
    want = trip["side"]
    best, bestdt = "(manual/external)", 1e9
    for ts, side, strat in entries:
        if side != want:
            continue
        dt = abs((ts - trip["etime"]).total_seconds())
        if dt < 180 and dt < bestdt:        # same side, entry within 3 min
            best, bestdt = strat, dt
    return best


def write_md(acct, nl, trips, op, path):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# NQ Engine — Paper Trade Log",
        "",
        f"Account **{acct}** (IBKR paper) · MNQU6 (MNQ Sep 2026) · $2/pt · "
        f"NetLiq ${nl}  ",
        f"Source: IB broker execution record (authoritative), via `trade_log.py`.  ",
        f"_Updated {now}. Paper P&L flatters real (optimistic fills + delayed data)._",
        "",
        "## Closed trades",
        "| # | Entry (UTC) | Exit (UTC) | Strategy | Side | Entry | Exit | Pts | $ | Held |",
        "|--:|---|---|---|---|--:|--:|--:|--:|---|",
    ]
    tot = 0.0
    for i, t in enumerate(trips, 1):
        usd = t["pts"] * t["qty"] * POINT_VALUE
        tot += usd
        lines.append(
            f"| {i} | {t['etime']:%Y-%m-%d %H:%M} | {t['xtime']:%H:%M} | {t['strategy']} | "
            f"{t['side']} | {t['epx']:.2f} | {t['xpx']:.2f} | {t['pts']:+.2f} | {usd:+.0f} | "
            f"{str(t['xtime'] - t['etime']).split('.')[0]} |")
    lines += ["", f"**Total closed: {tot:+.0f} USD (paper) · {len(trips)} round-trips**", ""]
    lines.append("## Open positions")
    lines.append(f"- OPEN {op['side']} {op['qty']:g} @ {op['epx']:.2f} (entry {op['etime']:%H:%M})"
                 if op else "_(none — flat)_")
    lines += [
        "",
        "## Armed engines (potential upcoming)",
        "16 live: 9 long + 7 short mirrors (UNTESTED), across 2m/5m/15m. They fire only on "
        "their conditions (fade ≥3-ATR stretch; EMA_PROX proximity+accel; LVL NY-session "
        "zone tap). SHOCK_V1 disabled (no volume feed). See STRATEGY_VAULT.md for specs.",
        "",
        "---",
        "_Regenerate: `.venv/bin/python trade_log.py` (refreshes this file). "
        "Drive copy refreshed on request._",
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    ib = IB()
    try:
        ib.connect("127.0.0.1", 4002, clientId=20, timeout=15)
        acct = ib.managedAccounts()[0]
        nl = {r.tag: r.value for r in ib.accountSummary(acct)}.get("NetLiquidation")
        ib.sleep(1)
        fills = sorted(ib.fills(), key=lambda f: f.execution.time)
        entries = bridge_entries()

        pos, op, trips = 0.0, None, []
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
                op.update(xtime=e.time, xpx=e.price, pts=pts)
                op["strategy"] = label(op, entries)
                trips.append(op); op = None

        print(f"account {acct}  NetLiq ${nl}  | {len(trips)} closed round-trips")
        for i, t in enumerate(trips, 1):
            usd = t["pts"] * t["qty"] * POINT_VALUE
            print(f"  {i} {t['side']:5} {t['strategy']:24} {t['epx']:.2f}->{t['xpx']:.2f} "
                  f"{t['pts']:+.2f}pt {usd:+.0f}$")
        if op:
            print(f"  * OPEN {op['side']} {op['qty']:g} @ {op['epx']:.2f}")

        md = os.path.join(REPO, "TRADES.md")
        write_md(acct, nl, trips, op, md)
        print(f"wrote {md}")
        ib.disconnect()
    except Exception as e:
        print("trade_log error:", type(e).__name__, e)
        try:
            ib.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
