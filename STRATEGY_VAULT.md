# Strategy Vault — NQ Autonomous Trading System
**Updated:** 2026-06-15 · All results net of 1.0 pt RT friction · Long-only unless noted
**$ convention:** legacy EMA/zone rows are NQ points ($20/pt); the new databento OB + V4-OOS rows report **MNQ prop dollars ($2/pt)** for $2K-limit fit. Points are instrument-agnostic; watch the multiplier when comparing $ figures.

## Status board

| ID | Strategy | TF | Status | n | Win% | Total pts | PF | MaxDD | Sharpe |
|---|---|---|---|---|---|---|---|---|---|
| MEANREV_FADE_2M | Mean-rev fade (3-ATR below EMA9) ★NEW | 2m | **CANDIDATE** (verified in-repo; full match) | 103 blind | 72% | +4,379 blind | **5.27** blind / 5.06 full (drift 0.75) | −245pt (−$491, fits $2K ✓) | 4.7 |
| OB_NYOPEN_BULL_1M | NY-open bullish OB reversion | 1m | **FALSIFIED** (single-entry; re-entry too) | 164 | 38% | −150 | 0.94 | — | — |
| EMA_PROX_V4_5M | Proximity + acceleration | 5m | **FROZEN — ⚠ OOS FAILED** | 22 | 55% | +5,461 IS | 16.0 IS / **2.39** OOS / 0.99 blind-window | −212 IS / **−$2,582 OOS (>$2K ✗)** | 5.0 |
| EMA_PROX_V4_15M | Proximity + accel (frozen 15m base) | 15m | CANDIDATE (verified, ⚠ low-n) | 19 | 47% | +4,188 | **3.57** (claim 3.67 ✓) / 1.91 blind | **−$989 (fits $2K ✓)** | 6.0 |
| LVL_IMB_LONDON_5M | London zones, NY tap, multi-touch | 5m | **FINDING** (blind PF 2.16 ✓ but 70% conc) | 69 blind | 44% | +653 blind | **2.16** blind / 3.22 full | −121pt (fits $2K ✓) | 4.7 |
| EMA_PROX_V4_15M_K075 | Prox + accel, slow | 15m | CANDIDATE | 21 | 48% | +6,265 | 4.6 | −980 | 2.0 |
| EMA_PROX_V0B_5M | Proximity base k=0.75 | 5m | CANDIDATE | 40 | 45% | +4,380 | 3.1 | −1,248 | 3.8 |
| EMA_PROX_V4_15M_K15 | Prox + accel | 15m | CANDIDATE | 45 | 47% | +3,184 | 2.1 | −922 | 1.9 |
| LVL_IMB_ASIA_5M | Asia zones, multi-touch | 5m | **FINDING** (under-powered: blind n=9) | 9 blind | 44% | +275 blind | 8.83 blind (n=9!) / 6.90 full | −87pt | 9.2 |
| SHOCK_V1 | Shock continuation (UP+E3) | 1m | **FINDING** (unblocked; UP-shock edge, sub-gate) | 45 ev | 49% (E3) | +850 (UP/E3) | **3.6** (UP/E3); DOWN dead | — | — |
| DAY_MAP_V1 | Session H/L interaction map | 15m | FINDING (context) | 223d | — | — | — | — | — |
| EMA_PROX_V0_15M_K15 | Ablation control (no accel) | 15m | FINDING | 57 | 44% | +2,424 | 1.6 | −1,623 | 1.1 |
| EMA_PROX_V4_1M_12MO | V4 at 1-min (exploratory) | 1m | SPEC ONLY (edge fails: PF 1.3 full / 1.1 OOS) | 327 | 46% | +3,596 | 1.3 | −1,909 | 1.3 |
| EMA_PROX_V4_SWING | Multi-day swing variant | 5m | PARKED (merge w/ V4_5M) | 22 | — | — | 7.6–16.5 | — | — |
| OB_STRICT_SINGLE_TOUCH | Strict-mitigation OB | both | SUPERSEDED | — | — | — | — | — | — |
| EMA_CROSS_CASCADE_RSI55 | Cross cascade 3m>5m>15m 7x50 +RSI55 (operator-ext) | multi | FINDING (low-freq, ~80/yr; UNVERIFIED) | — | — | — | 2.36 floor | — | — |
| EMA_CROSS_CONFIRMED | Crossover at confirmed cross | 5m | **FALSIFIED** | 511 | 27% | −2,307 | 0.89 | −3,216 | — |

## ⚠ 12-month databento OOS update (2026-06-15)
Exchange-direct 1m MNQ (352,695 bars, Jun 2025–Jun 2026, with volume, front-month U5/Z5/H6/M6) is now the **primary dataset** and gave the **first true out-of-sample** test (vault V4 was tuned only on Mar–Jun 2026). The deployment lens is the **$2K trailing prop limit** — PF means little if max DD blows the account.
- **★ NEW — OB_NYOPEN_BULL_1M (CANDIDATE, operator external research):** NY-open bullish order-block reversion on 1m. **n=798, PF 2.26, +$15,968, max DD only −$323, 13/13 green months**, beats its structural drift control (2.26 vs 0.90). **Decisive property: the −$323 DD fits the $2K prop limit** — unlike V4 5m. Best window 09:30–09:50. Two ablations FALSIFIED: volume-confirming the displacement leg reduced edge (`OB_NYOPEN_VOLUME_CONFIRM`); the 09:50 macro window was weakest, not strongest (`OB_NYOPEN_MACRO_WINDOW`). *Operator-reported, not yet reproduced in-repo — regression test = task T24.*
- **V4 OOS honest numbers (validated):** **V4_long_5m OOS PF = 2.39** (not the in-sample 5.66/16.0), and its **max DD −$2,582 EXCEEDS the $2K prop limit** → not prop-deployable as-is. **V4_long_15m OOS PF 3.67 with only −$1,080 DD → fits the limit** and is the prop-viable EMA_PROX timeframe. Within the 5m OOS, the genuinely-unseen Aug 2025–Feb 2026 sub-window was PF 0.99 (break-even) and Feb 2026 correction was all losers — the 5m edge is up-tape regime-conditional. Recorded as `oos_validation` on EMA_PROX_V4_5M.
- **V4 at 1m does not work** (PF 1.29 full / 1.07 blind; no k rescues it) — `EMA_PROX_V4_1M_12MO`, SPEC_ONLY.
- **SHOCK_V1 unblocked → FINDING.** UP-shock + E3 (extreme-break) PF 3.60 (+850pt, n=33), beats E1 baseline (0.97) and random drift (0.77). DOWN-shocks have no continuation edge (all PF<1) — fade/skip in this up-tape. UP n=45 < 50-event gate → reports, not promoted; needs more events + gamma feed + slippage model + shadow mode.

## Key validated findings (cross-strategy)
1. **Acceleration condition** (ddGap>0): PF 1.55→2.12 and halves max loser; replicated on both timeframes.
2. **Multi-touch zone survival** (die on close-through only): resurrects Asia zones, adds ~100 London events; zones valid through ~2 interactions, 2+ pre-NY touches turn negative.
3. **Sweep-tap inversion:** tap bar that also sweeps the London extreme kills reversion (MFE/MAE 0.18) — skip filter.
4. **Day-map:** first overnight break ≈ commits the day (opposite side taken 13–15%); London hold→85%/79% NY draws; AM→PM persistence 72%/58%; non-committed-London-day suppressor (trend systems PF 0.60 there).
5. **Rising 200EMA gate:** LVL_IMB PF 3.21→4.35. EMA state = context: validated. EMA cross = trigger: falsified.
6. **Right-tail exits:** trail >> fixed R everywhere tested (zone engine: 2R=+388, 3R=+590, trail=+1,099 on identical entries).
7. **Honest OOS expectation — now confirmed on hard data:** the tuned 5m PFs (3–16) do not compress to ~2, they compress to **~1.0 (break-even)** on genuinely-unseen months. V4_5M blind OOS (Aug 2025–Feb 2026) = PF 0.99; OOS/IS ratio 0.18–0.20. Feb 2026 correction = all losers. **The EMA_PROX edge is regime-conditional (up-tape only), not a standalone long-only edge.** Deploy only with a regime gate that kills it in corrections.
8. **Shock continuation is real on the UP side (new):** 4σ/3×-volume UP-shocks continue past their extreme — E3 entry PF 3.6 vs random 0.77. DOWN-shocks revert (no continuation) in the current up-tape. Right-tail capture, lumpy, sub-gate sample — promising hypothesis, not yet validated.
9. **The unit of edge is the deployment decision, not PF (new, decisive):** max drawdown vs the $2K prop limit now ranks the book. OB_NYOPEN_BULL_1M (DD −$323) and V4-15m (DD −$1,080) FIT and are deployable; V4-5m (DD −$2,582) does NOT, despite higher headline PF. A lower-PF, low-DD strategy that fits the account beats a high-PF one that blows it.
10. **Volume-confirm filters keep failing:** confirming the OB displacement leg by volume reduced edge (OB_NYOPEN_VOLUME_CONFIRM falsified) — same lesson as EMA-cross triggers. Edge is in location + timing, not indicator/volume confirmation.

## Open risks / blockers
- **V4_5M failed blind OOS** (PF→1.0 on Aug2025–Feb2026; −729 in Feb). Do NOT deploy unconditional long-only. Needs regime gate + formal demotion via T11.
- ~~No down-regime test of any 5m config~~ **RESOLVED:** 12mo databento covers Aug2025–Feb2026 incl. the Feb correction; V4 bled through it as feared.
- **No disaster stop** in EMA_PROX exits (V0b −1,210 single trade). Test structural brake — even more urgent given OOS DD −1,245.
- **Short mirrors untested** (not falsified) — and now testable on the Aug–Feb databento window (DOWN-shock already shown to fade).
- ~~SHOCK_V1 blocked on 1-min + volume data~~ **RESOLVED** (databento); now FINDING, UP-shock E3 sub-gate.
- 15m CANDIDATE configs not yet re-run on databento OOS — next validation target.
- Position-netting logic required in risk manager before multi-engine book goes live.

## Process rules (binding on research loop)
- Sweep timing variants before any FALSIFIED verdict.
- Drift control (random same-session entries) mandatory; B&H benchmark retired per operator.
- Definitions frozen before OOS; no re-tuning against validation data.
- Promotion path: frozen config → blind OOS → shadow mode (paper) → capital.
