"""multi_engine_bridge — paper forward-test runner for the full top-10 book.

Per CLAUDE.md amendment 2026-06-23 (paper-only, promotion-path/$2K gates waived):
runs every ENABLED registry engine concurrently on IBKR paper, each on its own
timeframe, each fill tagged with the engine id + gate_status so forward data is
never mistaken for validated edge.

Feed: one delayed reqMktData poll (type 3) -> 1-min bars -> fanned into per-engine
timeframe aggregators (2m/5m/15m), true OHLC (epoch-aligned, matches resample.py).
Engines are STOPLESS at the order layer (entry MarketOrder, exit on the engine's own
signal — V4 catastrophe stop disabled per vault config; LVL exits are engine-internal
structural/trail stops surfaced as EXIT signals).

Positions are tracked per engine and netted (`net` exposure logged on every fill).
True position-netting into single broker orders is a capital-gate prerequisite and
NOT done here — on paper, per-engine tagged orders are kept so each engine's P&L is
attributable. SHOCK_V1 is registered-but-disabled (no volume on the delayed feed).

Usage:
  .venv/bin/python multi_engine_bridge.py --dry-run   # offline 1m replay, sim fills
  .venv/bin/python multi_engine_bridge.py             # paper live (Gateway + .env)
"""
from __future__ import annotations
import argparse
import csv
import os
import signal as _signal
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.bridge.ibkr_client import IBKRClient, IBKRConfig
from src.bridge.oso import build_flatten
from src.bridge.engine_registry import enabled_specs

SYMBOL_LOCAL = "MNQU6"
FRICTION_PTS = 1.0
POINT_VALUE = 2.0
FILL_TAG = "operator-external/paper"


class BarAggregator:
    """Aggregate sub-bars into clock-aligned bars of `step_s` seconds (true OHLC,
    epoch %step). Emits a completed bar when a sub-bar of the next bucket arrives."""
    def __init__(self, step_s: int, on_close):
        self.step = step_s; self.on_close = on_close
        self.key = None; self.o = self.h = self.l = self.c = None; self.vol = 0

    def add(self, epoch, o, h, l, c, vol=0):
        k = int(epoch) - (int(epoch) % self.step)
        if self.key is None:
            self._start(k, o, h, l, c, vol)
        elif k == self.key:
            self.h = max(self.h, h); self.l = min(self.l, l); self.c = c; self.vol += vol
        elif k > self.key:
            self._flush(); self._start(k, o, h, l, c, vol)

    def _start(self, k, o, h, l, c, vol):
        self.key, self.o, self.h, self.l, self.c, self.vol = k, o, h, l, c, vol

    def _flush(self):
        if self.key is not None and self.o is not None:
            self.on_close(self.key, self.o, self.h, self.l, self.c, self.vol)

    def close_final(self):
        self._flush(); self.key = None


class MultiEngineBridge:
    def __init__(self, dry_run: bool = True, specs=None, logdir: str = "logs",
                 session_date: str | None = None):
        self.dry_run = dry_run
        self.client = IBKRClient(IBKRConfig(dry_run=dry_run, port=4002, client_id=3))
        self.specs = specs if specs is not None else enabled_specs()
        self.states = []            # per-engine: dict(spec, engine, pos, entry, entry_ts)
        self.by_tf: dict[int, list] = {}
        for s in self.specs:
            st = {"spec": s, "engine": s.make(), "pos": 0, "entry": None, "entry_ts": None}
            self.states.append(st)
            self.by_tf.setdefault(s.tf_min, []).append(st)
        # one aggregator per distinct timeframe (bind tf via default arg)
        self.aggs = {tf: BarAggregator(tf * 60,
                     lambda k, o, h, l, c, v, _tf=tf: self._on_tf_close(_tf, k, o, h, l, c, v))
                     for tf in self.by_tf}
        self.net = 0
        self.bars_seen = 0
        self.trades = []
        self.warming = False

        os.makedirs(logdir, exist_ok=True)
        d = session_date or datetime.now(timezone.utc).strftime("%Y%m%d")
        self.logpath = os.path.join(logdir, f"multi_engine_session_{d}.log")
        self.logf = open(self.logpath, "a")
        self._log(f"START mode={'DRY_RUN' if dry_run else 'PAPER_LIVE-intent'} "
                  f"engines={[s.id for s in self.specs]} tfs={sorted(self.by_tf)}")

    def _log(self, msg):
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        self.logf.write(line + "\n"); self.logf.flush(); print(line)

    # ---- feed ----
    def feed_sub_bar(self, epoch, o, h, l, c, vol=0):
        self.bars_seen += 1
        for agg in self.aggs.values():
            agg.add(epoch, o, h, l, c, vol)

    def _on_tf_close(self, tf, epoch, o, h, l, c, vol):
        bar_ts = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        for st in self.by_tf[tf]:
            eng = st["engine"]
            if st["spec"].needs_ts:
                eng.feed_ts(bar_ts)
            dec = eng.on_bar(o, h, l, c)
            if dec is None or self.warming:        # warmup: update indicators, no orders
                continue
            sig = str(dec["signal"])
            if sig.endswith("ENTER_LONG") and st["pos"] == 0:
                self._enter(st, bar_ts, dec)
            elif sig.endswith("EXIT_LONG") and st["pos"] > 0:
                self._exit(st, bar_ts, dec)

    # ---- orders (per-engine, tagged) ----
    def _enter(self, st, ts, dec):
        spec = st["spec"]; qty = int(dec.get("qty", 1)); price = dec["price"]
        payload = {"accountSpec": self.client.cfg.account_spec, "symbol": SYMBOL_LOCAL,
                   "action": "Buy", "orderQty": qty, "orderType": "Market",
                   "isAutomated": True, "strategy": spec.id,
                   "gate_status": spec.gate_status, "source": FILL_TAG}
        ack = self.client.place_order(payload)
        st["pos"] = qty; st["entry"] = price; st["entry_ts"] = ts; self.net += qty
        self._log(f"FILL ENTER {spec.id} qty={qty} entry={price:.2f} net={self.net} "
                  f"mode={ack['mode']} [{spec.gate_status}]")

    def _exit(self, st, ts, dec):
        spec = st["spec"]; price = dec["price"]; qty = st["pos"]
        payload = build_flatten(SYMBOL_LOCAL, qty, account_spec=self.client.cfg.account_spec)
        payload["strategy"] = spec.id; payload["source"] = FILL_TAG
        ack = self.client.place_order(payload)
        pnl = (price - st["entry"]) - FRICTION_PTS
        self.trades.append({"strategy": spec.id, "entry": st["entry"], "exit": price,
                            "pnl_pts": pnl, "qty": qty, "entry_ts": st["entry_ts"],
                            "exit_ts": ts, "gate_status": spec.gate_status})
        self.net -= qty
        self._log(f"FILL EXIT {spec.id} exit={price:.2f} pnl_pts={pnl:+.2f} "
                  f"net={self.net} mode={ack['mode']}")
        st["pos"] = 0; st["entry"] = None; st["entry_ts"] = None

    # ---- runners ----
    def run_dry(self, replay_path: str, last_bars: int = 0):
        self._log(f"DRY_RUN replay {replay_path} (1m sub-bars -> per-tf aggregation)")
        with open(replay_path, newline="") as f:
            rows = list(csv.DictReader(f))
        if last_bars and len(rows) > last_bars:
            rows = rows[-last_bars:]
        for r in rows:
            self.feed_sub_bar(int(r["time"]), float(r["open"]), float(r["high"]),
                              float(r["low"]), float(r["close"]), int(r.get("volume", 0) or 0))
        for agg in self.aggs.values():
            agg.close_final()
        self._log(f"DRY_RUN replay complete ({len(rows)} sub-bars)")

    def run_live(self, poll_s: int = 10):
        if self.client.mode != "PAPER_LIVE":
            raise SystemExit("client not PAPER_LIVE — set IBKR_ACCOUNT=DU* on a paper "
                             "port in .env and run without --dry-run, or use --dry-run.")
        res = self.client.authenticate()
        self._log(f"CONNECT {res}")
        ib, contract = self.client._ib, self.client._contract
        self._warmup(ib, contract)
        ticker = ib.reqMktData(contract, "", False, False)
        self._log("LIVE reqMktData(delayed) -> 1m bars -> multi-tf. Ctrl-C to stop.")
        while True:
            bar = self._poll_one_minute(ib, ticker, poll_s)
            if bar is None:
                self._log("POLL warning: no valid last/close this minute; skipping"); continue
            now = datetime.now(timezone.utc).timestamp()
            self.feed_sub_bar(int(now) - (int(now) % 60), *bar)

    def _warmup(self, ib, contract):
        self.warming = True
        for tf in sorted(self.by_tf):
            try:
                hist = ib.reqHistoricalData(contract, endDateTime="", durationStr="14400 S",
                                            barSizeSetting=f"{tf} mins", whatToShow="TRADES",
                                            useRTH=False)
                for b in hist:
                    self._on_tf_close(tf, int(b.date.timestamp()) if hasattr(b.date, "timestamp")
                                      else 0, b.open, b.high, b.low, b.close, b.volume)
                self._log(f"WARMUP tf={tf}m fed {len(hist)} bars")
            except Exception as e:
                self._log(f"WARMUP tf={tf}m skipped: {e}")
        self.warming = False

    @staticmethod
    def _poll_one_minute(ib, ticker, poll_s):
        o = h = l = c = None
        for _ in range(max(1, 60 // poll_s)):
            ib.sleep(poll_s)
            px = ticker.last
            if not (px == px and px is not None and px > 0):
                px = ticker.close
            if px == px and px is not None and px > 0:
                o = px if o is None else o
                h = px if h is None else max(h, px); l = px if l is None else min(l, px); c = px
        return None if o is None else (o, h, l, c)

    # ---- shutdown ----
    def shutdown(self):
        self._log("SHUTDOWN initiated")
        for st in self.states:
            if st["pos"] > 0:
                try:
                    p = build_flatten(SYMBOL_LOCAL, st["pos"],
                                      account_spec=self.client.cfg.account_spec)
                    p["strategy"] = st["spec"].id
                    ack = self.client.place_order(p)
                    self._log(f"SHUTDOWN flatten {st['spec'].id} qty={st['pos']} mode={ack['mode']}")
                except Exception as e:
                    self._log(f"SHUTDOWN flatten {st['spec'].id} error: {e}")
                self.net -= st["pos"]; st["pos"] = 0
        self._summary()
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.logf.close()

    def _summary(self):
        self._log("==== SESSION SUMMARY (per engine) ====")
        for st in self.states:
            sid = st["spec"].id
            ts = [t for t in self.trades if t["strategy"] == sid]
            pts = sum(t["pnl_pts"] * t["qty"] for t in ts)
            wins = sum(1 for t in ts if t["pnl_pts"] > 0)
            self._log(f"  {sid:24} trades={len(ts):3} wins={wins:3} "
                      f"pts={pts:+8.1f} est_$={pts*POINT_VALUE:+8.0f}  [{st['spec'].gate_status}]")
        self._log(f"bars_seen={self.bars_seen} net_exposure={self.net} "
                  f"(PAPER — fills flatter real; gate_status tags forward data)")
        self._log(f"log={self.logpath}")


def main():
    ap = argparse.ArgumentParser(description="Multi-engine paper book runner (IBKR)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replay", default="src/data/MNQ_1m_12mo_databento.csv")
    ap.add_argument("--bars", type=int, default=0, help="DRY_RUN: replay last N 1m bars (0=all)")
    args = ap.parse_args()
    bridge = MultiEngineBridge(dry_run=args.dry_run)
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
