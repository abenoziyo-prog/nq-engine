# NQ Engine — Paper Trade Log

Account **DUQ794374** (IBKR paper) · MNQU6 (MNQ Sep 2026) · $2/pt · NetLiq $1000590.88  
Source: IB broker execution record (authoritative), via `trade_log.py`.  
_Updated 2026-06-24 19:37 UTC. Paper P&L flatters real (optimistic fills + delayed data)._

## Closed trades
| # | Entry (UTC) | Exit (UTC) | Strategy | Side | Entry | Exit | Pts | $ | Held |
|--:|---|---|---|---|--:|--:|--:|--:|---|
| 1 | 2026-06-24 06:58 | 09:32 | MEANREV_FADE_2M_SHORT | SHORT | 29832.75 | 29798.25 | +34.50 | +69 | 2:34:01 |
| 2 | 2026-06-24 14:43 | 14:43 | (manual/external) | LONG | 29725.50 | 29724.00 | -1.50 | -3 | 0:00:01 |

**Total closed: +66 USD (paper) · 2 round-trips**

## Open positions
- OPEN LONG 1 @ 29389.00 (entry 19:29)

## Armed engines (potential upcoming)
16 live: 9 long + 7 short mirrors (UNTESTED), across 2m/5m/15m. They fire only on their conditions (fade ≥3-ATR stretch; EMA_PROX proximity+accel; LVL NY-session zone tap). SHOCK_V1 disabled (no volume feed). See STRATEGY_VAULT.md for specs.

---
_Regenerate: `.venv/bin/python trade_log.py` (refreshes this file). Drive copy refreshed on request._
