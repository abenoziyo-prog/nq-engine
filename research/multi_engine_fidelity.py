"""Regenerate the deploy book's numbers in-repo — the honest "what are we actually
routing to paper" check before the multi-engine bridge goes live.

For each ENABLED registry engine, run its exact configured instance through the
SAME harness on the databento bars at its timeframe, and print PF / win% / net /
maxDD / n. 'none' guessed configs: if a row's PF is wildly off its vault value, the
config is a drift bug and that engine must NOT be trusted live (CLAUDE.md amendment).

Run: .venv/bin/python research/multi_engine_fidelity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.drift_control import load_bars
from src.backtest.harness import run_backtest
from src.bridge.engine_registry import REGISTRY, enabled_specs

POINT_VALUE = 2.0
DATA = {tf: f"src/data/MNQ_{tf}m_12mo_databento.csv" for tf in (2, 5, 15)}
VAULT_PF = {  # vault reference (reconciled to the research scripts' figures)
    "MEANREV_FADE_2M": 5.06, "EMA_PROX_V4_15M": 3.57, "EMA_PROX_V4_15M_K075": 3.75,
    "EMA_PROX_V4_15M_K15": 2.53, "EMA_PROX_V4_5M": 2.39, "EMA_PROX_V0B_5M": 3.11,
    "EMA_PROX_V0_15M_K15": 1.55, "LVL_IMB_LONDON_5M": 3.21, "LVL_IMB_ASIA_5M": 6.90,
}


def run_one(spec):
    bars = load_bars(DATA[spec.tf_min])
    tup = [(b.ts, b.open, b.high, b.low, b.close) for b in bars]
    eng = spec.make()
    dg = eng.feed_ts if spec.needs_ts else None
    trades, st = run_backtest(tup, eng, friction_pts=1.0, daily_gap_fn=dg)
    return st


def main():
    print(f"{'engine':24} {'tf':>4} {'n':>5} {'win%':>5} {'net':>8} "
          f"{'PF':>6} {'maxDD$':>9} {'vaultPF':>8}  gate_status")
    print("-" * 110)
    for spec in enabled_specs():
        try:
            st = run_one(spec)
            pf = "∞" if st.pf == float("inf") else f"{st.pf:.2f}"
            vpf = VAULT_PF.get(spec.id)
            vstr = "—" if vpf is None else f"{vpf:.2f}"
            print(f"{spec.id:24} {spec.tf_min:>3}m {st.n:>5} {st.win_pct:>4.0f}% "
                  f"{st.total_pts:>+8.0f} {pf:>6} {st.max_dd*POINT_VALUE:>+9.0f} "
                  f"{vstr:>8}  {spec.gate_status}")
        except Exception as e:
            print(f"{spec.id:24} {spec.tf_min:>3}m  ERROR: {type(e).__name__}: {e}")
    # blocked engines, for the record
    for spec in REGISTRY:
        if not spec.enabled:
            print(f"{spec.id:24} {spec.tf_min:>3}m  DISABLED — {spec.blocked_reason}")
    print("\nDD$ = maxDD_pts * $2/pt (MNQ). Full-12mo window — differs from "
          "window-specific vault figures (e.g. V4_5M's 16.0 was in-sample only).")


if __name__ == "__main__":
    main()
