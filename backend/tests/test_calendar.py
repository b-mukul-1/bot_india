"""
Tests for MarketCalendar
Verifies Indian market hours, holiday detection, mandatory square-off, and expiry shifting.
"""

import pytest
from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo
from backend.app.calendar import MarketCalendar, IST, UTC

@pytest.fixture
def calendar():
    return MarketCalendar()

def test_holiday_detection(calendar):
    # Gandhi Jayanti (2026-10-02) is a holiday
    assert calendar.is_holiday(date(2026, 10, 2)) is True
    assert calendar.is_trading_day(date(2026, 10, 2)) is False

    # Saturday is a holiday
    assert calendar.is_holiday(date(2026, 10, 3)) is True

    # Regular trading day (Wednesday 2026-10-14)
    assert calendar.is_holiday(date(2026, 10, 14)) is False
    assert calendar.is_trading_day(date(2026, 10, 14)) is True

def test_session_phases_and_squareoff(calendar):
    # 2026-10-14 is Wednesday
    # 09:10 IST - Pre-open
    dt_pre = datetime(2026, 10, 14, 9, 10, tzinfo=IST)
    state_pre = calendar.get_market_state(dt_pre)
    assert state_pre["is_open"] is False
    assert state_pre["phase"] == "PRE_OPEN"

    # 09:18 IST - Open Warmup
    dt_warmup = datetime(2026, 10, 14, 9, 18, tzinfo=IST)
    state_warmup = calendar.get_market_state(dt_warmup)
    assert state_warmup["is_open"] is True
    assert state_warmup["can_enter"] is False
    assert state_warmup["phase"] == "OPEN_WARMUP"

    # 10:30 IST - Normal Trading
    dt_trade = datetime(2026, 10, 14, 10, 30, tzinfo=IST)
    state_trade = calendar.get_market_state(dt_trade)
    assert state_trade["is_open"] is True
    assert state_trade["can_enter"] is True
    assert state_trade["must_squareoff"] is False
    assert state_trade["phase"] == "NORMAL_TRADING"

    # 14:50 IST - No New Entries
    dt_late = datetime(2026, 10, 14, 14, 50, tzinfo=IST)
    state_late = calendar.get_market_state(dt_late)
    assert state_late["is_open"] is True
    assert state_late["can_enter"] is False
    assert state_late["must_squareoff"] is False
    assert state_late["phase"] == "NO_NEW_ENTRIES"

    # 15:16 IST - Squareoff
    dt_sq = datetime(2026, 10, 14, 15, 16, tzinfo=IST)
    state_sq = calendar.get_market_state(dt_sq)
    assert state_sq["is_open"] is True
    assert state_sq["must_squareoff"] is True
    assert state_sq["phase"] == "SQUAREOFF"

    # 15:35 IST - Closed
    dt_closed = datetime(2026, 10, 14, 15, 35, tzinfo=IST)
    state_closed = calendar.get_market_state(dt_closed)
    assert state_closed["is_open"] is False
    assert state_closed["phase"] == "CLOSED_POST_SESSION"

def test_expiry_date_calculation_and_holiday_shift(calendar):
    # Nifty expiry is Tuesday
    # Reference: Monday 2026-10-12 -> next Tuesday is 2026-10-13
    exp_nifty = calendar.get_expiry_date("NIFTY", ref_date=date(2026, 10, 12))
    assert exp_nifty == date(2026, 10, 13)

    # Sensex expiry is Thursday
    # Reference: Monday 2026-10-12 -> next Thursday is 2026-10-15
    exp_sensex = calendar.get_expiry_date("SENSEX", ref_date=date(2026, 10, 12))
    assert exp_sensex == date(2026, 10, 15)

    # Holiday shift test:
    # If Tuesday is an exchange holiday, Nifty weekly expiry shifts to Monday!
    custom_cal = MarketCalendar(holidays={date(2026, 10, 20)})
    exp_nifty_holiday = custom_cal.get_expiry_date("NIFTY", ref_date=date(2026, 10, 19))
    assert exp_nifty_holiday == date(2026, 10, 19)
