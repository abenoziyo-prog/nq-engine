# BUILD MANIFEST — nq-engine autonomous build
**Purpose:** drive a scheduled build agent that constructs, tests, and readies the full
trading system task-by-task across many runs. Each cron fire = the agent reads this manifest,
picks the next unblocked PENDING task, completes it, runs its acceptance test, updates state,
commits, and reports. No run is expected to finish everything.

## THE END RESULT (what "done" means)
A deployable repo where:
1. `src/engine/` produces V4 + all CANDIDATE-or-better vault signals, bit-identical in
   backtest and live (regression-tested against frozen vault numbers).
2. `src/backtest/` is an event-driven harness that reproduces every vault stat on demand,
   and runs the factorial + walk-forward + drift-control framework.
3. `src/risk/` vetoes any order violating the $50K/$2K constraints; unit-tested at limits.
4. `src/bridge/` receives a TradingView webhook (or internal signal), passes it through risk,
   places an `isAutomated:true` OSO bracket on Tradovate, and reconciles position state.
   Runs headless, auto-reconnects, crash-safe. (Auth stubbed to .env until keys arrive.)
5. `src/data/` ingests live + historical NQ/MNQ, session-tagged, into the parquet store.
6. The research loop (routines/) runs against real state, not AWAITING_DATA stubs.
7. A full integration test passes end-to-end on the demo/paper environment.
8. DEPLOY.md lets the operator go from clone → paper-trading in <30 min.

## OPERATING RULES FOR THE BUILD AGENT
- Read build/state/STATUS.json first. Work the highest-priority task whose deps are all DONE.
- One task per run unless a task is trivially small and its successor is unblocked.
- Every task has an ACCEPTANCE test. A task is DONE only when its test passes. If it fails,
  set status BLOCKED with the error and report; do not mark DONE.
- After each task: run the full existing test suite (regression guard), commit with the task id,
  update STATUS.json, append to build/state/BUILDLOG.md, notify the operator.
- NEVER fabricate a passing test. NEVER place live orders during build (use demo/dry-run).
- NEVER weaken the regression target: the engine must keep reproducing vault numbers exactly.
- If blocked on the API keys, build everything around them with the auth layer stubbed and
  mark only the live-handshake tasks BLOCKED_ON_KEYS; keep building the rest.
- Respect the constitution in CLAUDE.md. Research-only rules apply; the build agent writes
  execution CODE but never executes live trades itself.

## TASK GRAPH (priority order; deps in brackets)
See build/tasks/*.md for full spec of each. Summary:

P0 foundations
- T01 backtest-harness        [—]            event-driven engine, replays vault
- T02 engine-regression-suite [T01]          asserts every vault stat reproduces
- T03 data-store              [—]            parquet ingest + session tagger wired

P1 risk + validation
- T04 risk-manager-tests      [—]            unit tests at every limit/edge
- T05 walkforward-framework   [T01]          train/test roll + OOS tracking
- T06 factorial-runner        [T01]          variable sweep + main-effects report
- T07 drift-control           [T01]          random-entry benchmark generator

P2 strategy completion
- T08 v4-short-impl           [T02]          implement+test the mirror spec (no live)
- T09 lvl-imb-engine          [T02]          zone engine to code, reproduce PF 3.2
- T10 daymap-feature          [T03]          session-context features as live feed
- T11 vault-promotion-logic   [T05,T07]      automated lifecycle transitions

P3 execution layer
- T12 tradovate-client        [—]            REST+WS client, auth STUBBED to .env
- T13 oso-bracket-builder     [T12]          isAutomated OSO order construction
- T14 bridge-receiver         [T04,T13]      webhook -> risk -> order
- T15 reconciliation-loop     [T12]          user/syncRequest position sync
- T16 crash-recovery          [T15]          restart-safe position recovery

P4 integration
- T17 live-feed-adapter       [T03,T12]      live NQ bars into engine + research loop
- T18 paper-integration-test  [T14,T17]      end-to-end on demo env  [BLOCKED_ON_KEYS]
- T19 slippage-audit-harness  [T18]          live-vs-backtest fill comparison
- T20 deploy-doc              [all]          DEPLOY.md clone->paper in <30min

P5 hardening
- T21 kill-switch             [T14]          operator + automated halt paths
- T22 monitoring-alerts       [T14]          heartbeat, error, drift notifications
- T23 cost-guard              [—]            API spend cap on the research loop

P6 research-unblocked (1m databento sync 2026-06-15; see build/tasks/specs_P6_research.md)
- T24 ob-nyopen-engine        [T01]          OB_NYOPEN_BULL_1M production engine + regression (reproduce n=798/PF2.26)
- T25 ob-walkforward-oos      [T24,T05]      walk-forward OOS of OB incl $2K-prop-DD check
- T26 shock-v1-build          [T01]          productionize SHOCK_v1 (UP E3 edge); does NOT promote (n<50 gate)

## STATUS
Tracked in build/state/STATUS.json. Initialized all PENDING except where deps allow start.
```
