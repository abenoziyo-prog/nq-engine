"""ib_fade_bridge — live paper runner for MEANREV_FADE_2M on IBKR paper.

Connects the VERIFIED fade engine (src/engine/meanrev_fade.py) to the IBKR paper
account. The engine is IMPORTED and called bar-by-bar — its signal logic is never
reimplemented here, so there is zero drift between this runner and the backtest
that produced the in-repo numbers.

Bar construction (must match src/data/resample.py exactly): IBKR 5-sec realtime
bars are aggregated into clock-aligned 2-min buckets (epoch %120), OHLC =
first-open / max-high / min-low / last-close. True high/low are preserved so the
engine's true-range ATR14 / EMA9 see exactly what the backtest saw — NOT a
close-to-close proxy.

Order flow (per completed 2-min bar):
  - engine ENTER_LONG -> risk-vetted entry MarketOrder + a protective disaster
    Stop at entry - STOP_ATR*atr (STOP_ATR=2.5). NO hard take-profit: the exit is
    signal-driven (the engine's reversion EXIT).
  - engine EXIT_LONG  -> cancel the resting stop + closing MarketOrder.

Safety: orders route through src/bridge/ibkr_client.py, which places PAPER orders
only (CLAUDE.md operator amendment 2026-06-23) — live ports/accounts are refused
and DRY_RUN is the default. Fills are tagged operator-external/paper. Paper P&L
flatters real P&L (optimistic fills + delayed data); this run validates that the
engine fires and the stop behaves, NOT the dollar numbers.

Usage:
  .venv/bin/python ib_fade_bridge.py              # paper live (needs Gateway + .env)
  .venv/bin/python ib_fade_bridge.py --dry-run    # offline replay, simulated fills
"""
from __future__ import annotations
import argparse
import csv
import os
import signal as _signal
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.engine.meanrev_fade import MeanRevFadeEngine, MeanRevConfig
from src.engine.v4 import _Ema, _Atr               # same verified indicator code
from src.bridge.ibkr_client import IBKRClient, IBKRConfig
from src.bridge.oso import round_tick, build_flatten
from src.risk.manager import RiskManager, AccountState, OrderProposal, Verdict

SYMBOL_LOCAL = "MNQU6"
CONTRACT_CONID = 793356225          # operator-verified 2026-06-23 (MNQ Sep 2026)
STOP_ATR_DEFAULT = 2.5
FRICTION_PTS = 1.0                  # matches the backtest harness
POINT_VALUE = 2.0                   # MNQ $/pt
FILL_TAG = "operator-external/paper"


class TwoMinAggregator:
    """Aggregate sub-2-min bars into clock-aligned 2-min bars (epoch %120),
    true OHLC. Emits a completed bar the moment a sub-bar of the NEXT bucket
    arrives (i.e. once the bucket is closed). Mirrors src/data/resample.py."""
    STEP = 120

    def __init__(self, on_close):
        self.on_close = on_close
        self.key = None
        self.o = self.h = self.l = self.c = None
        self.vol = 0

    def add(self, epoch: int, o: float, h: float, l: float, c: float, vol: int = 0) -> None:
        epoch = int(epoch)
        k = epoch - (epoch % self.STEP)
        if self.key is None:
            self._start(k, o, h, l, c, vol)
        elif k == self.key:
            self.h = max(self.h, h); self.l = min(self.l, l); self.c = c; self.vol += vol
        elif k > self.key:
            self._flush()
            self._start(k, o, h, l, c, vol)
        # k < self.key: stale/out-of-order sub-bar — ignore

    def _start(self, k, o, h, l, c, vol):
        self.key, self.o, self.h, self.l, self.c, self.vol = k, o, h, l, c, vol

    def _flush(self):
        if self.key is not None and self.o is not None:
            self.on_close(self.key, self.o, self.h, self.l, self.c, self.vol)

    def close_final(self) -> None:
        """Flush the last (in-progress) bucket — used at end of a finite replay."""
        self._flush()
        self.key = None


class FadeBridge:
    def __init__(self, dry_run: bool = True, stop_atr: float = STOP_ATR_DEFAULT,
                 simulate_stop: bool = True, route_risk: bool = True,
                 logdir: str = "logs", session_date: str | None = None):
        self.dry_run = dry_run
        self.stop_atr = stop_atr
        self.simulate_stop = simulate_stop      # DRY_RUN: model intrabar stop fills
        self.route_risk = route_risk            # send entries through the risk veto

        # live client targets the paper Gateway (port 4002, clientId 2); .env overrides.
        self.client = IBKRClient(IBKRConfig(dry_run=dry_run, port=4002, client_id=2))
        self.engine = MeanRevFadeEngine(MeanRevConfig())
        self.ema = _Ema(self.engine.cfg.ema_len)   # parallel trackers: same code, same
        self.atr = _Atr(self.engine.cfg.atr_len)   # bars -> identical to engine internals
        self.risk = RiskManager()
        self.acct = AccountState()

        self.position = 0
        self.qty = 0
        self.entry_price = None
        self.entry_ts = None
        self.stop_price = None
        self.bars_processed = 0
        self.trades: list[dict] = []
        self.agg = TwoMinAggregator(self.on_closed_bar)

        os.makedirs(logdir, exist_ok=True)
        d = session_date or datetime.now(timezone.utc).strftime("%Y%m%d")
        self.logpath = os.path.join(logdir, f"paper_session_{d}.log")
        self.logf = open(self.logpath, "a")
        self._log(f"START mode={'DRY_RUN' if dry_run else 'PAPER_LIVE-intent'} "
                  f"stop_atr={stop_atr} engine=MEANREV_FADE_2M symbol={SYMBOL_LOCAL}")

    # ---- logging ----
    def _log(self, msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        self.logf.write(line + "\n"); self.logf.flush()
        print(line)

    @staticmethod
    def _fmt(x):
        return f"{x:.2f}" if isinstance(x, (int, float)) else "—"

    # ---- core: one completed 2-min bar ----
    def on_closed_bar(self, key, o, h, l, c, vol=0) -> None:
        self.bars_processed += 1
        ema = self.ema.update(c)
        atr = self.atr.update(h, l, c)              # identical to engine's internal atr
        dist = (c - ema) / atr if (atr and atr > 0 and ema is not None) else None
        bar_ts = datetime.fromtimestamp(int(key), tz=timezone.utc)
        self._log(f"BAR ts={bar_ts.isoformat()} c={self._fmt(c)} ema9={self._fmt(ema)} "
                  f"atr={self._fmt(atr)} dist={self._fmt(dist)} pos={self.position}")

        # PAPER_LIVE: the broker holds the real protective stop; reconcile each bar
        # so a fired stop is reflected here (we can't see it intrabar).
        if not self.dry_run and self.position > 0:
            self._reconcile_broker(bar_ts)

        # DRY_RUN: model the protective stop firing intrabar (low pierces the stop).
        if (self.dry_run and self.simulate_stop and self.position > 0
                and self.stop_price is not None and l <= self.stop_price):
            self._exit(bar_ts, self.stop_price, "DISASTER_STOP")
            return

        dec = self.engine.on_bar(o, h, l, c)
        if dec is None:
            return
        sig = str(dec["signal"])
        if sig.endswith("ENTER_LONG") and self.position == 0:
            self._enter(bar_ts, dec["price"], atr)
        elif sig.endswith("EXIT_LONG") and self.position > 0:
            self._exit(bar_ts, dec["price"], "SIGNAL_REVERSION")

    # ---- order actions ----
    def _enter(self, ts, entry, atr) -> None:
        stop_dist = self.stop_atr * atr
        if self.route_risk:
            prop = OrderProposal(action="BUY", requested_qty=1, price=entry, atr=atr,
                                 stop_dist=stop_dist, daily_aligned=False)
            d = self.risk.evaluate(prop, self.acct)
            if d.verdict in (Verdict.REJECT, Verdict.HALT) or d.approved_qty <= 0:
                # Skip the trade; leave the engine state untouched (it will reset on
                # its own reversion exit). We simply place nothing.
                self._log(f"ENTER DROPPED verdict={d.verdict.value} reason={d.reason}")
                return
            qty, stop_price = d.approved_qty, round_tick(d.stop_price)
        else:
            qty, stop_price = 1, round_tick(entry - stop_dist)

        payload = {"accountSpec": self.client.cfg.account_spec, "symbol": SYMBOL_LOCAL,
                   "action": "Buy", "orderQty": qty, "orderType": "Market",
                   "isAutomated": True, "source": FILL_TAG,
                   "bracket": {"stopLoss": {"action": "Sell", "orderType": "Stop",
                                            "stopPrice": stop_price, "isAutomated": True}}}
        ack = self.client.place_order(payload)
        self.position = qty; self.qty = qty; self.entry_price = entry
        self.entry_ts = ts; self.stop_price = stop_price
        self.acct.open_position = qty
        self._log(f"FILL ENTER ({FILL_TAG}) qty={qty} entry={self._fmt(entry)} "
                  f"stop={self._fmt(stop_price)} stop_atr={self.stop_atr} "
                  f"atr={self._fmt(atr)} mode={ack['mode']} order={ack.get('orderId')}")

    def _exit(self, ts, exit_price, reason) -> None:
        broker_closed = reason.startswith("DISASTER_STOP")   # resting stop did the close
        if not broker_closed:
            self.client.cancel_open_orders()                 # cancel the resting stop
            ack = self.client.place_order(
                build_flatten(SYMBOL_LOCAL, self.position, account_spec=self.client.cfg.account_spec))
            mode = ack["mode"]
        else:
            mode = self.client.mode
        pnl_pts = (exit_price - self.entry_price) - FRICTION_PTS
        self.trades.append({"entry_ts": self.entry_ts, "entry": self.entry_price,
                            "exit_ts": ts, "exit": exit_price, "qty": self.position,
                            "pnl_pts": pnl_pts, "reason": reason})
        dollars = pnl_pts * self.position * POINT_VALUE
        self.acct.realized_pnl_session += dollars
        self.acct.realized_pnl_total += dollars
        self.acct.high_water = max(self.acct.high_water, self.acct.realized_pnl_total)
        self._log(f"FILL EXIT ({FILL_TAG}) reason={reason} exit={self._fmt(exit_price)} "
                  f"pnl_pts={pnl_pts:+.2f} (${dollars:+.0f}) qty={self.position} mode={mode}")
        self.position = 0; self.qty = 0; self.entry_price = None
        self.entry_ts = None; self.stop_price = None
        self.acct.open_position = 0

    def _reconcile_broker(self, ts) -> None:
        try:
            sync = self.client.sync_request()
        except Exception as e:                       # never let a sync error kill the loop
            self._log(f"RECONCILE error: {e}")
            return
        bpos = sum(p.get("position", 0) for p in sync.get("positions", [])
                   if p.get("conId") == CONTRACT_CONID)
        if bpos == 0 and self.position > 0:
            self._log("RECONCILE broker flat while bridge long -> protective stop fired")
            self._exit(ts, self.stop_price, "DISASTER_STOP_BROKER")

    # ---- warmup (indicator-only; no phantom positions) ----
    def warm(self, bars) -> None:
        n = 0
        last_atr = None
        for o, h, l, c in bars:
            self.engine._ema.update(c); self.engine._atr.update(h, l, c)
            self.ema.update(c); last_atr = self.atr.update(h, l, c)
            n += 1
        self._log(f"WARMUP fed {n} historical bars (indicator-only); atr={self._fmt(last_atr)}")

    # ---- runners ----
    def run_live(self) -> None:
        if self.client.mode != "PAPER_LIVE":
            raise SystemExit(
                "client is not in PAPER_LIVE mode — set IBKR_ACCOUNT=DU* on a paper "
                "port (4002) in .env and run without --dry-run, or use --dry-run.")
        res = self.client.authenticate()
        self._log(f"CONNECT {res}")
        ib, contract = self.client._ib, self.client._contract
        try:
            hist = ib.reqHistoricalData(contract, endDateTime="", durationStr="7200 S",
                                        barSizeSetting="2 mins", whatToShow="TRADES",
                                        useRTH=False)
            self.warm([(b.open, b.high, b.low, b.close) for b in hist])
        except Exception as e:
            self._log(f"WARMUP skipped (no historical): {e}")
        bars = ib.reqRealTimeBars(contract, 5, "TRADES", useRTH=False)
        bars.updateEvent += self._on_rt_bar
        self._log("LIVE reqRealTimeBars(5s) -> 2m aggregation. Ctrl-C to stop.")
        ib.run()

    def _on_rt_bar(self, bars, hasNewBar) -> None:
        if not hasNewBar:
            return
        b = bars[-1]
        self.agg.add(int(b.time.timestamp()), b.open_, b.high, b.low, b.close, b.volume)

    def run_dry(self, replay_path: str, last_bars: int = 3000) -> None:
        self._log(f"DRY_RUN replay {replay_path} (sub-bars -> 2m aggregation)")
        with open(replay_path, newline="") as f:
            rows = list(csv.DictReader(f))
        if last_bars and len(rows) > last_bars:
            rows = rows[-last_bars:]
        for r in rows:
            self.agg.add(int(r["time"]), float(r["open"]), float(r["high"]),
                         float(r["low"]), float(r["close"]), int(r.get("volume", 0) or 0))
        self.agg.close_final()
        self._log(f"DRY_RUN replay complete ({len(rows)} sub-bars)")

    # ---- shutdown ----
    def shutdown(self) -> None:
        self._log("SHUTDOWN initiated")
        if self.position > 0:
            try:
                self.client.cancel_open_orders()
                ack = self.client.place_order(
                    build_flatten(SYMBOL_LOCAL, self.position,
                                  account_spec=self.client.cfg.account_spec))
                self._log(f"SHUTDOWN flatten qty={self.position} mode={ack['mode']}")
            except Exception as e:
                self._log(f"SHUTDOWN flatten error: {e}")
            self.position = 0
        self._write_summary()
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.logf.close()

    def _write_summary(self) -> None:
        n = len(self.trades)
        total_pts = sum(t["pnl_pts"] * t["qty"] for t in self.trades)
        wins = sum(1 for t in self.trades if t["pnl_pts"] > 0)
        by_reason = {}
        for t in self.trades:
            by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
        self._log("==== SESSION SUMMARY ====")
        self._log(f"bars_processed={self.bars_processed} trades={n} "
                  f"wins={wins} total_pts={total_pts:+.2f} "
                  f"est_$={total_pts * POINT_VALUE:+.0f} (PAPER, fills flatter real)")
        self._log(f"exit_reasons={by_reason}")
        self._log(f"log={self.logpath}")


def main():
    ap = argparse.ArgumentParser(description="MEANREV_FADE_2M live paper runner (IBKR)")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline replay with simulated fills (no Gateway)")
    ap.add_argument("--stop-atr", type=float, default=STOP_ATR_DEFAULT)
    ap.add_argument("--replay", default="src/data/MNQ_1m_12mo_databento.csv",
                    help="DRY_RUN: sub-2min bar CSV to replay (aggregated to 2m)")
    ap.add_argument("--bars", type=int, default=3000, help="DRY_RUN: replay last N sub-bars")
    args = ap.parse_args()

    bridge = FadeBridge(dry_run=args.dry_run, stop_atr=args.stop_atr)
    _signal.signal(_signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.dry_run:
            bridge.run_dry(args.replay, args.bars)
        else:
            bridge.run_live()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.shutdown()


if __name__ == "__main__":
    main()
