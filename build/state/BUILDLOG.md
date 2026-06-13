# Build Log

Append one entry per completed task: timestamp, task id, acceptance result, commit hash.


## 2026-06-13 02:31 — T01 backtest-harness DONE
Acceptance PASS: src/backtest/harness.py reproduces EMA_PROX_V4_5M base config exactly (n=21, +4935pt, PF 5.66). Regression baseline locked. Next workable: T02 (regression suite), T03 (data store), T04 (risk tests), T07 (drift) — all unblocked.

## 2026-06-12 — T04 risk-manager-tests DONE
Acceptance PASS: tests/test_risk.py — 18 boundary cases, all green. Covers every limit in the spec against src/risk/manager.py: per-trade $ ceiling (exact numbers: 98pt stop @ $2 = $196/ct < $200 → ALLOW 1; 2-lot tier $392 → DOWNSIZE to 1; 40pt $160 → ALLOW 2), catastrophe-too-wide (100pt $200 boundary ALLOW, 100.5pt $201 REJECT, invalid/<=0 stop REJECT), trailing-DD proximity HALT (room <= $200 boundary), session-loss HALT (<= -$600 boundary), daily-align +1 only with $400 buffer AND alignment, max-contracts clamp, FLAT always ALLOW even when halted / DD-breached / session-stopped. Manager required no code changes — already correct at every boundary. Regression guard tests/test_core.py still PASS. Next workable in P1: T05 walkforward, T06 factorial, T07 drift (all dep T01, DONE).
