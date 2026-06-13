# NQ Autonomous Trading System

Session-context conditioned, multi-engine NQ futures system with continuous research loop.

## Engines (v1)
| ID | Engine | Class | Status |
|---|---|---|---|
| `SHOCK_v1` | Shock continuation (price-derived, cause-agnostic) | Right-tail | Spec complete |
| `MOC_v1` | 15:30–16:00 MOC/gamma flows | Structural flow | Spec pending |
| `LVL_v1` | Level sweep/reclaim mechanics (Asia/London H-L, PDH/PDL, PD-mid, prior NY H-L) | Liquidity | Spec pending |
| `MR_v1` | Regime-gated VWAP mean reversion | Balance days | Spec pending |
| `ORB_v1` | NY ORB conditioned on overnight context | Conditional breakout | Spec pending |

## Architecture

```
                ┌────────────────────────────────────────────┐
                │              DATA LAYER                    │
                │  live ws (Schwab/ToS paper → later real)   │
                │  historical: parquet/duckdb, session-tagged│
                └───────────────┬────────────────────────────┘
                                │ Bar/Tick events
                ┌───────────────▼────────────────┐
                │   SESSION CONTEXT STATE MACHINE │  ← single source of truth
                │  session, levels, vwap state,   │     for ALL engines
                │  shock regime, econ calendar,   │
                │  gamma/vix regime               │
                └───────────────┬────────────────┘
                                │ ContextSnapshot
        ┌──────────┬────────────┼────────────┬──────────┐
     SHOCK_v1   MOC_v1       LVL_v1       MR_v1      ORB_v1
        └──────────┴────────────┼────────────┴──────────┘
                                │ Signals
                ┌───────────────▼────────────────┐
                │          RISK MANAGER           │  hard limits, kill switch,
                │  (shock interlock lives here)   │  per-account prop rules
                └───────────────┬────────────────┘
                                │ Orders
                ┌───────────────▼────────────────┐
                │        EXECUTION LAYER          │  brackets, OCO, reconciliation
                └────────────────────────────────┘

  RESEARCH LOOP (separate process): logs → EOD stats → LLM hypothesis
  → backtest queue → shadow mode → promotion gate → allocator
```

**Invariant #1:** identical strategy code runs in backtest and live. The engine
classes consume the same event stream; only the data source differs.

**Invariant #2:** detection/trigger parameters are fixed a priori and version-
controlled. Changes go through the research loop, never hand-edited live.

## Repo layout
```
config/          parameters (yaml), per-engine, versioned
docs/            specs — one per engine + data schema
src/data/        feeds, session tagger, historical store
src/session/     context state machine
src/detector/    shock detector
src/backtest/    event-driven engine, stats, walk-forward
src/risk/        risk manager, prop-account rule encodings
tests/           unit tests incl. detector golden cases
```

## Paper trading
Thinkorswim paper account via Schwab API (existing infra from 0DTE engine
reusable: auth, token refresh, streaming). Note ToS paper fills are optimistic —
treat paper P&L as signal-validation only; slippage audit happens on first
live sim with real fills.

## Build order
1. Data schema + session tagger (blocks everything; ready before data lands)
2. Session context state machine
3. Shock detector + event labeler (runs on historical data day one)
4. Backtest engine core
5. Schwab streaming adapter (paper)
6. Remaining engine specs → implementations
