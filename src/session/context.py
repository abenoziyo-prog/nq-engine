"""Session context state machine — single source of truth for all engines.

Consumes the bar stream, maintains levels/VWAP/session state, emits a
ContextSnapshot per bar. Globex day rolls at 18:00 ET.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

from src.data.model import (
    Bar, ContextSnapshot, GammaRegime, LevelState, Session,
    SESSION_BOUNDS_ET, ET, in_moc_window, tag_session,
)


class SessionContextMachine:
    def __init__(self):
        self.levels = LevelState()
        self._cur_session: Optional[Session] = None
        self._cur_day: Optional[str] = None        # Globex day key
        # running aggregates
        self._day_high = self._day_low = None
        self._ny_high = self._ny_low = None
        self._sess_pv = self._sess_v = 0.0         # session vwap accumulators
        self._day_pv = self._day_v = 0.0
        self._sess_high = self._sess_low = None
        # external regime inputs (set by feeds)
        self.gamma_regime: GammaRegime = GammaRegime.UNKNOWN
        self.vix_level: Optional[float] = None
        self.econ_flag: Optional[str] = None
        self.shock_regime_on: bool = False
        self.shock_direction: Optional[int] = None

    # ---- external setters (regime feeds / risk bus) ----
    def set_shock_regime(self, on: bool, direction: Optional[int] = None) -> None:
        self.shock_regime_on, self.shock_direction = on, direction

    # ---- core ----
    @staticmethod
    def globex_day_key(ts_utc: datetime) -> str:
        et = ts_utc.astimezone(ET)
        if et.time() >= time(18, 0):
            et = et + timedelta(days=1)
        return et.strftime("%Y-%m-%d")

    def on_bar(self, bar: Bar) -> ContextSnapshot:
        sess = bar.session
        day = self.globex_day_key(bar.ts)

        if day != self._cur_day:
            self._roll_day()
            self._cur_day = day
        if sess != self._cur_session:
            self._roll_session(prev=self._cur_session)
            self._cur_session = sess

        # aggregates
        self._day_high = bar.high if self._day_high is None else max(self._day_high, bar.high)
        self._day_low = bar.low if self._day_low is None else min(self._day_low, bar.low)
        self._sess_high = bar.high if self._sess_high is None else max(self._sess_high, bar.high)
        self._sess_low = bar.low if self._sess_low is None else min(self._sess_low, bar.low)
        tp = (bar.high + bar.low + bar.close) / 3.0
        self._sess_pv += tp * bar.volume; self._sess_v += bar.volume
        self._day_pv += tp * bar.volume; self._day_v += bar.volume
        if sess in (Session.NY_AM, Session.NY_PM):
            self._ny_high = bar.high if self._ny_high is None else max(self._ny_high, bar.high)
            self._ny_low = bar.low if self._ny_low is None else min(self._ny_low, bar.low)

        self.levels.session_vwap = self._sess_pv / self._sess_v if self._sess_v else None
        self.levels.day_vwap = self._day_pv / self._day_v if self._day_v else None

        return ContextSnapshot(
            ts=bar.ts,
            session=sess,
            mins_to_session_boundary=self._mins_to_boundary(bar.ts, sess),
            in_moc_window=in_moc_window(bar.ts),
            levels=self.levels,
            shock_regime_on=self.shock_regime_on,
            shock_direction=self.shock_direction,
            gamma_regime=self.gamma_regime,
            vix_level=self.vix_level,
            econ_flag=self.econ_flag,
        )

    def _roll_session(self, prev: Optional[Session]) -> None:
        if prev is Session.ASIA:
            self.levels.asia_high, self.levels.asia_low = self._sess_high, self._sess_low
        elif prev is Session.LONDON:
            self.levels.london_high, self.levels.london_low = self._sess_high, self._sess_low
        self._sess_high = self._sess_low = None
        self._sess_pv = self._sess_v = 0.0

    def _roll_day(self) -> None:
        if self._day_high is not None:
            self.levels.pdh, self.levels.pdl = self._day_high, self._day_low
            self.levels.pd_mid = (self._day_high + self._day_low) / 2.0
        if self._ny_high is not None:
            self.levels.prior_ny_high, self.levels.prior_ny_low = self._ny_high, self._ny_low
        self._day_high = self._day_low = None
        self._ny_high = self._ny_low = None
        self._day_pv = self._day_v = 0.0
        self.levels.asia_high = self.levels.asia_low = None
        self.levels.london_high = self.levels.london_low = None

    @staticmethod
    def _mins_to_boundary(ts_utc: datetime, sess: Session) -> float:
        et = ts_utc.astimezone(ET)
        for start, end, s in SESSION_BOUNDS_ET:
            if s is sess:
                end_dt = et.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
                if end_dt <= et:
                    end_dt += timedelta(days=1)
                return (end_dt - et).total_seconds() / 60.0
        return 0.0
