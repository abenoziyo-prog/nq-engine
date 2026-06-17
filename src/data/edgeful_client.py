"""Edgeful API client — read-only report fetch (stdlib only).

Base: https://api.edgeful.com
Auth: Authorization: Bearer <EDGEFUL_API_KEY>   (key from env / repo-root .env; never hard-coded)
Endpoint: GET /report_calculation/{report}/{market_type}/{ticker}?start_date=&end_date=[&...]

This is a READ-ONLY stats API (no orders). Used to cross-check our own in-repo
reproductions of Edgeful's probability reports against their published numbers.
The key is loaded from .env (gitignored) — it is never written into code or commits.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.parse

BASE = "https://api.edgeful.com"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env() -> None:
    path = os.path.join(_repo_root(), ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class EdgefulClient:
    def __init__(self, api_key: str | None = None, base: str = BASE, timeout: int = 30):
        _load_env()
        self.key = api_key or os.environ.get("EDGEFUL_API_KEY")
        self.base = base.rstrip("/")
        self.timeout = timeout

    @property
    def has_key(self) -> bool:
        return bool(self.key)

    def get_report(self, report: str, ticker: str = "NQ", market_type: str = "futures",
                   start_date: str = "", end_date: str = "", **params) -> dict:
        """GET one report. report = endpoint name (e.g. 'gap-fill-standard').
        Optional params: start_time, end_time (HH:MM:SS), period (int), timezone (IANA)."""
        if not self.has_key:
            raise RuntimeError("EDGEFUL_API_KEY not set — put it in .env (gitignored).")
        q = {"start_date": start_date, "end_date": end_date}
        q.update({k: v for k, v in params.items() if v is not None})
        url = f"{self.base}/report_calculation/{report}/{market_type}/{ticker}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.key}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())


if __name__ == "__main__":
    import sys
    c = EdgefulClient()
    rep = sys.argv[1] if len(sys.argv) > 1 else "gap-fill-standard"
    data = c.get_report(rep, "NQ", "futures", "2026-06-01", "2026-06-13")
    print(json.dumps(data, indent=2)[:1500])
