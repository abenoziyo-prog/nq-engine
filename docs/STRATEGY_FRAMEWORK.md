# Strategy Framework — systematic generation, testing, and deployment

How a trading idea becomes (or fails to become) a deployed strategy in this engine.
The goal is a **repeatable pipeline with hard gates**, so every idea is tested the
same way and every result — win or lose — is recorded. Built from what this repo has
learned the hard way (see *Codified lessons*).

---

## 0. Principles (from CLAUDE.md, do not violate)

1. **The unit of edge is the deployment decision, not the model.** Strategies are
   regime-matched instruments. The job is to identify the current regime, deploy the
   right tool, and **kill it when it stops performing** — not to find one model robust
   across 5 years.
2. **Edge lives in LOCATION (zones/levels) and TIMING (session structure), not
   indicators.** Indicator-trigger strategies have repeatedly falsified here (EMA
   crosses: −$5,380 live; see anti-patterns).
3. **Recent price action > long history** in a regime-shifting market. Validate on
   "matched to present + fast to kill," not "robust across all history."
4. **Negative results are first-class.** Every test is logged to the vault, win or
   lose, so dead ideas are never rediscovered.

---

## 1. The pipeline

```
  HYPOTHESIS → ENGINE → BACKTEST → VALIDATE → RECORD → FORWARD-TEST → DECIDE
   (stage 0)   (1)       (2)        (3)        (4)       (5)           (6)
```

Each stage has an exit gate. An idea that fails a gate is recorded FALSIFIED and stops.

### Stage 0 — Hypothesis
State the edge in one sentence, tagged by family and what makes it *location/timing*
rather than *indicator*. Define entry, exit, stop, and the regime it should work in
**before** any backtest. Pre-registration prevents fitting to outcomes.

### Stage 1 — Engine
Implement as an engine class with the standard `on_bar` contract (see §2). Copy
`src/engine/_template_engine.py`. The SAME class runs backtest and live (Invariant #1).

### Stage 2 — Backtest
`python research/validate_strategy.py <module:Class>` runs the gate battery on the
databento data. Core metrics: PF, win%, n, max DD, trades/day, effective (day-level)
sample size, top-3 concentration.

### Stage 3 — Validate (the hard gates)
| Gate | Threshold | Why |
|---|---|---|
| **Drift control** | beats random same-session entries | not just market beta (B&H retired) |
| **PF** | > 1.5 floor (candidate); skeptical above small n | edge must clear friction |
| **Effective n** | report day-level n + concentration | high PF on 3 trades = noise (rule 7) |
| **Top-3 concentration** | < ~60% | edge must be broad, not 3 lucky trades |
| **Blind OOS** | PF holds (expect compression toward ~1.0) | the honest test (vault finding #7) |
| **Prop-fit** | **max DD fits the $2K trailing limit** | a model that blows the account is undeployable regardless of PF |
| **Timing sweep** | test anticipatory/confirmed/delayed | mandatory before any FALSIFIED verdict (rule 5) |

### Stage 4 — Record (always)
Add a row to `strategy_vault.json` + `STRATEGY_VAULT.md` with status, metrics, rules,
caveats — **win or lose**. This is the memory that prevents rediscovery.

### Stage 5 — Forward-test (paper)
Register in `src/bridge/engine_registry.py`, run on IBKR paper via
`multi_engine_bridge.py`, gate-tagged with its vault status. **Caveat:** the live feed
is delayed (~15 min) → fills slip ~70 pt vs signal price. Forward P&L is read from the
**broker** (`trade_log.py`), never the bridge's own logged pnl. Use forward-test to
confirm the engine *fires correctly and the stop behaves*, not the dollar numbers.

### Stage 6 — Decide (promote or kill)
`frozen config → blind OOS → shadow (paper) → capital`. A strategy earns capital only
by passing every gate. Kill the moment forward data contradicts the backtest.

---

## 2. Engine contract

```python
class MyEngine:
    def __init__(self, cfg: MyConfig = MyConfig()): ...
    def on_bar(self, o, h, l, c, daily_gap=0.0, daily_rising=False) -> dict | None:
        # return None, or one decision dict:
        # {"signal": Signal.ENTER_LONG|EXIT_LONG|ENTER_SHORT|EXIT_SHORT,
        #  "price": <fill price>, "qty": <int>}
```
- One position per engine; one decision per bar.
- Indicators: reuse `_Ema`, `_Atr` from `src/engine/v4.py` (validated conventions).
- Session-aware engines expose `feed_ts(ts)` (see `lvl_imb.py`).
- ATR is simple-rolling-mean true-range; never substitute Wilder (shifts trades).

---

## 3. Status taxonomy

`SPEC_ONLY` → idea/engine only · `FINDING` → has a result, sub-gate · `CANDIDATE` →
passed core gates, paper-eligible · `FROZEN` → rules locked, in OOS/shadow ·
`FALSIFIED` → failed, recorded (first-class) · `SUPERSEDED` / `PARKED` → replaced/shelved.
Long-only statuses are **REGIME-CONDITIONAL**, tagged as such (rule 6).

---

## 4. Strategy generation (systematic ideation)

Generate candidates, don't wait for inspiration:
1. **Families to mine** — LOCATION: order-block zones, prior session H/L, PD-mid,
   liquidity sweeps/reclaims. TIMING: session opens (NY ORB), MOC/gamma windows,
   first-overnight-break commitment. STRUCTURE: shock continuation, VWAP mean-reversion
   on balance days. REGIME: the same signal long in up-tape / short in down-tape (the
   06-26 finding: shorts lose up-tape, win down-tape).
2. **Variant sweeps** — given a base engine, sweep its key parameter (k, timeframe,
   band, stop) like `research/multi_engine_fidelity.py` and `disaster_stop_sweep.py`.
   Generates a family of testable configs automatically.
3. **Timing variants** — for any signal, always test anticipatory / confirmed / delayed
   before falsifying (this is how V4's anticipatory variant beat the bare cross).

---

## 5. Anti-patterns (already falsified — do not re-propose without a new angle)

- **Bare indicator triggers**, especially **EMA crosses** — `EMA_CROSS_CONFIRMED`
  −2,307 pt; `EMA_CROSS_9_50` backtest PF 0.74 / −$40k DD; **live −$5,380** (68% loss,
  whipsawed). Indicators are *context*, not *triggers*.
- **Volume-confirm filters** — repeatedly reduce edge (OB_NYOPEN_VOLUME_CONFIRM).
- **Tuned high PF on small n** — compresses toward ~1.0 OOS (V4-5m: 16.0 IS → 0.99 blind).
- **No disaster-stop assumption ≠ free** — but also, adding a stop to a reversion edge
  can *hurt* (fade disaster-stop sweep: every stop cut PF below stopless).

---

## 6. Tooling map

| Tool | Purpose |
|---|---|
| `src/backtest/harness.py` | event-driven backtest; long+short; same code as live |
| `src/backtest/drift_control.py` | random same-session drift benchmark |
| `research/validate_strategy.py` | **one-command gate battery** for any engine |
| `research/multi_engine_fidelity.py` | regenerate the book's backtest numbers |
| `src/bridge/engine_registry.py` | registry of deployed engines + gate_status |
| `multi_engine_bridge.py` | live paper runner (IBKR), all engines, all timeframes |
| `trade_log.py` | **authoritative** broker-truth ledger → TRADES.md |
| `session_report.py` | end-of-session report (P&L + slippage + findings) |
| `strategy_vault.json` / `STRATEGY_VAULT.md` | the registry of all results |

---

## 7. Add-a-strategy checklist

1. `cp src/engine/_template_engine.py src/engine/<name>.py`; implement `on_bar`.
2. `python research/validate_strategy.py src.engine.<name>:MyEngine` → read the gates.
3. Record the result (pass OR fail) in the vault.
4. If candidate: add an `EngineSpec` to `engine_registry.py` with honest `gate_status`.
5. Forward-test on paper; review via `session_report.py`; promote or kill.

---

## 8. Codified lessons (this deployment, learned live)

- **Backtest before deploy, always.** The EMA cross was deployed by request, backtested
  FALSIFIED, and bled −$5,380 live exactly as predicted.
- **Broker is the only truth for P&L.** The bridge's `pnl_pts` is delayed-data fiction
  (logged +88 pt on a trade the broker filled −$14). Read P&L from `trade_log.py`.
- **Delayed data corrupts the test, not just the marks.** ~70 pt avg entry slippage
  (max 178) exceeds most strategies' edge → forward results carry a slippage-sized error
  bar. A live data feed is the #1 lever on signal quality.
- **Regime flips the sign.** Short mirrors lost in the up-tape, won in the down-tape.
  Tag every long-only verdict as regime-conditional.
- **Reconcile to the broker.** The bridge fires-and-assumes; overnight order rejections
  (TIF preset, Error 10349) diverged its state from the broker. Fill-reconciliation is
  required before a result is trusted.

---

## 9. Known infrastructure gaps (block trustworthy results)

- [ ] **Live data feed** — biggest lever (kills the 70 pt slippage error bar).
- [ ] **Fill-reconciliation** in the bridge — so internal state can't diverge.
- [ ] **TIF/order-preset** fix — stop overnight Error 10349 rejections.
- [ ] **Position-netting** in the risk manager — prerequisite before multi-engine capital.
- [ ] **Reliable uptime** (cloud + IBC) — can't improve what doesn't run.
