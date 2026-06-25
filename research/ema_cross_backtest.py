"""EMA_CROSS_9_50 backtest — operator-requested EMA9/50 cross (5m), long+short.

Result: FALSIFIED. Every config loses heavily (PF ~0.74, ~-$37k/yr, -$40k DD on MNQ).
Confirms the vault's prior EMA-cross falsification. Naive EMA crosses get whipsawed;
the eyeballed winners don't pay for the chop. Logged so the idea isn't rediscovered.

Run: .venv/bin/python research/ema_cross_backtest.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest
from src.engine.ema_cross import EmaCrossEngine, EmaCrossConfig

bars = load_bars("src/data/MNQ_5m_12mo_databento.csv")
tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
print(f"5m bars: {len(tup)}  {bars[0].ts.date()}..{bars[-1].ts.date()}\n")
print(f"{'config':34} {'n':>5} {'win%':>5} {'net pt':>8} {'PF':>6} {'maxDD$':>9}")
print("-" * 74)

CONFIGS = [
    ("band=0 mom=0 (on-cross flip)",     EmaCrossConfig()),
    ("band=0 mom=0.5 (momentum filter)", EmaCrossConfig(momentum_min=0.5)),
    ("band=0 mom=1.0",                   EmaCrossConfig(momentum_min=1.0)),
    ("band=2 mom=0 (anticipate 2pt)",    EmaCrossConfig(band=2.0)),
    ("band=5 mom=0.5 (anticip+mom)",     EmaCrossConfig(band=5.0, momentum_min=0.5)),
]
for name, cfg in CONFIGS:
    tr, st = run_backtest(tup, EmaCrossEngine(cfg), friction_pts=1.0)
    pf = "inf" if st.pf == float("inf") else f"{st.pf:.2f}"
    print(f"{name:34} {st.n:>5} {st.win_pct:>4.0f}% {st.total_pts:>+8.0f} {pf:>6} {st.max_dd*2:>+9.0f}")
print("\nVERDICT: FALSIFIED — all configs PF<0.75, deep negative, large DD. Do not deploy.")
