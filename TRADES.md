# NQ Engine — Paper Trade Log

Account **DUQ794374** (IBKR paper) · MNQU6 (MNQ Sep 2026) · $2/pt · NetLiq $1000156.28  
Source: IB broker execution record (authoritative), via `trade_log.py`.  
_Updated 2026-06-24 23:57 UTC. Paper P&L flatters real (optimistic fills + delayed data)._

## Closed trades
| # | Entry (UTC) | Exit (UTC) | Strategy | Side | Entry | Exit | Pts | $ | Held |
|--:|---|---|---|---|--:|--:|--:|--:|---|
| 1 | 2026-06-24 06:58 | 09:32 | MEANREV_FADE_2M_SHORT | SHORT | 29832.75 | 29798.25 | +34.50 | +69 | 2:34:01 |
| 2 | 2026-06-24 14:43 | 14:43 | (manual/external) | LONG | 29725.50 | 29724.00 | -1.50 | -3 | 0:00:01 |
| 3 | 2026-06-24 19:29 | 19:42 | MEANREV_FADE_2M | LONG | 29389.00 | 29382.00 | -7.00 | -14 | 0:12:31 |
| 4 | 2026-06-24 20:16 | 22:00 | MEANREV_FADE_2M_SHORT | SHORT | 29866.00 | 30093.50 | -227.50 | -455 | 1:43:27 |
| 5 | 2026-06-24 22:33 | 23:28 | MEANREV_FADE_2M | LONG | 30067.00 | 30091.50 | +24.50 | +49 | 0:55:06 |

**Total closed: -354 USD (paper) · 5 round-trips**

## Open positions
_(none — flat)_

## Armed engines (potential upcoming)
16 live: 9 long + 7 short mirrors (UNTESTED), across 2m/5m/15m. They fire only on their conditions (fade ≥3-ATR stretch; EMA_PROX proximity+accel; LVL NY-session zone tap). SHOCK_V1 disabled (no volume feed). See STRATEGY_VAULT.md for specs.

---
_Regenerate: `.venv/bin/python trade_log.py` (refreshes this file). Drive copy refreshed on request._
