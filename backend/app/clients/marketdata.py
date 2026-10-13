"""
APEX-IN Market Data Provider Interface and Adapters
Enforces strict Rule 2: Never fabricate or randomly generate market data!
Missing depth/volume values remain None with explicit data_quality flags.
Conservative modeled spreads are kept in distinct modeled fields.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from backend.app.clients.megabull import MegaBullClient

logger = logging.getLogger(__name__)

@dataclass
class MarketQuote:
    instrument_token: str
    tradingsymbol: str
    ltp: float
    bid: Optional[float] = None
    bid_qty: Optional[int] = None
    ask: Optional[float] = None
    ask_qty: Optional[int] = None
    volume: Optional[int] = None
    oi: Optional[int] = None
    timestamp: datetime = None
    data_quality: str = "OK"  # "OK", "MISSING_DEPTH_AND_VOLUME", etc.

    # Modeled metrics (calculated strictly for cost/fill conservatism)
    spread_modeled: Optional[float] = None
    conservative_fill_price_modeled: Optional[float] = None

class MarketDataProvider(ABC):
    """Abstract interface for streaming or polling market data."""

    @abstractmethod
    def get_quote(self, instrument_token: str, tradingsymbol: str) -> Optional[MarketQuote]:
        pass

    @abstractmethod
    def get_quotes(self, items: List[tuple[str, str]]) -> Dict[str, MarketQuote]:
        """items is list of (token, symbol)"""
        pass

class MegaBullOnlyProvider(MarketDataProvider):
    """
    Default adapter when only MegaBull API key is available.
    MegaBull only provides LTP. All missing depth/volume fields stay None.
    """

    def __init__(self, megabull_client: MegaBullClient):
        self.client = megabull_client

    def get_quote(self, instrument_token: str, tradingsymbol: str) -> Optional[MarketQuote]:
        try:
            res = self.client.get_ltp(instrument_token)
            ltp = float(res.get("ltp", 0.0))
            if ltp <= 0.0:
                return None

            quote = MarketQuote(
                instrument_token=str(instrument_token),
                tradingsymbol=tradingsymbol,
                ltp=ltp,
                bid=None,  # Not provided by MegaBull
                bid_qty=None,
                ask=None,
                ask_qty=None,
                volume=None,
                oi=None,
                timestamp=datetime.now(timezone.utc),
                data_quality="MISSING_DEPTH_AND_VOLUME",
            )
            # Apply conservative cost model
            self._apply_conservative_model(quote)
            return quote
        except Exception as e:
            logger.warning(f"Failed to fetch LTP for token {instrument_token}: {e}")
            return None

    def get_quotes(self, items: List[tuple[str, str]]) -> Dict[str, MarketQuote]:
        results = {}
        for token, symbol in items:
            q = self.get_quote(token, symbol)
            if q:
                results[token] = q
        return results

    def _apply_conservative_model(self, quote: MarketQuote) -> None:
        """
        Calculates conservative modeled spread:
        - For options: 0.75% of premium (or minimum 0.50 points)
        - For futures: 1.0 point for Nifty, 3.0 points for Sensex
        Conservative fill: Buy at LTP + spread/2, Sell at LTP - spread/2.
        """
        symbol = quote.tradingsymbol.upper()
        if "CE" in symbol or "PE" in symbol:
            modeled_spread = max(0.50, round(quote.ltp * 0.0075, 2))
        elif "SENSEX" in symbol:
            modeled_spread = 3.0
        else:
            modeled_spread = 1.0

        quote.spread_modeled = modeled_spread
        # Default conservative fill for BUY:
        quote.conservative_fill_price_modeled = round(quote.ltp + modeled_spread / 2.0, 2)

class ExternalFeedProvider(MarketDataProvider):
    """
    Adapter for Angel One SmartAPI or DhanHQ API when credentials are provided by the owner.
    """
    def __init__(self, provider_name: str, config: Dict[str, str]):
        self.provider_name = provider_name
        self.config = config
        logger.info(f"Initialized external market data feed adapter: {provider_name}")

    def get_quote(self, instrument_token: str, tradingsymbol: str) -> Optional[MarketQuote]:
        # Pluggable placeholder when external broker credentials are added by user
        raise NotImplementedError("External broker feed credentials pending owner setup.")

    def get_quotes(self, items: List[tuple[str, str]]) -> Dict[str, MarketQuote]:
        raise NotImplementedError("External broker feed credentials pending owner setup.")
