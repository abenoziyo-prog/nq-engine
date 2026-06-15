# Build Log

Append one entry per completed task: timestamp, task id, acceptance result, commit hash.


## 2026-06-13 02:31 — T01 backtest-harness DONE
Acceptance PASS: src/backtest/harness.py reproduces EMA_PROX_V4_5M base config exactly (n=21, +4935pt, PF 5.66). Regression baseline locked. Next workable: T02 (regression suite), T03 (data store), T04 (risk tests), T07 (drift) — all unblocked.

## 2026-06-12 — T04 risk-manager-tests DONE
Acceptance PASS: tests/test_risk.py — 18 boundary cases, all green. Covers every limit in the spec against src/risk/manager.py: per-trade $ ceiling (exact numbers: 98pt stop @ $2 = $196/ct < $200 → ALLOW 1; 2-lot tier $392 → DOWNSIZE to 1; 40pt $160 → ALLOW 2), catastrophe-too-wide (100pt $200 boundary ALLOW, 100.5pt $201 REJECT, invalid/<=0 stop REJECT), trailing-DD proximity HALT (room <= $200 boundary), session-loss HALT (<= -$600 boundary), daily-align +1 only with $400 buffer AND alignment, max-contracts clamp, FLAT always ALLOW even when halted / DD-breached / session-stopped. Manager required no code changes — already correct at every boundary. Regression guard tests/test_core.py still PASS. Next workable in P1: T05 walkforward, T06 factorial, T07 drift (all dep T01, DONE).

## 2026-06-15 — T07 drift-control DONE
Acceptance PASS: src/backtest/drift_control.py reproduces the recorded ~0.93 NY-morning-long MFE/MAE drift benchmark (strategy_vault.json OB_STRICT_SINGLE_TOUCH "drift control 0.93"). Random same-session NY_AM long entries, fixed horizon, floor-at-0 excursion ratio = Σmfe/Σmae: single-seed 0.929 (H=6, n=500, seed=12345); Monte-Carlo pooled 0.928 / mean 0.934 over 200 seeds (p5/50/95 = 0.78/0.93/1.09). Deterministic via local random.Random(seed) — never the global RNG; MC seed list derived deterministically from cfg.seed → fully re-runnable. Reuses harness Stats/_stats (no stat-math duplication) and Session-tagged Bars. CLI: `python -m src.backtest.drift_control [--mc N]`. Buy-and-hold NOT implemented (retired per operator directive). tests/test_drift.py 4 cases green; regression guards tests/test_core.py + tests/test_risk.py still PASS. Next workable in P1: T05 walkforward, T06 factorial (both dep T01, DONE).
