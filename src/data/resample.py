"""Resample 1-minute bars to higher timeframes with proper OHLC aggregation.

Buckets are clock-aligned by epoch seconds (5m -> %300, 15m -> %900) and labeled
by bucket START time, matching the existing clean exports. OHLC = first-open /
max-high / min-low / last-close; volume summed. Session gaps (weekends, maintenance)
simply yield buckets with fewer 1m bars — no synthetic fills.

CLI:  python -m src.data.resample src/data/MNQ_1m_12mo_databento.csv 5 src/data/MNQ_5m_12mo_databento.csv
"""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OUT_HEADER = ["time", "ts_utc", "ts_et", "open", "high", "low", "close", "volume"]


def _fmt(v: float) -> str:
    return f"{v:g}"


def resample(in_path: str, minutes: int, out_path: str) -> dict:
    step = minutes * 60
    buckets: dict[int, list] = {}        # bucket_start_epoch -> [o,h,l,c,vol]
    order: list[int] = []
    rows_in = 0
    with open(in_path, newline="") as f:
        for r in csv.DictReader(f):
            rows_in += 1
            t = int(r["time"]); o = float(r["open"]); h = float(r["high"])
            l = float(r["low"]); c = float(r["close"]); v = int(r["volume"])
            key = t - (t % step)
            b = buckets.get(key)
            if b is None:
                buckets[key] = [o, h, l, c, v]
                order.append(key)
            else:
                b[1] = max(b[1], h); b[2] = min(b[2], l); b[3] = c; b[4] += v
    order.sort()
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OUT_HEADER)
        for key in order:
            o, h, l, c, v = buckets[key]
            dt = datetime.fromtimestamp(key, tz=timezone.utc)
            w.writerow([key, str(dt), dt.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S"),
                        _fmt(o), _fmt(h), _fmt(l), _fmt(c), v])
    return {"rows_in": rows_in, "rows_out": len(order),
            "first": order[0], "last": order[-1]}


if __name__ == "__main__":
    import sys
    in_path, minutes, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    info = resample(in_path, minutes, out_path)
    print(f"{in_path} -> {out_path}  ({minutes}m): {info['rows_in']} -> {info['rows_out']} bars")
