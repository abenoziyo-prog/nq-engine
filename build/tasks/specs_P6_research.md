# Task Specs — P6 (Research-unblocked work from the 1m databento sync, 2026-06-15)

Each task: GOAL · DELIVERABLE · ACCEPTANCE (objective pass condition) · NOTES.
Mark DONE only when ACCEPTANCE passes. Never fabricate a pass.

These tasks were spec'd when the 1m+volume databento dataset
(src/data/MNQ_1m_12mo_databento.csv) landed and produced the OB NY-open strategy
and the SHOCK UP-shock finding. The OB/SHOCK results in strategy_vault.json are
operator-reported external research; T24/T26 must REPRODUCE them in-repo before any
promotion. None of these are built yet.

---
## T24 · ob-nyopen-engine
**GOAL:** turn the externally-validated OB_NYOPEN_BULL_1M into a production engine that
backtest and live share, and lock its numbers with a regression test.
**DELIVERABLE:** `src/engine/ob_nyopen.py` — NY-open bullish order-block reversion on 1m
implementing `on_bar()` like the other engines (entry 09:30-09:50 ET open window, OB
reversion long, NO volume filter — both falsified per vault). Plus `tests/test_ob_nyopen.py`.
**ACCEPTANCE:** running the engine through the harness on src/data/MNQ_1m_12mo_databento.csv
reproduces the vault headline within tolerance: **n=798 (±2%), PF 2.26 (±0.1), max DD
≈ −$323 (MNQ $2/pt)**, 13/13 green months. Drift control (mandatory) beats benchmark
(2.26 vs ~0.90). Assert in the test; it must pass. Also report effective day-level n and
top-3 profit concentration (not provided externally — constitution rule 7).
**NOTES:** deps T01 (harness). If the in-repo run does NOT reproduce n=798/PF 2.26, do
NOT massage parameters — report the discrepancy to the operator (the external result may
use a definition we must clarify). $-figures are MNQ prop dollars, not the legacy $20/pt.

## T25 · ob-walkforward-oos
**GOAL:** out-of-sample / walk-forward validation of OB_NYOPEN_BULL_1M before promotion.
**DELIVERABLE:** walk-forward run (via T05 framework) over the 12-month series: rolling
train/test, per-window PF + OOS/IS PF ratio, DD-vs-$2K-prop-limit check each window.
**ACCEPTANCE:** produces a per-window report; flags DEGRADED if any test window PF<1.0 or
OOS/IS ratio<0.4, and confirms (or refutes) that max DD stays within the $2K prop limit
out-of-sample. Deterministic, re-runnable.
**NOTES:** deps T24 (engine) + T05 (walk-forward framework). This is the gate that decides
CANDIDATE → FROZEN_AWAITING_OOS for the OB strategy. 13/13 green months is single-regime;
walk-forward + a down-tape window are required before trusting it.

## T26 · shock-v1-build
**GOAL:** productionize the SHOCK_v1 engine now that 1m+volume data exists (FINDING in vault).
**DELIVERABLE:** promote `src/detector/shock.py` detection into a full engine path —
direction-split UP/DOWN, entry-scheme bake-off (E1-E4), impulse-scaled stops, trail/
duration/scratch exits (docs/SHOCK_ENGINE_SPEC.md sec 4-6) — wired through the harness,
with `tests/test_shock_v1.py` locking the backtest_v1 numbers in the vault.
**ACCEPTANCE:** reproduces the recorded bake-off within tolerance: UP-shock E3 PF≈3.6
(n≈33), DOWN-shocks all PF<1; detection pre-registered at k=4.0 with the one-step k=3.5
fallback. Mandatory drift control reported. Test must pass.
**NOTES:** deps T01. Does NOT promote to capital — UP n=45 is below the spec's 50-event
gate and there is no gamma feed yet; this only locks the research engine. Model E3 fill
slippage before trusting PF 3.6 (current backtest assumes exact intrabar fills).
