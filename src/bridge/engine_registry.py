"""Multi-engine registry — the top-10 book the operator directed to paper
forward-test (CLAUDE.md amendment 2026-06-23, paper-only, gates waived).

Each spec carries gate_status so forward data is never mistaken for validated
edge, and `enabled`/`blocked_reason` so an engine that can't be driven by the live
feed is registered-but-off rather than silently faked.

ALL engines here are price-only or price+timestamp (consume OHLC, optionally a
session ts via feed_ts) EXCEPT SHOCK_V1, which needs volume + the shock detector
and so cannot run on the delayed last-price poll — registered, disabled.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional

from src.engine.meanrev_fade import MeanRevFadeEngine, MeanRevConfig
from src.engine.v4 import V4Engine, V4Config
from src.engine.lvl_imb import LvlImbEngine, LvlImbConfig
from src.data.model import Session


@dataclass
class EngineSpec:
    id: str
    make: Callable[[], object]      # fresh engine instance
    tf_min: int                     # bar timeframe (minutes)
    gate_status: str                # vault status — tags every fill
    enabled: bool = True
    blocked_reason: Optional[str] = None
    needs_ts: bool = False          # engine.feed_ts(ts) before on_bar (session-aware)


# EMA_PROX configs reconciled against research/task_a_v4_oos.py + task_p3_v4_15m.py
# (the scripts that produced the vault entries): the EMA_PROX family runs with NO
# catastrophe stop (stop_atr disabled) and NO daily-align sizing — the vault "stop:
# none". V4Engine's defaults (stop_atr=4.0, daily_align_size=True) must be overridden
# or the active brake skews trades. k=0.75/1.5 are FIXED-point thresholds (k_fixed).
NO_STOP = 1e9   # matches research scripts' disable sentinel
_SHORT = "SHORT MIRROR — UNTESTED (vault: short mirrors untested)"


def _v4(**kw):
    base = dict(fast=9, slow=50, atr_len=14, accel=True,
                daily_align_size=False, stop_atr=NO_STOP)
    base.update(kw)
    return lambda: V4Engine(V4Config(**base))


REGISTRY: list[EngineSpec] = [
    EngineSpec("MEANREV_FADE_2M", lambda: MeanRevFadeEngine(MeanRevConfig()), 2,
               "CANDIDATE (verified PF 5.06)"),
    EngineSpec("EMA_PROX_V4_15M", _v4(k_atr=0.02), 15,
               "CANDIDATE (OOS PF 3.57, fits $2K)"),
    EngineSpec("EMA_PROX_V4_15M_K075", _v4(k_fixed=0.75), 15,
               "CANDIDATE (low-n)"),
    EngineSpec("EMA_PROX_V4_15M_K15", _v4(k_fixed=1.5), 15,
               "CANDIDATE"),
    EngineSpec("EMA_PROX_V4_5M", _v4(k_atr=0.02), 5,
               "FROZEN/OOS-FAILED, DD>$2K — observe failure only"),
    EngineSpec("EMA_PROX_V0B_5M", _v4(k_fixed=0.75, accel=False), 5,
               "CANDIDATE, DD>$2K — observe"),
    EngineSpec("EMA_PROX_V0_15M_K15", _v4(k_fixed=1.5, accel=False), 15,
               "FINDING — ablation control (not a strategy)"),
    EngineSpec("LVL_IMB_LONDON_5M",
               lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.LONDON)), 5,
               "FINDING (high concentration)", needs_ts=True),
    EngineSpec("LVL_IMB_ASIA_5M",
               lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.ASIA)), 5,
               "FINDING (underpowered, blind n≈9)", needs_ts=True),
    # --- SHORT MIRRORS (#1 fade + #2 EMA_PROX family) -----------------------
    # UNTESTED hypothesis: vault says "short mirrors untested (not falsified)".
    # The book is long-biased because the regime is an up-tape, so expect these to
    # bleed — they run to GATHER forward data, gate-tagged, not because they're good.
    EngineSpec("MEANREV_FADE_2M_SHORT",
               lambda: MeanRevFadeEngine(MeanRevConfig(direction="short")), 2, _SHORT),
    EngineSpec("EMA_PROX_V4_15M_SHORT", _v4(k_atr=0.02, direction="short"), 15, _SHORT),
    EngineSpec("EMA_PROX_V4_15M_K075_SHORT", _v4(k_fixed=0.75, direction="short"), 15, _SHORT),
    EngineSpec("EMA_PROX_V4_15M_K15_SHORT", _v4(k_fixed=1.5, direction="short"), 15, _SHORT),
    EngineSpec("EMA_PROX_V4_5M_SHORT", _v4(k_atr=0.02, direction="short"), 5, _SHORT),
    EngineSpec("EMA_PROX_V0B_5M_SHORT", _v4(k_fixed=0.75, accel=False, direction="short"), 5, _SHORT),
    EngineSpec("EMA_PROX_V0_15M_K15_SHORT", _v4(k_fixed=1.5, accel=False, direction="short"), 15, _SHORT),

    EngineSpec("SHOCK_V1", lambda: None, 1,
               "FINDING (sub-gate)", enabled=False,
               blocked_reason="live delayed feed carries no volume; needs Bar.volume "
                              "+ ShockDetector + gamma regime"),
]


def enabled_specs() -> list[EngineSpec]:
    return [s for s in REGISTRY if s.enabled]
