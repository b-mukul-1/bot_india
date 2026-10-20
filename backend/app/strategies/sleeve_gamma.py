"""
APEX-IN Sleeve GAMMA-EXP: Expiry Afternoon Gamma Surge Scalp
Targeted for weekly expiry days (Wednesday for BankNifty / Thursday for Nifty).
Executes post 13:15 IST when trapped option writers face short-covering panic.
Asymmetric risk-reward setup: Tight 35% risk with 2.5x target (+150% gain).
"""

from typing import Optional
import logging
from backend.app.instruments import InstrumentContract
from backend.app.strategies.sleeve_f import StrategySignal

logger = logging.getLogger(__name__)

class SleeveGamma:
    def __init__(self, max_premium_risk_inr: float = 30000.0):
        self.strategy_id = "SLEEVE_GAMMA_EXPIRY"
        self.max_premium_risk_inr = max_premium_risk_inr

    def evaluate(
        self,
        contract: InstrumentContract,
        premium: float,
        spot_price: float,
        session_high: float,
        session_low: float,
        is_expiry_day: bool,
        is_afternoon_window: bool,
    ) -> Optional[StrategySignal]:
        """
        Evaluates Expiry Afternoon Gamma Surge conditions:
        - Only active on expiry day afternoon (13:15 to 15:00 IST)
        - Premium between Rs 25 and Rs 90 (high gamma acceleration zone)
        - Bullish Gamma: Spot breaks above Session High
        - Bearish Gamma: Spot breaks below Session Low
        """
        if not is_expiry_day or not is_afternoon_window:
            return None

        if premium < 25.0 or premium > 90.0:
            return None

        lot_size = contract.lot_size
        premium_outlay = premium * lot_size

        if premium_outlay > self.max_premium_risk_inr:
            return None

        # Asymmetric risk: Stop loss at 35% loss of premium; Target at 2.5x (+150% runner)
        stop_price = round(premium * 0.65, 2)
        target_price = round(premium * 2.50, 2)
        risk_inr = round((premium - stop_price) * lot_size, 2)
        expected_move = round((target_price - premium) * lot_size, 2)

        # Bullish Gamma Breakout (Call short covering)
        if contract.instrument_type == "CE" and spot_price >= session_high:
            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="GAMMA_EXP",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="CE",
                side="BUY",
                quantity=lot_size,
                price=premium,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="AFTERNOON_GAMMA_SHORT_COVERING_CE",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        # Bearish Gamma Breakdown (Put long liquidation)
        if contract.instrument_type == "PE" and spot_price <= session_low:
            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="GAMMA_EXP",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="PE",
                side="BUY",
                quantity=lot_size,
                price=premium,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="AFTERNOON_GAMMA_PANIC_PUT_EXPANSION",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        return None
