# Routine Prompt Library — Autonomous Research Loop
**Repo:** nq-engine · **Brain:** Claude (via Claude Code Routine) · **State:** strategy_vault.json

Each prompt is a standing task a scheduled Routine runs without human approval. Every prompt
ends by (a) writing results to the vault in the standardized schema and (b) emitting a brief
to the notify channel. Prompts are ordered by cadence. The agent must NEVER place or modify
live orders — research only. Execution is a separate deterministic system.

---

## TIER 1 — Daily (fires ~17:15 ET, after Globex close)

### P1 · EOD ingest + health check  [TRIGGER: schedule 17:15 ET, Mon–Fri]
```
You are the research agent for the nq-engine project. It is end of the trading day.
1. Pull today's MNQ bars (5m and 15m) from the data source in /data. If the live feed
   isn't wired yet, note "AWAITING_DATA" and skip to step 4.
2. Append today's bars to the master parquet store; run the data-quality check
   (dupes, gaps vs session calendar, OHLC integrity). Log any anomaly.
3. Recompute today's session map (Asia/London/NY H-L, day-type, first-break side,
   AM->PM result) and append to the day-map table.
4. For each FROZEN or CANDIDATE strategy in strategy_vault.json, compute today's
   would-be signals and mark-to-close P&L (paper, no execution).
5. Write a <=200-word EOD brief: regime read (daily 9x50 gap state, VIX band if available),
   any signals fired, any data anomaly, any strategy whose trailing-10-trade PF dropped
   below its kill threshold. Send to notify channel. Update vault 'last_eod' timestamp.
Do not modify any FROZEN strategy's rules. Research and report only.
```

### P2 · Live-vs-backtest drift watch  [TRIGGER: schedule 17:20 ET, Mon–Fri]
```
Compare any live/paper fills logged today (in /logs/fills) against the backtest
assumption (1pt friction, bar-close entry) for each active strategy.
1. For each fill, compute realized slippage vs assumed.
2. If median slippage over the trailing 20 fills exceeds 1.5pt for any strategy,
   raise a DRIFT_ALERT in the vault and notify: the strategy's live edge is being
   eroded by execution; recommend re-marking its expected PF.
3. If no fills today, write "no fills" and exit.
Never adjust live sizing yourself — only flag and recommend.
```

### P-FWD · LVL_IMB_LONDON_5M forward paper-log  [TRIGGER: schedule 17:25 ET, Mon–Fri, after Globex close]
```
Run the LVL_IMB_LONDON_5M forward-logging harness — its 2nd out-of-sample window,
a PAPER record of the EXACT verified frozen engine on data it has never seen.
1. Ensure today's new 5m databento bars (post 2026-06-14) are in src/data/
   (appended to the 12mo file or dropped as MNQ_5m_forward_*.csv). If none, the
   harness prints "no forward data yet" — note that and exit.
2. Run:  python -m src.research.forward_log
   It loads src/engine/lvl_imb.py with the frozen config (the blind-slice PF 2.16
   engine — do NOT change any parameter), warms it on full history, and appends
   today's would-be London trades (zone, intended stop, +1R target, mark-to-close
   outcome) to logs/forward_london.jsonl. It is idempotent (no double-logging) and
   places NO orders.
3. Read the running forward tally (logs/forward_london_tally.json): cumulative
   forward n, win%, total pts, PF, maxDD. Compare PF to the blind-slice PF 2.16.
4. Append to the daily brief: "London forward: n=<n>, PF=<pf> vs blind 2.16
   (<tracking|below>)", plus any new would-be trades today and any open MTM.
Constitution: research only, never place orders, log every result win or lose,
never tune the frozen config. The point is an honest forward track record.
```

---

## TIER 2 — Weekly (fires Sunday 12:00 ET, before the week opens)

### P3 · Walk-forward re-validation  [TRIGGER: schedule Sun 12:00 ET]
```
For each FROZEN strategy, run the frozen config (do NOT re-tune) against the most
recent out-of-sample window not yet tested (track 'last_oos_through' per strategy
in the vault).
1. Produce the standard stat block (n, win%, total, PF, maxDD, Sharpe, avg/max W/L).
2. Compare to the strategy's in-sample stats. Compute the OOS/IS PF ratio.
3. If OOS PF < 1.0 OR OOS/IS ratio < 0.4, propose status change to DEGRADED and notify.
   If OOS holds, advance 'last_oos_through' and note PASS.
4. Always run the drift control (random same-session entries) as the benchmark.
Write all results to the vault. Recommend, do not auto-promote past shadow stage.
```

### P4 · Hypothesis generation  [TRIGGER: on completion of P3]
```
Read the vault's validated findings and falsified registry. Propose 2-3 NEW testable
hypotheses for the NQ engine that:
  - are NOT in the falsified registry (check the registry rules; never re-propose
    confirmed-cross indicator triggers or anything marked FALSIFIED)
  - are expressed in session-context or structure terms (location/timing/regime),
    consistent with the project's finding that location/context carries edge and
    bare indicators do not
  - specify exact, a-priori, backtestable rules and a pre-registered sample threshold
For each, before any verdict, sweep timing variants (anticipatory/confirmed/delayed)
per the binding process rule. Write each hypothesis as a SPEC_ONLY vault entry with
status and 'next' steps. Queue them for P5. Notify with the shortlist.
```

### P5 · Backtest queue runner  [TRIGGER: on completion of P4]
```
For each SPEC_ONLY hypothesis queued by P4:
1. Implement the rules exactly as specified using the shared engine modules.
2. Backtest on the in-sample window with full friction; run the factorial sweep
   (3-5 levels per variable) and report MAIN EFFECTS, not just the top cell.
3. Run the drift control. Compute the standard stat block per config.
4. If the robust region (median across the neighborhood, not the peak) clears
   PF > 1.5 AND beats drift control, advance status SPEC_ONLY -> CANDIDATE and
   freeze the config. Else mark FALSIFIED with the reason and add to the registry.
5. Write everything to the vault. Notify with one line per hypothesis: promoted/killed + why.
Be skeptical of high PF on small n; always report effective (day-level) sample size.
```

---

## TIER 3 — Monthly (fires 1st business day, 12:00 ET)

### P6 · Regime audit + deployment review  [TRIGGER: schedule monthly]
```
1. Classify the trailing month's regime (trend/chop/correction) from daily structure
   and realized vol. Tag it in the vault's regime log.
2. For each strategy, report performance conditional on regime. Flag any strategy
   whose deploy-conditions no longer match the current regime (e.g. a long-only
   trend model in a down month) and recommend activate/deactivate to the operator.
3. Re-run the full vault status board. Promote CANDIDATE -> FROZEN_AWAITING_OOS only
   if it has cleared 2+ weeks of shadow logging. Never promote to live capital.
4. Produce a monthly report: equity-curve summary per active strategy, the regime call,
   the deploy recommendations, and the current 'rack' of ready-to-deploy models.
Notify with the report. This is a recommendation to the operator, not an action.
```

### P7 · Vault integrity + self-audit  [TRIGGER: on completion of P6]
```
Audit strategy_vault.json: every entry has a valid status, a complete stat block or a
clear reason for null, and a 'next' field. Verify no FROZEN strategy's rules were
silently changed (diff against git history). Confirm the falsified registry has not
shrunk. Confirm long-only statuses are still tagged regime-conditional, not permanent.
If any integrity issue is found, do NOT fix silently — report it to the operator with
the diff. This guards against research-loop drift from the constitution.
```

---

## Notify channel
All prompts end with a brief to the operator (Telegram/Slack/email — set in config).
Daily briefs <=200 words. Weekly/monthly may include the stat tables.
NEVER include an instruction to place a trade. Research and recommend only.
```
```
