"""Core data model: bars, session tagging, context snapshot.

Every bar is enriched at ingest time with session context — these are
first-class data, not derived at strategy time (Invariant from spec).
All timestamps are US/Eastern wall-clock for session logic, stored UTC.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class Session(str, Enum):
    ASIA = "ASIA"          # 18:00 - 03:00 ET
    LONDON = "LONDON"      # 03:00 - 09:30 ET
    NY_AM = "NY_AM"        # 09:30 - 12:00 ET
    NY_PM = "NY_PM"        # 12:00 - 17:00 ET (MOC window 15:30-16:00 flagged separately)
    CLOSED = "CLOSED"      # 17:00 - 18:00 ET maintenance


SESSION_BOUNDS_ET = [
    (time(18, 0), time(3, 0), Session.ASIA),
    (time(3, 0), time(9, 30), Session.LONDON),
    (time(9, 30), time(12, 0), Session.NY_AM),
    (time(12, 0), time(17, 0), Session.NY_PM),
    (time(17, 0), time(18, 0), Session.CLOSED),
]

MOC_WINDOW = (time(15, 30), time(16, 0))


def tag_session(ts_utc: datetime) -> Session:
    t = ts_utc.astimezone(ET).time()
    for start, end, sess in SESSION_BOUNDS_ET:
        if start <= end:
            if start <= t < end:
                return sess
        else:  # wraps midnight (ASIA)
            if t >= start or t < end:
                return sess
    return Session.CLOSED


def in_moc_window(ts_utc: datetime) -> bool:
    t = ts_utc.astimezone(ET).time()
    return MOC_WINDOW[0] <= t < MOC_WINDOW[1]


@dataclass(slots=True)
class Bar:
    ts: datetime              # bar close, UTC
    open: float
    high: float
    low: float
    close: float
    volume: int
    session: Session = Session.CLOSED

    def __post_init__(self):
        if self.session is Session.CLOSED:
            self.session = tag_session(self.ts)


class GammaRegime(str, Enum):
    SHORT = "SHORT"
    LONG = "LONG"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class LevelState:
    """Reference levels, maintained by the session context machine."""
    pdh: Optional[float] = None            # prior day high (Globex day)
    pdl: Optional[float] = None
    pd_mid: Optional[float] = None
    prior_ny_high: Optional[float] = None  # prior NY-session-only high
    prior_ny_low: Optional[float] = None
    asia_high: Optional[float] = None
    asia_low: Optional[float] = None
    london_high: Optional[float] = None
    london_low: Optional[float] = None
    session_vwap: Optional[float] = None
    day_vwap: Optional[float] = None


@dataclass(slots=True)
class ContextSnapshot:
    """Single source of truth handed to every engine on every event."""
    ts: datetime
    session: Session
    mins_to_session_boundary: float
    in_moc_window: bool
    levels: LevelState
    shock_regime_on: bool = False
    shock_direction: Optional[int] = None      # +1 / -1
    gamma_regime: GammaRegime = GammaRegime.UNKNOWN
    vix_level: Optional[float] = None
    econ_flag: Optional[str] = None            # CPI/PPI/FOMC/NFP within ±30min

    def dist_to(self, level: Optional[float], price: float) -> Optional[float]:
        return None if level is None else price - level
