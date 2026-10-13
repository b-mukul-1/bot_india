"""
APEX-IN Market Data Recorder
Records live quotes and telemetry during trading sessions.
Maintains session manifests and data quality flags.
"""

import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
from backend.app.calendar import MarketCalendar
from backend.app.instruments import InstrumentResolver, InstrumentContract
from backend.app.clients.marketdata import MarketDataProvider, MarketQuote

logger = logging.getLogger(__name__)

class DataRecorder:
    def __init__(
        self,
        provider: MarketDataProvider,
        resolver: InstrumentResolver,
        calendar: MarketCalendar,
        poll_interval: float = 2.0,
    ):
        self.provider = provider
        self.resolver = resolver
        self.calendar = calendar
        self.poll_interval = poll_interval
        self.quotes_recorded_today: int = 0
        self.is_running: bool = False

    def get_active_contracts(self) -> List[tuple[str, str]]:
        """
        Gathers tokens to monitor:
        - Indices: NIFTY 50, SENSEX, INDIA VIX
        - Futures: Nifty near-month, Sensex near-month
        - ATM +/- 3 options strikes for Nifty
        """
        contracts: List[tuple[str, str]] = []

        # Indices
        for idx in ["NIFTY", "SENSEX", "INDIA VIX"]:
            spot = self.resolver.get_spot(idx)
            if spot:
                contracts.append((spot.instrument_token, spot.trading_symbol))

        # Futures
        for u in ["NIFTY", "SENSEX"]:
            futs = self.resolver.get_futures(u)
            if futs:
                contracts.append((futs[0].instrument_token, futs[0].trading_symbol))

        return contracts

    def record_cycle(self) -> Dict[str, MarketQuote]:
        """Runs a single polling cycle across active instruments."""
        active = self.get_active_contracts()
        if not active:
            return {}

        quotes = self.provider.get_quotes(active)
        self.quotes_recorded_today += len(quotes)
        return quotes
