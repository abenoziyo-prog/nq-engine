# Task Specs — P0 (Foundations) & P1 (Risk + Validation)

Each task: GOAL · DELIVERABLE · ACCEPTANCE (objective pass condition) · NOTES.
The agent marks DONE only when ACCEPTANCE passes. Never fabricate a pass.

---
## T01 · backtest-harness
**GOAL:** one event-driven backtester that replays bars through the shared engine modules,
so backtest and live use identical signal code.
**DELIVERABLE:** `src/backtest/harness.py` — loads a parquet/csv bar series, streams bars to
any engine implementing `on_bar()`, applies friction, computes the standard stat block
(n, win%, total_pts, PF, maxDD, Sharpe_daily, avg/max W/L, avg/max duration, capture, giveback).
**ACCEPTANCE:** running V4 (base, no stop, no daily-align) through the harness on
`data/MNQ_5m_aggregated_clean.*` returns n=21, total=+4935 (±5pt), PF 5.66 (±0.05).
Assert this in `tests/test_harness.py`; it must pass.
**NOTES:** ATR = simple rolling-mean (NOT Wilder) — this is the validated convention.
EMAs = ewm adjust=False. dG/ddG seeded to match the vault (prepend-diff equivalent).

## T02 · engine-regression-suite
**GOAL:** lock every vault number so no future change silently breaks the engine.
**DELIVERABLE:** `tests/test_vault_regression.py` asserting, for each strategy with results
in strategy_vault.json, that the harness reproduces its headline stats within tolerance.
**ACCEPTANCE:** suite passes for EMA_PROX_V4_5M (with stop and daily-align variants),
EMA_PROX_V0B_5M, and the 15m V4 configs. Each assertion names the vault id and tolerance.
**NOTES:** this is the guard rail. If a later task breaks it, that task is BLOCKED, not DONE.

## T03 · data-store
**GOAL:** durable, session-tagged bar store ingesting historical + (later) live bars.
**DELIVERABLE:** `src/data/store.py` — append-only parquet keyed by (symbol, timeframe, ts);
dedupe; data-quality check (gaps vs CME session calendar, OHLC integrity); session tagging
via existing `src/session/context.py`. CLI: `python -m src.data.store ingest <csv>`.
**ACCEPTANCE:** ingesting the existing 5m and 15m cleaned CSVs yields the same row counts
already validated (19168 / 20424), zero dupes, zero OHLC violations; re-ingesting is idempotent.
**NOTES:** parquet so the research loop reads it fast. Keep raw + derived separate.

---
## T04 · risk-manager-tests
**GOAL:** prove the risk manager vetoes correctly at every boundary before it ever sees a live order.
**DELIVERABLE:** `tests/test_risk.py` covering: per-trade $ ceiling downsizing; trailing-DD
proximity HALT; session-loss HALT; daily-align +1 only with buffer; max-contracts clamp;
catastrophe-stop-too-wide REJECT; FLAT always allowed even when halted.
**ACCEPTANCE:** all boundary cases pass. Include the exact $50K/$2K/MNQ numbers:
e.g. 4*ATR=98pt stop at $2/pt = $196/contract < $200 ceiling → 1 lot ALLOW; at 2 lots the
$392 risk vs $200 ceiling → DOWNSIZE to 1.
**NOTES:** risk manager already drafted in src/risk/manager.py — write tests, fix any gaps found.

## T05 · walkforward-framework
**GOAL:** re-validate frozen strategies on rolling out-of-sample windows.
**DELIVERABLE:** `src/backtest/walkforward.py` — train/test roll (configurable window),
tracks `last_oos_through` per strategy, outputs OOS stat block + OOS/IS PF ratio,
flags DEGRADED when OOS PF<1.0 or ratio<0.4.
**ACCEPTANCE:** on the 15m series (Jul2025-Jun2026), produces a per-window report for V4
and correctly identifies Feb 2026 as the weak window. Deterministic; re-runnable.
**NOTES:** feeds research-loop prompt P3.

## T06 · factorial-runner
**GOAL:** sweep multiple variables and report MAIN EFFECTS, not just the top cell.
**DELIVERABLE:** `src/backtest/factorial.py` — takes a param grid, runs all combos,
outputs per-variable main-effect tables (median PF/total/%positive across other vars)
plus top-N by PF and by total, plus robust-region check (neighborhood median).
**ACCEPTANCE:** reproduces the V4 sweep result: 9x50 and 21x100 as co-ridges, tighter k
better, acceleration neutral-to-positive, price-trails destroy P&L. Output matches the
analysis already in the vault findings within tolerance.
**NOTES:** this is the engine behind research-loop prompt P5.

## T07 · drift-control
**GOAL:** the mandatory benchmark — random same-session entries — so no strategy is judged
on absolute P&L alone.
**DELIVERABLE:** `src/backtest/drift_control.py` — for a given session window and direction,
generates N random entries, same horizon as the strategy, returns the benchmark stat block.
**ACCEPTANCE:** reproduces the ~0.93 MFE/MAE NY-morning-long drift number used earlier.
Seeded/deterministic for reproducibility; also supports a Monte-Carlo mode (many seeds).
**NOTES:** buy-and-hold is RETIRED — do not implement it as a benchmark.
```
