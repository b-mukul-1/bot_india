"""
APEX-IN Sleeve VWAP-MOM: Institutional VWAP & Multi-EMA Momentum Breakout
Buys high-momentum ATM Call/Put options when price crosses VWAP with EMA 9/21 alignment.
Enforces strict premium-based risk caps and dynamic trailing stops.
"""

from typing import Optional
import logging
from backend.app.instruments import InstrumentContract
from backend.app.strategies.sleeve_f import StrategySignal

logger = logging.getLogger(__name__)

class SleeveVWAP:
    def __init__(self, max_premium_risk_inr: float = 40000.0):
        self.strategy_id = "SLEEVE_VWAP_MOMENTUM"
        self.max_premium_risk_inr = max_premium_risk_inr

    def evaluate(
        self,
        contract: InstrumentContract,
        premium: float,
        spot_price: float,
        vwap: float,
        ema_9: float,
        ema_21: float,
        session_open: float,
        india_vix: float = 14.5,
    ) -> Optional[StrategySignal]:
        """
        Evaluates Institutional VWAP Momentum signals:
        - VIX filter: Skip if India VIX > 23 (excessive IV crush risk)
        - Premium filter: Minimum Rs 25 floor to prevent brokerage drag
        - Bullish CE: Spot > VWAP and EMA 9 > EMA 21 and Spot > Session Open
        - Bearish PE: Spot < VWAP and EMA 9 < EMA 21 and Spot < Session Open
        """
        if india_vix > 23.0 or premium < 25.0:
            return None

        lot_size = contract.lot_size
        premium_outlay = premium * lot_size

        # Cap max capital outlay per single leg (Rs 40,000 max)
        if premium_outlay > self.max_premium_risk_inr:
            return None

        # Risk parameters: Initial Stop Loss at 30% risk, Target at 2.2x (+120% gain)
        stop_price = round(premium * 0.70, 2)
        target_price = round(premium * 2.20, 2)
        risk_inr = round((premium - stop_price) * lot_size, 2)
        expected_move = round((target_price - premium) * lot_size, 2)

        # 1. Bullish Call Momentum (Above VWAP + EMA 9/21 Trend + Above Open)
        if (
            contract.instrument_type == "CE"
            and spot_price > vwap
            and ema_9 > ema_21
            and spot_price >= session_open
        ):
            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="VWAP_MOM",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="CE",
                side="BUY",
                quantity=lot_size,
                price=premium,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="INSTITUTIONAL_VWAP_CALL_EXPANSION",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        # 2. Bearish Put Breakdown (Below VWAP + EMA 9/21 Breakdown + Below Open)
        if (
            contract.instrument_type == "PE"
            and spot_price < vwap
            and ema_9 < ema_21
            and spot_price <= session_open
        ):
            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="VWAP_MOM",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="PE",
                side="BUY",
                quantity=lot_size,
                price=premium,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="INSTITUTIONAL_VWAP_PUT_BREAKDOWN",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        return None
