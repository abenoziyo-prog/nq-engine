# IBKR Paper Trading Engine — Full Startup Sequence
# Run from scratch, computer just opened.

> **Scope:** PAPER trading only (account DUQ794374). Per CLAUDE.md "Operator
> amendments", paper-order placement is authorized; live/real-money placement is
> NOT. The client (`src/bridge/ibkr_client.py`) hard-refuses live ports (7496/4001)
> and non-`DU` accounts, and stays in DRY_RUN unless `IBKR_ACCOUNT`=DU* + a paper
> port + `dry_run=False` are all set. **All steps below assume py3.11 `.venv`.**

## STEP 1 — Start IB Gateway

Open IB Gateway (Applications or Dock).
- Login with paper account credentials
- Select **Paper Trading** account type
- Confirm: API Server = connected (green), Market Data Farm = ON (green)

```zsh
lsof -nP -iTCP -sTCP:LISTEN | grep 4002
```
Expected: `JavaAppli ... TCP *:4002 (LISTEN)`

---

## STEP 2 — Open repo and activate Python environment

```zsh
cd ~/Downloads/nq-engine-build/repo
source .venv/bin/activate
python --version
```
Expected: `Python 3.11.x`

If venv is missing:
```zsh
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
pip install ib_async pandas numpy
```

---

## STEP 3 — Confirm connection + data feed

```zsh
python3 ib_test.py
```
Expected: `Connected: True  marketDataType: 3  MNQ last=XXXXX.X close=XXXXX.XX`
`bid=-1 ask=-1` is normal on delayed data.

---

## STEP 4 — Confirm account state

```zsh
python3 ib_account.py
```
Expected: Account DUQ794374, NetLiquidation ~$1,000,086, positions flat, P&L $0.0

---

## STEP 5 — Start the fade engine bridge

`ib_fade_bridge.py` imports the verified `src/engine/meanrev_fade.py` (zero drift —
proven by `tests/test_ib_fade_bridge.py::test_zero_drift_vs_harness`), aggregates
IBKR 5-sec realtime bars into true-OHLC 2-min bars, and trades it **stopless**:
entry MarketOrder only, exit on the engine's reversion signal. The disaster stop was
swept and **removed** — `research/disaster_stop_sweep.md` showed every STOP_ATR value
cuts PF below the stopless 5.06 and the stopless maxDD (−$491) already fits the $2K
prop limit.

```zsh
.venv/bin/python ib_fade_bridge.py              # PAPER LIVE (needs Gateway + .env)
.venv/bin/python ib_fade_bridge.py --dry-run    # offline replay, simulated fills
```
Leave running. Logs every bar (close/ema9/atr/dist/pos) and every fill to
`logs/paper_session_YYYYMMDD.log`. Ctrl-C flattens, cancels orders, writes a summary.

> PAPER LIVE requires `IBKR_ACCOUNT=DU*` on a paper port (4002) in `.env`; otherwise
> the client stays in DRY_RUN and the live runner refuses to start (use `--dry-run`).
> Realtime bars may not stream under delayed-only data — a known limitation; the
> dry-run path exercises the full signal/stop/order logic without Gateway.

Verify the plumbing offline anytime:
```zsh
.venv/bin/python tests/test_ibkr.py && .venv/bin/python tests/test_ib_fade_bridge.py
```

---

## STEP 6 — (Optional) Claude Code in second tab

```zsh
cd ~/Downloads/nq-engine-build/repo
source .venv/bin/activate
claude
```

---

## STEP 7 — End of session cleanup

```zsh
python3 - << 'EOF'
from ib_async import IB, MarketOrder
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=9)
acct = ib.managedAccounts()[0]
for p in ib.positions(acct):
    if p.position != 0:
        side = 'SELL' if p.position > 0 else 'BUY'
        ib.placeOrder(p.contract, MarketOrder(side, abs(p.position)))
        print(f"Flattened {p.contract.localSymbol}")
ib.sleep(2)
ib.disconnect()
print("Flat.")
EOF

git add -A && git commit -m "session: paper engine run $(date +%Y-%m-%d)" && git push
```

---

## Reference

| Item             | Value                                      |
|------------------|--------------------------------------------|
| Gateway port     | 4002 (paper)                               |
| Account          | DUQ794374                                  |
| Contract         | MNQU6 Sep 2026, conId 793356225            |
| Python           | 3.11 (.venv)                               |
| Library          | ib_async 2.1.0                             |
| Market data      | Delayed (reqMarketDataType=3)              |
| clientIds        | test=1, bridge=2, account=3, flatten=9     |

## Caveats

- Python 3.14 breaks ib_async — always use .venv (3.11)
- bid=-1 on delayed data is expected, not an error
- Historical Data Farm inactive at startup — normal
- clientId conflict after crash: wait 30s or use different clientId
- Paper P&L flatters real: optimistic fills + delayed data
- Contract rollover: switch to MNQZ6 (conId 815824267) after 2026-09-18
