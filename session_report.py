"""End-of-session report — runs at each trading-session end (or on demand).

Pulls IB's OWN fills (authoritative), pairs round-trips, labels each by strategy and
compares the bridge's SIGNAL price to the actual broker FILL (delayed-data slippage).
Emits per-engine P&L, slippage stats, auto-findings, and improvement flags, and writes
reports/session_<date>.md. The qualitative narrative is added by the operator/agent on top.

Run: .venv/bin/python session_report.py
"""
import glob
import os
import re
from datetime import datetime, timezone

from ib_async import IB

PV = 2.0
REPO = os.path.dirname(os.path.abspath(__file__))


def bridge_enters():
    """[(dt, side, strategy, signal_px)] from every bridge 'FILL ENTER' line today."""
    out = []
    for path in glob.glob(os.path.join(REPO, "logs", "multi_engine_session_*.log")):
        for line in open(path):
            if "FILL ENTER " not in line:
                continue
            m = re.search(r"FILL ENTER (LONG|SHORT) (\S+).*entry=([0-9.]+)", line)
            if m:
                try:
                    out.append((datetime.fromisoformat(line.split(" ", 1)[0]),
                                m.group(1), m.group(2), float(m.group(3))))
                except ValueError:
                    pass
    return out


def match(trip, enters):
    best, bestdt = None, 1e9
    for dt, side, strat, px in enters:
        if side != trip["side"]:
            continue
        d = abs((dt - trip["etime"]).total_seconds())
        if d < 180 and d < bestdt:
            best, bestdt = (strat, px), d
    return best or ("(manual/external)", None)


def main():
    ib = IB()
    try:
        ib.connect("127.0.0.1", 4002, clientId=21, timeout=15)
        acct = ib.managedAccounts()[0]
        nl = {r.tag: r.value for r in ib.accountSummary(acct)}.get("NetLiquidation")
        ib.sleep(1)
        fills = sorted(ib.fills(), key=lambda f: f.execution.time)
        enters = bridge_enters()

        pos, op, trips = 0.0, None, []
        for f in fills:
            e = f.execution
            prev = pos
            pos += e.shares if e.side == "BOT" else -e.shares
            if prev == 0 and pos != 0:
                op = {"side": "LONG" if pos > 0 else "SHORT", "etime": e.time, "epx": e.price,
                      "qty": abs(pos)}
            elif prev != 0 and pos == 0 and op:
                op["pts"] = (e.price - op["epx"]) if op["side"] == "LONG" else (op["epx"] - e.price)
                op["xpx"], op["xtime"] = e.price, e.time
                strat, sigpx = match(op, enters)
                op["strategy"], op["sig"] = strat, sigpx
                # entry slippage vs the delayed signal price (worse fill = positive cost)
                op["slip"] = (op["epx"] - sigpx) if (sigpx and op["side"] == "LONG") else \
                             (sigpx - op["epx"]) if sigpx else None
                trips.append(op); op = None

        # aggregates
        by_eng, slips = {}, []
        for t in trips:
            by_eng.setdefault(t["strategy"], []).append(t["pts"] * t["qty"] * PV)
            if t["slip"] is not None:
                slips.append(abs(t["slip"]))
        total = sum(t["pts"] * t["qty"] * PV for t in trips)
        shorts = [t for t in trips if "SHORT" in t["strategy"]]
        short_pnl = sum(t["pts"] * t["qty"] * PV for t in shorts)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        L = [f"# Trading session report — {date}", "",
             f"Account **{acct}** · NetLiq ${nl} · {len(trips)} round-trips · "
             f"**P&L {total:+.0f} USD (paper, broker truth)**", "",
             "## Trades", "| # | Strategy | Side | Sig→Fill (slip) | Entry→Exit | $ |",
             "|--:|---|---|---|---|--:|"]
        for i, t in enumerate(trips, 1):
            usd = t["pts"] * t["qty"] * PV
            slip = f"{t['sig']:.0f}→{t['epx']:.0f} ({t['slip']:+.0f})" if t["sig"] else "—"
            L.append(f"| {i} | {t['strategy']} | {t['side']} | {slip} | "
                     f"{t['epx']:.2f}→{t['xpx']:.2f} | {usd:+.0f} |")
        L += ["", "## Per-engine P&L"]
        for eng, ps in sorted(by_eng.items(), key=lambda kv: sum(kv[1])):
            L.append(f"- {eng}: {sum(ps):+.0f} USD ({len(ps)} trades)")
        avg_slip = (sum(slips) / len(slips)) if slips else 0
        L += ["", "## Findings (auto)",
              f"- Delayed-data entry slippage: avg **{avg_slip:.0f} pt**, "
              f"max **{max(slips) if slips else 0:.0f} pt** — signal price vs actual fill.",
              f"- Short mirrors: {short_pnl:+.0f} USD over {len(shorts)} trades "
              f"({'bleeding as backtested' if short_pnl < 0 else 'positive (small n)'}).",
              f"- Biggest single trade: "
              f"{max(trips, key=lambda t: abs(t['pts']))['strategy']} "
              f"{max((t['pts']*t['qty']*PV for t in trips), key=abs):+.0f} USD.",
              "", "## Areas for improvement (flags)",
              "- [ ] Live data feed — decisions + P&L are on ~15-min-delayed prices "
              f"(avg {avg_slip:.0f} pt slippage). Biggest lever on signal quality.",
              "- [ ] Short mirrors forward-confirming as losers — candidate to demote." if short_pnl < 0 else "",
              "- [ ] Reliable uptime (cloud/IBC) so sessions don't die with the laptop.",
              "", "## Narrative (operator/agent)", "_…add regime read + decisions here._", ""]

        os.makedirs(os.path.join(REPO, "reports"), exist_ok=True)
        path = os.path.join(REPO, "reports", f"session_{date}.md")
        open(path, "w").write("\n".join(x for x in L if x is not None))
        print("\n".join(x for x in L if x is not None))
        print(f"\nwrote {path}")
        ib.disconnect()
    except Exception as e:
        print("session_report error:", type(e).__name__, e)
        try:
            ib.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
