# Strategy Vault — NQ Autonomous Trading System
**Updated:** 2026-06-12 · All results net of 1.0 pt RT friction · 1 NQ contract ($20/pt) · Long-only unless noted

## Status board

| ID | Strategy | TF | Status | n | Win% | Total pts | PF | MaxDD | Sharpe |
|---|---|---|---|---|---|---|---|---|---|
| EMA_PROX_V4_5M | Proximity + acceleration | 5m | **FROZEN → OOS** | 22 | 55% | +5,461 | 16.0 | −212 | 5.0 |
| LVL_IMB_LONDON_5M | London zones, NY tap, multi-touch | 5m | **FROZEN → OOS** | 151 | 35% | +4,121 | 3.2 (4.4 w/ EMA gate) | −290 | — |
| EMA_PROX_V4_15M_K075 | Prox + accel, slow | 15m | CANDIDATE | 21 | 48% | +6,265 | 4.6 | −980 | 2.0 |
| EMA_PROX_V0B_5M | Proximity base k=0.75 | 5m | CANDIDATE | 40 | 45% | +4,380 | 3.1 | −1,248 | 3.8 |
| EMA_PROX_V4_15M_K15 | Prox + accel | 15m | CANDIDATE | 45 | 47% | +3,184 | 2.1 | −922 | 1.9 |
| LVL_IMB_ASIA_5M | Asia zones, multi-touch | 5m | CANDIDATE | 49 | 20% | +838 | 2.1 | −271 | — |
| DAY_MAP_V1 | Session H/L interaction map | 15m | FINDING (context) | 223d | — | — | — | — | — |
| EMA_PROX_V0_15M_K15 | Ablation control (no accel) | 15m | FINDING | 57 | 44% | +2,424 | 1.6 | −1,623 | 1.1 |
| SHOCK_V1 | Shock continuation | 1m | SPEC ONLY (blocked: needs 1m+vol) | — | — | — | — | — | — |
| EMA_PROX_V4_SWING | Multi-day swing variant | 5m | PARKED (merge w/ V4_5M) | 22 | — | — | 7.6–16.5 | — | — |
| OB_STRICT_SINGLE_TOUCH | Strict-mitigation OB | both | SUPERSEDED | — | — | — | — | — | — |
| EMA_CROSS_CONFIRMED | Crossover at confirmed cross | 5m | **FALSIFIED** | 511 | 27% | −2,307 | 0.89 | −3,216 | — |

## Key validated findings (cross-strategy)
1. **Acceleration condition** (ddGap>0): PF 1.55→2.12 and halves max loser; replicated on both timeframes.
2. **Multi-touch zone survival** (die on close-through only): resurrects Asia zones, adds ~100 London events; zones valid through ~2 interactions, 2+ pre-NY touches turn negative.
3. **Sweep-tap inversion:** tap bar that also sweeps the London extreme kills reversion (MFE/MAE 0.18) — skip filter.
4. **Day-map:** first overnight break ≈ commits the day (opposite side taken 13–15%); London hold→85%/79% NY draws; AM→PM persistence 72%/58%; non-committed-London-day suppressor (trend systems PF 0.60 there).
5. **Rising 200EMA gate:** LVL_IMB PF 3.21→4.35. EMA state = context: validated. EMA cross = trigger: falsified.
6. **Right-tail exits:** trail >> fixed R everywhere tested (zone engine: 2R=+388, 3R=+590, trail=+1,099 on identical entries).
7. **Honest OOS expectation:** tuned 5m PFs (3–16) compress toward PF~2, Sharpe~2 on unseen months (15m Aug–Jan pseudo-OOS evidence). Feb 2026 = family-wide worst month; long-only bleeds in corrections.

## Open risks / blockers
- **No down-regime test of any 5m config** (dataset starts Mar 8). Dec–Mar 5m batch = top priority.
- **No disaster stop** in EMA_PROX exits (V0b −1,210 single trade). Test structural brake.
- **Short mirrors untested** (not falsified) — run on Feb window when data lands.
- SHOCK_V1 blocked on 1-min + volume data.
- Position-netting logic required in risk manager before multi-engine book goes live.

## Process rules (binding on research loop)
- Sweep timing variants before any FALSIFIED verdict.
- Drift control (random same-session entries) mandatory; B&H benchmark retired per operator.
- Definitions frozen before OOS; no re-tuning against validation data.
- Promotion path: frozen config → blind OOS → shadow mode (paper) → capital.
