"""
APEX-IN Sleeve O-Buy: Convex Option Buying (Momentum & Vol Expansion)
Buys ATM / slightly OTM CE or PE on momentum expansion.
Defined risk: max loss is capped at entry premium.
"""

from typing import Optional
from backend.app.instruments import InstrumentContract
from backend.app.strategies.sleeve_f import StrategySignal

class SleeveOBuy:
    def __init__(self, max_premium_risk_inr: float = 3500.0):
        self.strategy_id = "SLEEVE_O_BUY_CONVEX"
        self.max_premium_risk_inr = max_premium_risk_inr

    def evaluate(
        self,
        contract: InstrumentContract,
        premium: float,
        spot_price: float,
        india_vix: float,
        spot_donchian_high: float,
        spot_donchian_low: float,
    ) -> Optional[StrategySignal]:
        """
        Evaluates option buying signal:
        - Avoid entering if India VIX > 22 (excessive IV crush risk)
        - Call (CE): Spot breaks above Donchian High
        - Put (PE): Spot breaks below Donchian Low
        """
        if india_vix > 22.0 or premium < 25.0:
            return None

        lot_size = contract.lot_size
        premium_outlay = premium * lot_size

        # Cap size to risk budget
        if premium_outlay > self.max_premium_risk_inr:
            return None

        # Hard stop at 35% loss of premium; target at 2x profit (+70% of premium)
        stop_price = round(premium * 0.65, 2)
        target_price = round(premium * 1.70, 2)
        risk_inr = round((premium - stop_price) * lot_size, 2)
        expected_move = round((target_price - premium) * lot_size, 2)

        if contract.instrument_type == "CE" and spot_price > spot_donchian_high:
            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="O_BUY",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="CE",
                side="BUY",
                quantity=lot_size,
                price=premium,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="CONVEX_CALL_MOMENTUM_EXPANSION",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        if contract.instrument_type == "PE" and spot_price < spot_donchian_low:
            return StrategySignal(
                strategy_id=self.strategy_id,
                sleeve="O_BUY",
                underlying=contract.underlying,
                instrument_token=contract.instrument_token,
                tradingsymbol=contract.trading_symbol,
                instrument_type="PE",
                side="BUY",
                quantity=lot_size,
                price=premium,
                stop_price=stop_price,
                target_price=target_price,
                signal_reason="CONVEX_PUT_MOMENTUM_EXPANSION",
                risk_inr=risk_inr,
                expected_move=expected_move,
            )

        return None
