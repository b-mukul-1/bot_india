"""
APEX-IN Sleeve O-Spread: Defined-Risk Vertical Credit Spreads
Trades Bull Put or Bear Call spreads in range-bound, high-IV regimes.
MANDATORY SAFETY: NEVER sell naked options. Hedge leg is ALWAYS confirmed first.
"""

from typing import Optional, Tuple
from backend.app.instruments import InstrumentContract
from backend.app.strategies.sleeve_f import StrategySignal

class SleeveOSpread:
    def __init__(self, max_spread_risk_inr: float = 4000.0):
        self.strategy_id = "SLEEVE_O_SPREAD_CREDIT"
        self.max_spread_risk_inr = max_spread_risk_inr

    def evaluate_bull_put_spread(
        self,
        short_put_contract: InstrumentContract,
        short_put_premium: float,
        long_put_hedge_contract: InstrumentContract,
        long_put_hedge_premium: float,
        spot_price: float,
        adx: float,
        india_vix: float,
    ) -> Optional[Tuple[StrategySignal, StrategySignal]]:
        """
        Creates a Bull Put Spread (Credit):
        - Sell higher strike Put (short leg)
        - Buy lower strike Put (long hedge leg)
        Returns: (long_hedge_signal, short_leg_signal)
        Order manager executes the long hedge FIRST.
        """
        # Low trend / range-bound requirement
        if adx > 22.0 or india_vix < 13.0 or india_vix > 25.0:
            return None

        if short_put_contract.strike <= long_put_hedge_contract.strike:
            return None

        spread_width = short_put_contract.strike - long_put_hedge_contract.strike
        net_credit = short_put_premium - long_put_hedge_premium
        if net_credit <= 5.0 or spread_width <= 0:
            return None

        lot_size = short_put_contract.lot_size
        max_loss_inr = (spread_width - net_credit) * lot_size

        if max_loss_inr > self.max_spread_risk_inr:
            return None

        # 1. Protective Long Hedge (PLACED FIRST)
        hedge_signal = StrategySignal(
            strategy_id=self.strategy_id,
            sleeve="O_SPREAD",
            underlying=long_put_hedge_contract.underlying,
            instrument_token=long_put_hedge_contract.instrument_token,
            tradingsymbol=long_put_hedge_contract.trading_symbol,
            instrument_type="PE",
            side="BUY",
            quantity=lot_size,
            price=long_put_hedge_premium,
            stop_price=0.0,
            target_price=0.0,
            signal_reason="SPREAD_LONG_HEDGE_WING",
            risk_inr=round(long_put_hedge_premium * lot_size, 2),
            expected_move=0.0,
            is_hedged=True,
        )

        # 2. Income Short Leg (PLACED SECOND)
        short_signal = StrategySignal(
            strategy_id=self.strategy_id,
            sleeve="O_SPREAD",
            underlying=short_put_contract.underlying,
            instrument_token=short_put_contract.instrument_token,
            tradingsymbol=short_put_contract.trading_symbol,
            instrument_type="PE",
            side="SELL",
            quantity=lot_size,
            price=short_put_premium,
            stop_price=round(short_put_premium + spread_width, 2),
            target_price=round(short_put_premium * 0.20, 2),  # Target: keep 80% of credit
            signal_reason="SPREAD_SHORT_INCOME_LEG",
            risk_inr=round(max_loss_inr, 2),
            expected_move=round(net_credit * lot_size, 2),
            is_hedged=True,
            hedge_token=long_put_hedge_contract.instrument_token,
            hedge_price=long_put_hedge_premium,
        )

        return (hedge_signal, short_signal)
