"""Golden tests: session tagging, day roll, and shock detector trigger math."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.data.model import Bar, Session, tag_session, in_moc_window
from src.session.context import SessionContextMachine
from src.detector.shock import ShockDetector, ShockParams

ET = ZoneInfo("America/New_York")


def et(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


def test_session_tags():
    assert tag_session(et(2026, 6, 10, 20, 0)) is Session.ASIA
    assert tag_session(et(2026, 6, 11, 2, 59)) is Session.ASIA
    assert tag_session(et(2026, 6, 11, 3, 0)) is Session.LONDON
    assert tag_session(et(2026, 6, 11, 9, 29)) is Session.LONDON
    assert tag_session(et(2026, 6, 11, 9, 30)) is Session.NY_AM
    assert tag_session(et(2026, 6, 11, 13, 0)) is Session.NY_PM
    assert tag_session(et(2026, 6, 11, 17, 30)) is Session.CLOSED
    assert in_moc_window(et(2026, 6, 11, 15, 45))
    assert not in_moc_window(et(2026, 6, 11, 16, 0))


def _bar(ts, o, h, l, c, v=1000):
    return Bar(ts=ts, open=o, high=h, low=l, close=c, volume=v)


def test_day_roll_sets_pdh_pdl():
    m = SessionContextMachine()
    # day 1: two bars
    m.on_bar(_bar(et(2026, 6, 10, 19, 0), 21000, 21100, 20990, 21050))
    m.on_bar(_bar(et(2026, 6, 11, 10, 0), 21050, 21200, 21040, 21150))
    # cross into next globex day (>= 18:00 ET)
    snap = m.on_bar(_bar(et(2026, 6, 11, 18, 5), 21150, 21160, 21140, 21155))
    assert snap.levels.pdh == 21200
    assert snap.levels.pdl == 20990
    assert snap.levels.pd_mid == (21200 + 20990) / 2


def test_asia_levels_roll_into_london():
    m = SessionContextMachine()
    m.on_bar(_bar(et(2026, 6, 10, 20, 0), 21000, 21080, 20950, 21020))
    m.on_bar(_bar(et(2026, 6, 11, 1, 0), 21020, 21060, 20940, 21000))
    snap = m.on_bar(_bar(et(2026, 6, 11, 3, 5), 21000, 21010, 20995, 21005))
    assert snap.session is Session.LONDON
    assert snap.levels.asia_high == 21080
    assert snap.levels.asia_low == 20940


def test_shock_detector_fires_on_impulse():
    params = ShockParams(window_s=180, k_sigma=4.0, vol_multiple=3.0, min_abs_move_pct=0.35)
    det = ShockDetector(params, vol_baseline_fn=lambda ts: 3000.0, sigma_floor=1e-5)
    m = SessionContextMachine()

    t0 = et(2026, 6, 11, 10, 0)
    px = 21000.0
    ev = None
    # 30 quiet minutes to seed EWMA sigma (tiny moves)
    for i in range(30):
        b = _bar(t0 + timedelta(minutes=i), px, px + 2, px - 2, px + (0.5 if i % 2 else -0.5), v=1000)
        ev = det.on_bar(b, m.on_bar(b))
        assert ev is None
    # impulse: +100 pts (~0.48%) over 3 bars with 5x volume
    triggers = []
    for j, chg in enumerate([40, 35, 25]):
        px += chg
        b = _bar(t0 + timedelta(minutes=30 + j), px - chg, px + 1, px - chg - 1, px, v=5000)
        r = det.on_bar(b, m.on_bar(b))
        if r is not None:
            triggers.append(r)
    assert triggers, "shock should trigger"
    assert len(triggers) == 1, "cooldown must suppress re-triggers within impulse"
    ev = triggers[0]
    assert ev.direction == 1
    assert ev.impulse_range_pts > 70  # fires mid-impulse once 0.35% floor cleared
    assert ev.shock_sigma >= 4.0

    # cooldown: immediate same-direction follow-up must not re-trigger
    px += 60
    b = _bar(t0 + timedelta(minutes=33), px - 60, px, px - 61, px, v=6000)
    assert det.on_bar(b, m.on_bar(b)) is None


if __name__ == "__main__":
    test_session_tags()
    test_day_roll_sets_pdh_pdl()
    test_asia_levels_roll_into_london()
    test_shock_detector_fires_on_impulse()
    print("ALL TESTS PASSED")
