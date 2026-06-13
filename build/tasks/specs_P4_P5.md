# Task Specs — P4 (Integration) & P5 (Hardening)

---
## T17 · live-feed-adapter
**GOAL:** real-time NQ/MNQ bars into the engine AND the data store, so the daily research
prompts stop returning AWAITING_DATA.
**DELIVERABLE:** `src/data/live_feed.py` — subscribes Tradovate market-data WS, aggregates
ticks/quotes into 5m + 15m bars on close, appends to the store, and pushes each closed bar
to the live engine instances. Handles reconnect with backoff; fills gaps from REST chart on reconnect.
**ACCEPTANCE:** with a mocked WS emitting synthetic ticks, produces correct 5m/15m bars,
appends them idempotently, and triggers engine on_bar exactly once per closed bar.
**NOTES:** bar-close semantics must match the backtest (the engine acts on closed bars).

## T18 · paper-integration-test  [BLOCKED_ON_KEYS]
**GOAL:** prove the whole chain works end-to-end on the DEMO environment.
**DELIVERABLE:** `tests/test_integration_paper.py` — against TV_ENV=demo with real (demo) keys:
auth → subscribe MNQ → on a forced V4 signal, place an OSO via the bridge → confirm the order
appears in the demo account → flatten → confirm. Full round trip.
**ACCEPTANCE:** the round trip completes against the live demo endpoint; order shows isAutomated;
position reconciles; flatten confirmed. REQUIRES demo API keys in env.
**NOTES:** this is the first task that needs real credentials. Until then: BLOCKED_ON_KEYS.
Everything upstream is testable with mocks and must be GREEN before this runs.

## T19 · slippage-audit-harness  [BLOCKED_ON_KEYS]
**GOAL:** measure live fills vs backtest assumptions — the real-edge audit.
**DELIVERABLE:** `src/research/slippage.py` — reads logs/fills, compares realized entry/exit
to the bar-close + 1pt assumption, reports median slippage per strategy and per session window
(overnight vs RTH — V4's overnight entries are the suspect ones).
**ACCEPTANCE:** on a sample fills log, computes correct per-window slippage; raises DRIFT_ALERT
when median > 1.5pt. Feeds research-loop prompt P2.
**NOTES:** if overnight slippage >1.5pt, V4's frozen P&L must be re-marked — this harness is
how we learn that before it costs real money.

## T20 · deploy-doc
**GOAL:** operator can go clone → paper-trading in <30 min.
**DELIVERABLE:** `DEPLOY.md` — VPS provisioning, timezone, Python/Node setup, .env template
(every required var, where to get it), systemd units (bridge + reconcile, Restart=always),
crontab install (research loop), TradingView alert setup (paste webhook + JSON), demo-first
checklist, go-live checklist, kill-switch usage.
**ACCEPTANCE:** a dry walkthrough on a fresh Ubuntu box (documented in BUILDLOG) reaches the
point where the bridge is listening and the demo handshake succeeds, in the documented steps.
**NOTES:** demo-first is mandatory in the doc. Live capital only after the slippage audit week.

---
## T21 · kill-switch
**GOAL:** instant, total stop — operator-initiated and automated.
**DELIVERABLE:** `src/bridge/killswitch.py` — a flag file + an endpoint that: cancels working
orders, flattens open positions, and refuses all new entries until manually cleared. Automated
triggers: trailing-DD breach proximity, reconciliation desync, error-rate threshold.
**ACCEPTANCE:** test asserts that setting the kill flag flattens + blocks new entries; that an
automated trigger (simulated DD breach) fires it; that clearing requires explicit operator action.
**NOTES:** the most important safety component. Build it paranoid.

## T22 · monitoring-alerts
**GOAL:** the operator always knows the system's state without watching it.
**DELIVERABLE:** `src/bridge/notify.py` — structured alerts to the notify channel
(Telegram/Slack/email) for: every fill, every risk REJECT/HALT, reconciliation desync,
crash/restart, drift alerts, daily heartbeat with open position + session pnl + DD room.
**ACCEPTANCE:** each event type produces a correctly formatted alert in test (mocked channel).
Heartbeat includes the numbers the operator needs to make a deploy call.
**NOTES:** alerts are recommendations/status; never an instruction the operator must act on instantly.

## T23 · cost-guard
**GOAL:** the research loop cannot run up a surprise API bill.
**DELIVERABLE:** `src/research/cost_guard.py` — tracks daily API spend, hard cutoff at a
configured cap, alerts at 2x average; max-steps-per-run cap to prevent runaway agent loops.
**ACCEPTANCE:** simulated spend over the cap halts further runs that day and alerts; under cap proceeds.
**NOTES:** protects against an agent stuck in a loop. Independent of trading risk.

---
## DEFINITION OF DONE (whole build)
All tasks DONE except T18/T19 which flip from BLOCKED_ON_KEYS to DONE once the operator supplies
demo keys and the live handshake passes. At that point: research loop runs on real data,
bridge paper-trades end-to-end, slippage audit begins, DEPLOY.md is validated. The operator
then runs the documented demo→live promotion after a clean paper week.
```
