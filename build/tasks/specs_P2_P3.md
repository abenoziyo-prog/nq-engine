# Task Specs — P2 (Strategy Completion) & P3 (Execution Layer)

---
## T08 · v4-short-impl
**GOAL:** implement the mirror short spec (EMA_PROX_V4_SHORT_5M) as code — untested live by design.
**DELIVERABLE:** short path in `src/engine/v4.py` (or a `V4Engine(direction="short")`),
entry: |g|<=k, g>0, dG<0, ddG<0; exit anticipated upcross; catastrophe stop 4*ATR above;
daily-align +1 when daily gap<0 and falling.
**ACCEPTANCE:** unit test confirms the short engine fires the mirror conditions on synthetic
data; a backtest on the (up-tape) 5m data shows it correctly produces few/no profitable
trades (expected in this regime) — i.e. it RUNS correctly, not that it's profitable yet.
**NOTES:** do NOT tune it to be profitable on up-tape data. It waits for a bear window.

## T09 · lvl-imb-engine
**GOAL:** the London/Asia displacement-imbalance zone engine in production code.
**DELIVERABLE:** `src/engine/lvl_imb.py` — zone detection (OB + merged FVG in displacement),
multi-touch survival (die on close-through, touch-count feature), NY-tap entry at zone mid,
structural stop, trail exit, rising-200EMA gate, long-only.
**ACCEPTANCE:** reproduces LVL_IMB_LONDON_5M vault stats (n~151, PF~3.2; with EMA gate ~4.35)
within tolerance via the harness. Regression test added.
**NOTES:** EOD-flatten rule is obsolete (hold-through-validity mandate) — implement hold-through.

## T10 · daymap-feature
**GOAL:** session-context day-map as a live feature feed all engines can read.
**DELIVERABLE:** `src/session/daymap.py` — per Globex day computes London state
(hold/sweep/inside/both), first-break side, AM result, conflict-cell flags, suppressor flag;
exposes a `ContextSnapshot` extension consumed by engines and the research loop.
**ACCEPTANCE:** recomputes the matrix findings (London-hold→85% NY-high-draw; first-break
commitment 13-15%; AM→PM 72%/58%) on the 15m history within tolerance.
**NOTES:** the suppressor (non-committed days) must be queryable so the allocator can downsize.

## T11 · vault-promotion-logic
**GOAL:** automated, rule-bound lifecycle transitions in the vault.
**DELIVERABLE:** `src/research/promotion.py` — enforces SPEC_ONLY→CANDIDATE (clears factorial
robust region + drift) →FROZEN_AWAITING_OOS (clears walk-forward) →shadow→ (operator gate for
capital). Demotes to DEGRADED/FALSIFIED on failure. Writes vault + reason; never promotes to
live capital without operator flag.
**ACCEPTANCE:** unit test drives a fake strategy through every transition and asserts the gates
block/allow correctly; asserts it can NEVER reach a 'LIVE' state without operator approval field.
**NOTES:** this is what lets the research loop self-manage the rack safely.

---
## T12 · tradovate-client
**GOAL:** REST + WebSocket Tradovate client, auth stubbed to .env until keys arrive.
**DELIVERABLE:** `src/bridge/tradovate.py` — `/auth/accesstokenrequest` with token refresh;
account list; market-data WS subscribe; trading WS; rate-limit-aware (back off on 429).
Reads creds from env: TV_NAME, TV_PASSWORD, TV_APP_ID, TV_CID, TV_SEC, TV_DEVICE_ID, TV_ENV(demo/live).
**ACCEPTANCE:** with dummy env vars, a dry-run unit test exercises request construction,
token-refresh logic, and 429 backoff using a MOCKED http layer (no network). All payloads
match the documented schema. Live handshake test is T18 (BLOCKED_ON_KEYS).
**NOTES:** default TV_ENV=demo. Never default to live. isAutomated handled in T13.

## T13 · oso-bracket-builder
**GOAL:** construct the entry+stop(+target) OSO order with the regulatory flag.
**DELIVERABLE:** `src/bridge/orders.py` — builds `/order/placeOSO` payload: market/limit entry,
catastrophe stop from risk decision, `isAutomated: true` always, accountSpec/accountId from session.
Optional scale-out legs for the prop-overlay exit.
**ACCEPTANCE:** unit test builds a known proposal into the exact documented OSO JSON, asserts
isAutomated=true present, stop on correct side, qty = risk-approved qty (not raw signal qty).
**NOTES:** qty MUST come from the RiskDecision, never the raw signal.

## T14 · bridge-receiver
**GOAL:** the spine — receive signal, risk-check, place order.
**DELIVERABLE:** `src/bridge/server.py` — FastAPI endpoint `/webhook` (TradingView JSON) AND an
internal mode that consumes engine signals directly; verifies a shared secret; maps payload→
OrderProposal; calls RiskManager; on ALLOW/DOWNSIZE builds OSO via T13 and submits via T12;
logs everything (signal, decision, order, response) as structured JSON to logs/.
**ACCEPTANCE:** integration test (mocked Tradovate) feeds a V4 entry webhook, asserts: secret
verified, risk applied (correct qty), isAutomated order built, fill logged. A REJECT/HALT path
asserts NO order is sent. Replay of a duplicate webhook is idempotent (no double order).
**NOTES:** idempotency keyed on bar_time+strategy. Reject anything failing secret check.

## T15 · reconciliation-loop
**GOAL:** keep internal position state == broker truth, always.
**DELIVERABLE:** `src/bridge/reconcile.py` — subscribes user/syncRequest WS; on every
position/order/fill event updates AccountState (realized pnl, open position, high-water);
every N seconds compares internal vs broker; on desync → flatten-and-halt + alert.
**ACCEPTANCE:** simulated event stream drives state correctly; an injected desync triggers the
halt path in test. AccountState fields feed the RiskManager live.
**NOTES:** "flatten and halt on desync" is a safety invariant; never trade through uncertainty.

## T16 · crash-recovery
**GOAL:** restart-safe — recover open positions and state after any crash.
**DELIVERABLE:** persistence of AccountState + open orders to disk (build/state/runtime.json),
on boot reconcile against broker before accepting any new signal.
**ACCEPTANCE:** kill the process mid-position in test, restart, assert it recovers the open
position from broker truth and refuses new entries until reconciled.
**NOTES:** target <5s restart (systemd Restart=always handles the relaunch).
```
