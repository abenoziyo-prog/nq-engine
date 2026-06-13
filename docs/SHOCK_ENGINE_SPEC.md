# Shock Continuation Engine — Formal Specification

**Engine ID:** `SHOCK_v1`
**Instrument:** NQ (CME E-mini Nasdaq-100 futures, front month)
**Class:** Right-tail capture, regime-conditional, price-derived (cause-agnostic)

---

## 1. Detection (parameters fixed a priori — DO NOT fit to outcomes)

A **shock event** fires when ALL conditions hold within a rolling evaluation window:

| Parameter | Symbol | v1 Value | Notes |
|---|---|---|---|
| Impulse window | `W` | 180 s | Rolling, evaluated per 1-min bar close + intrabar check every 5 s |
| Sigma multiple | `k` | 4.0 | vs. rolling 1-min return sigma |
| Sigma lookback | `L` | 120 min | EWMA, half-life 30 min; floor = 0.25 × 20-day median sigma (prevents quiet-tape false fires) |
| Volume multiple | `m` | 3.0 | W-window volume vs. same-time-of-day 20-day median baseline |
| Cooldown | `C` | 30 min | No re-trigger same direction; opposite direction allowed (reversal shock) |
| Min absolute move | `A` | 0.35% | Hard floor so low-vol regimes can't fire on noise |

**Trigger:** `|P_now − P_{t−W}| ≥ max(k × σ_L × √(W/60), A × P)` AND `Vol_W ≥ m × Vol_baseline(TOD)`

Magnitude is recorded as a **feature** (`shock_sigma = move / (σ_L × √(W/60))`), not used as a filter beyond the threshold — sizing handles magnitude later via Kelly.

**Direction:** sign of the impulse. **UP and DOWN are separate setups** with independent statistics, playbooks, and promotion gates. No pooling.

## 2. Event labeling schema (every event, live or historical)

```
shock_id, ts_trigger, direction, shock_sigma, impulse_range_pts,
impulse_open, impulse_extreme, impulse_duration_s,
session (ASIA|LONDON|NY_AM|NY_PM), mins_to_session_boundary,
dist_to_PDH, dist_to_PDL, dist_to_asia_high, dist_to_asia_low,
dist_to_london_high, dist_to_london_low, dist_to_vwap_session,
vix_level, vix_1d_chg, gamma_regime (SHORT|LONG|NEUTRAL|UNKNOWN),
econ_calendar_flag (none|CPI|PPI|FOMC|NFP|other ±30min),
-- outcomes (backtest/post-hoc only):
max_continuation_pts_30m/60m/120m/to_close,
max_retrace_pct_of_impulse, time_to_50pct_retrace_s,
pullback_depth_pct, pullback_occurred_within_15m (bool),
broke_impulse_extreme_within_15m (bool)
```

Historical shock events are sampled from **>12 months** (rare event class exception), each tagged with regime so conditioning is learned, not assumed. Strategy parameters still optimize on last-12-months weighting.

## 3. State machine

```
IDLE → SHOCK_DETECTED → ARMED → IN_TRADE → MANAGING → FLAT(cooldown) → IDLE
                      ↘ EXPIRED (no entry within T_arm = 20 min) → IDLE
```

On `SHOCK_DETECTED`: broadcast `SHOCK_REGIME=ON` to the global state bus → **all other engines flatten/halt** for the cooldown window. This is a hard interlock in the risk manager, not a suggestion.

## 4. Entry schemes (bake-off — all three run in backtest, promotion picks per direction)

- **E1 IMMEDIATE:** market on trigger confirm (next 5 s). Baseline only; expected to lose the bake-off after friction.
- **E2 PULLBACK:** limit at 25–40% retrace zone of impulse leg, valid only if reached within 15 min and impulse extreme not yet broken. Misses no-pullback runners by design.
- **E3 EXTREME-BREAK:** stop order 2 ticks beyond impulse extreme, armed after a 3-min hold period, valid 20 min.
- **E4 HYBRID:** 50% E2 + 50% E3, treated as its own scheme in stats.

## 5. Stop logic (impulse-scaled, never pre-shock ATR)

- Initial stop: `0.45 × impulse_range` beyond entry-side invalidation, AND never beyond 50% retrace of the impulse leg (thesis invalidation: forced-hedging flow does not give back half the move).
- E2 entries: stop below pullback low if tighter.
- Stop is structural; no fixed-point stops anywhere in this engine.

## 6. Exit logic (right-tail capture — no fixed R targets)

- **Primary:** trail beneath 15-min swing structure (last confirmed higher-low for longs).
- **Time guard:** hard flat at session boundary following entry (Globex close, or NY close if entered NY_PM) — hedging flow is duration-bounded.
- **Scratch rule:** if neither +1×impulse_range nor stop within 60 min, exit at market (dead shock).

## 7. Regime conditioning (features, v1)

- `gamma_regime`: from daily dealer-positioning input (manual/CSV feed acceptable v1). Prior: UP-shocks in SHORT gamma = continuation; LONG gamma = fade/skip.
- `vix_level` bands: <15 / 15–22 / >22.
- Promotion may be regime-conditional (e.g., trade UP-shocks only in SHORT gamma).

## 8. Validation & promotion gate

1. ≥ 50 events per direction in sample; if fewer at k=4.0, lower k to 3.5 (pre-registered fallback, one step only).
2. Outcome stats computed per (direction × entry scheme × gamma regime) bucket; buckets with n < 25 report but don't promote.
3. Walk-forward on the 12-month optimization set; stress-window sanity pass (no-blow-up check only).
4. **Shadow mode ≥ 2 weeks live** (signals logged via paper, not traded) before capital.
5. Allocator class: `LUMPY_RIGHT_TAIL` — reduced base size, profit-banking rules, excluded from consistency-sensitive prop accounts if distribution violates their rules.

## 9. Open questions (resolve with data)

- Optimal `W`: 180 s chosen a priori; sensitivity report (60/180/300 s) is informational only — no post-hoc threshold shopping.
- Whether DOWN-shock continuation exists at all in current regime, or DOWN setup becomes a fade playbook.
- Pullback-depth distribution: does 25–40% zone match 2025–26 tape?
