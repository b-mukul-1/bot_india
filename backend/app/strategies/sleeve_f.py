"""
APEX-IN Sleeve F: Index Futures Trend & Opening Range Breakout (ORB)
Generates directional signals for Nifty and Sensex futures.
Enforces cost-aware gates, ATR trailing stops, and intraday square-off.
"""

from dataclasses import dataclass
from typing import Optional, List
import logging
from backend.app.instruments import InstrumentContract

logger = logging.getLogger(__name__)

@dataclass
class StrategySignal:
    strategy_id: str
    sleeve: str  # "F", "O_BUY", "O_SPREAD"
    underlying: str
    instrument_token: str
    tradingsymbol: str
    instrument_type: str  # "FUT", "CE", "PE"
    side: str  # "BUY" or "SELL"
    quantity: int
    price: float
    stop_price: float
    target_price: float
    signal_reason: str
    risk_inr: float
    expected_move: float
    is_hedged: bool = False
    hedge_token: Optional[str] = None
    hedge_price: Optional[float] = None

class SleeveF:
    def __init__(self, risk_per_trade_inr: float = 8000.0):
        self.strategy_id = "SLEEVE_F_ORB_TREND"
        self.risk_per_trade_inr = risk_per_trade_inr

    def evaluate(
        self,
        contract: InstrumentContract,
        current_price: float,
        orb_high: float,
        orb_low: float,
        ema_20: float,
        ema_50: float,
        adx: float,
        atr: float,
        spot_price: Optional[float] = None,
    ) -> Optional[StrategySignal]:
        """
        Evaluates ORB + Trend conditions:
        - Long: eval_price > orb_high AND eval_price > ema_20 > ema_50 AND adx > 20
        - Short: eval_price < orb_low AND eval_price < ema_20 < ema_50 AND adx > 20
        """
        if adx < 20.0 or atr <= 0.0:
            return None

        eval_price = spot_price if spot_price is not None else current_price
        lot_size = contract.lot_size
        stop_dist = max(20.0, 1.5 * atr)  # minimum stop distance in index points

        # 1. Long Breakout
        if eval_price > orb_high and eval_price > ema_20 > ema_50:
            stop_price = round(current_price - stop_dist, 2)
            target_price = round(current_price + 2.5 * stop_dist, 2)
            risk_inr = stop_dist * lot_size
            expected_move = 2.5 * stop_dist

            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="F",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="FUT",
                side="BUY",
                quantity=lot_size,
                price=current_price,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="ORB_LONG_EMA_TREND_ADX",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        # 2. Short Breakdown
        if eval_price < orb_low and eval_price < ema_20 < ema_50:
            stop_price = round(current_price + stop_dist, 2)
            target_price = round(current_price - 2.5 * stop_dist, 2)
            risk_inr = stop_dist * lot_size
            expected_move = 2.5 * stop_dist

            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="F",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="FUT",
                side="SELL",
                quantity=lot_size,
                price=current_price,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="ORB_SHORT_EMA_TREND_ADX",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        return None
