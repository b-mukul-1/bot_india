"""
APEX-IN Market Calendar and Session Controller
Handles Indian market sessions (09:15 - 15:30 IST), pre-open, square-off,
exchange holidays, weekly expiry shifts (Nifty Tuesday, Sensex Thursday), and timezone conversions.
"""

import os
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Set, Optional, Dict, Any

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

# NSE / BSE Official Holidays 2026
NSE_HOLIDAYS_2026: Set[date] = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 2, 17),  # Mahashivratri
    date(2026, 3, 3),   # Holi
    date(2026, 3, 20),  # Id-ul-Fitr
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. B.R. Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 27),  # Bakri Id
    date(2026, 6, 26),  # Muharram
    date(2026, 8, 15),  # Independence Day
    date(2026, 9, 4),   # Milad-un-Nabi
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 11, 10), # Diwali Balipratipada
    date(2026, 11, 24), # Gurunanak Jayanti
    date(2026, 12, 25), # Christmas
}

class MarketCalendar:
    """Provides market session timings and expiry calculations for NSE and BSE."""

    def __init__(
        self,
        holidays: Optional[Set[date]] = None,
        session_open: time = time(9, 15),
        session_close: time = time(15, 30),
        entry_start: time = time(9, 20),      # Skip first 5 mins (volatility flush)
        entry_cutoff: time = time(14, 45),    # No new entries after 14:45 IST
        square_off_time: time = time(15, 15), # Mandatory intraday square-off by 15:15 IST
    ):
        self.holidays = holidays or NSE_HOLIDAYS_2026
        self.session_open = session_open
        self.session_close = session_close
        self.entry_start = entry_start
        self.entry_cutoff = entry_cutoff
        self.square_off_time = square_off_time

    @staticmethod
    def to_ist(dt: datetime) -> datetime:
        """Converts any datetime to IST (Asia/Kolkata)."""
        if dt.tzinfo is None:
            # Assume UTC if naive
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(IST)

    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        """Converts any datetime to UTC."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(UTC)

    def is_holiday(self, d: date) -> bool:
        """Returns True if the date is a weekend or listed exchange holiday."""
        if os.environ.get("BYPASS_CALENDAR_HOLIDAY", "false").lower() in ("true", "1"):
            return False
        if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return True
        return d in self.holidays

    def is_trading_day(self, d: date) -> bool:
        return not self.is_holiday(d)

    def get_market_state(self, dt: datetime) -> Dict[str, Any]:
        """
        Returns full market session status for a given datetime:
        is_open, can_enter, must_squareoff, session_phase ('PRE_OPEN', 'OPEN', 'SQUAREOFF', 'CLOSED')
        """
        ist_dt = self.to_ist(dt)
        current_date = ist_dt.date()
        current_time = ist_dt.time()

        if not self.is_trading_day(current_date):
            return {
                "is_open": False,
                "can_enter": False,
                "must_squareoff": False,
                "phase": "CLOSED_HOLIDAY",
                "ist_time": ist_dt.isoformat(),
            }

        # Market Hours check
        if current_time < self.session_open:
            phase = "PRE_OPEN" if time(9, 0) <= current_time < self.session_open else "CLOSED_PRE_SESSION"
            return {
                "is_open": False,
                "can_enter": False,
                "must_squareoff": False,
                "phase": phase,
                "ist_time": ist_dt.isoformat(),
            }
        elif current_time >= self.session_close:
            return {
                "is_open": False,
                "can_enter": False,
                "must_squareoff": False,
                "phase": "CLOSED_POST_SESSION",
                "ist_time": ist_dt.isoformat(),
            }

        # Session is Open
        is_open = True
        can_enter = self.entry_start <= current_time <= self.entry_cutoff
        must_squareoff = current_time >= self.square_off_time

        if must_squareoff:
            phase = "SQUAREOFF"
        elif can_enter:
            phase = "NORMAL_TRADING"
        elif current_time < self.entry_start:
            phase = "OPEN_WARMUP"
        else:
            phase = "NO_NEW_ENTRIES"

        return {
            "is_open": is_open,
            "can_enter": can_enter,
            "must_squareoff": must_squareoff,
            "phase": phase,
            "ist_time": ist_dt.isoformat(),
        }

    def get_expiry_date(self, underlying: str, ref_date: Optional[date] = None) -> date:
        """
        Calculates weekly expiry date for underlying starting from ref_date:
        - NIFTY: Tuesday (weekday 1)
        - SENSEX: Thursday (weekday 3)
        - BANKNIFTY: Wednesday (weekday 2) or Tuesday
        If the scheduled expiry falls on an exchange holiday, it shifts to the PRECEDING trading day.
        """
        if ref_date is None:
            ref_date = datetime.now(IST).date()

        u = underlying.upper()
        if "SENSEX" in u:
            target_weekday = 3  # Thursday
        elif "BANKNIFTY" in u:
            target_weekday = 2  # Wednesday
        else:
            target_weekday = 1  # Tuesday (NIFTY standard for 2026)

        # Days until next target weekday (including today if today is target weekday)
        days_ahead = (target_weekday - ref_date.weekday()) % 7
        candidate_date = ref_date + timedelta(days=days_ahead)

        # Shift to preceding trading day if candidate falls on holiday
        while not self.is_trading_day(candidate_date):
            candidate_date -= timedelta(days=1)

        return candidate_date
