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


# NOTE on EMA_PROX configs: vault rules say "stop: none" but V4Engine defaults
# stop_atr=4.0 (an active catastrophe brake). These configs are BEST-INFERRED from
# the vault rule text and MUST be reconciled against vault PF by the fidelity
# report before being trusted live (CLAUDE.md: "a guessed config is a drift bug").
REGISTRY: list[EngineSpec] = [
    EngineSpec("MEANREV_FADE_2M", lambda: MeanRevFadeEngine(MeanRevConfig()), 2,
               "CANDIDATE (verified PF 5.06)"),
    EngineSpec("EMA_PROX_V4_15M", lambda: V4Engine(V4Config()), 15,
               "CANDIDATE (OOS PF 3.57, fits $2K)"),
    EngineSpec("EMA_PROX_V4_15M_K075", lambda: V4Engine(V4Config(k_fixed=0.75)), 15,
               "CANDIDATE (low-n)"),
    EngineSpec("EMA_PROX_V4_15M_K15", lambda: V4Engine(V4Config(k_fixed=1.5)), 15,
               "CANDIDATE"),
    EngineSpec("EMA_PROX_V4_5M", lambda: V4Engine(V4Config()), 5,
               "FROZEN/OOS-FAILED, DD>$2K — observe failure only"),
    EngineSpec("EMA_PROX_V0B_5M", lambda: V4Engine(V4Config(k_fixed=0.75, accel=False)), 5,
               "CANDIDATE, DD>$2K — observe"),
    EngineSpec("EMA_PROX_V0_15M_K15", lambda: V4Engine(V4Config(k_fixed=1.5, accel=False)), 15,
               "FINDING — ablation control (not a strategy)"),
    EngineSpec("LVL_IMB_LONDON_5M",
               lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.LONDON)), 5,
               "FINDING (high concentration)", needs_ts=True),
    EngineSpec("LVL_IMB_ASIA_5M",
               lambda: LvlImbEngine(LvlImbConfig(formation_session=Session.ASIA)), 5,
               "FINDING (underpowered, blind n≈9)", needs_ts=True),
    EngineSpec("SHOCK_V1", lambda: None, 1,
               "FINDING (sub-gate)", enabled=False,
               blocked_reason="live delayed feed carries no volume; needs Bar.volume "
                              "+ ShockDetector + gamma regime"),
]


def enabled_specs() -> list[EngineSpec]:
    return [s for s in REGISTRY if s.enabled]
