"""T12 — Tradovate client (REST+WS), auth STUBBED to .env.

Constitution: NEVER place a live order. This client defaults to DRY_RUN — it
records the order payload (paper log) and returns a simulated ack; it performs NO
network I/O and imports no network library. Real demo-API calls are gated behind
DEMO_LIVE mode, which requires (a) demo credentials in the environment AND (b) an
explicit opt-in, and even then live order placement is disabled pending the
T18 live-handshake validation. There is no path to a real-money order here.

Credentials are read from env (TRADOVATE_*), so a free Tradovate DEMO account's
keys can be dropped in later without code changes.
"""
from __future__ import annotations
import os
import time
from dataclasses import dataclass, field

DEMO_BASE = "https://demo.tradovateapi.com/v1"   # DEMO endpoint only — never live
CRED_KEYS = ("NAME", "PASSWORD", "APP_ID", "APP_VERSION", "CID", "SEC", "DEVICE_ID")


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env_file(path: str | None = None) -> dict:
    """Load KEY=VALUE lines from a repo-root .env into the environment (does NOT
    override already-set vars). No-op if absent. Lets you 'drop keys in .env'
    instead of exporting them. The .env file is gitignored — keys never commit."""
    path = path or os.path.join(_repo_root(), ".env")
    loaded: dict[str, str] = {}
    if not os.path.exists(path):
        return loaded
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
            loaded[k] = v
    return loaded


@dataclass
class TradovateConfig:
    base_url: str = DEMO_BASE
    dry_run: bool = True             # NEVER auto-disable; must be explicitly set False
    env_prefix: str = "TRADOVATE_"
    account_spec: str = "DEMO"


class TradovateClient:
    def __init__(self, cfg: TradovateConfig = TradovateConfig()):
        self.cfg = cfg
        self._token: str | None = None
        load_env_file()   # pull repo-root .env into the environment if present
        self._creds = {k: os.environ.get(cfg.env_prefix + k) for k in CRED_KEYS}
        self.sent: list[dict] = []   # paper log of every order payload seen

    @property
    def has_credentials(self) -> bool:
        return all(self._creds.get(k) for k in ("NAME", "PASSWORD", "CID", "SEC"))

    @property
    def mode(self) -> str:
        # DRY_RUN unless explicitly opted out AND demo creds present
        return "DEMO_LIVE" if (not self.cfg.dry_run and self.has_credentials) else "DRY_RUN"

    def authenticate(self) -> dict:
        if self.mode == "DRY_RUN":
            self._token = "DRYRUN-TOKEN"
            return {"ok": True, "mode": "DRY_RUN",
                    "note": "auth stubbed; no network; awaiting free Tradovate DEMO keys (TRADOVATE_*)"}
        # DEMO_LIVE: real demo handshake would POST base_url/auth/accessTokenRequest.
        # Disabled here pending T18 live-handshake validation — never silently goes live.
        raise NotImplementedError(
            "DEMO_LIVE auth not enabled in this build (T18 BLOCKED_ON_KEYS). "
            "Verify the Tradovate demo handshake against live API docs before enabling.")

    def place_order(self, payload: dict) -> dict:
        """Record + (DRY_RUN) simulate. NEVER sends a live order."""
        rec = {"seq": len(self.sent) + 1, "ts": time.time(), "mode": self.mode, "payload": payload}
        self.sent.append(rec)
        if self.mode == "DRY_RUN":
            return {"ok": True, "mode": "DRY_RUN", "orderId": f"SIM-{rec['seq']}",
                    "isAutomated": payload.get("isAutomated"), "payload": payload}
        raise NotImplementedError(
            "DEMO_LIVE order placement disabled pending T18 live-handshake validation.")

    def sync_request(self) -> dict:
        """Position/account sync (user/syncRequest). Stubbed in DRY_RUN."""
        if self.mode == "DRY_RUN":
            return {"mode": "DRY_RUN", "positions": [], "note": "stub — no live account"}
        raise NotImplementedError("DEMO_LIVE sync disabled pending T18.")
