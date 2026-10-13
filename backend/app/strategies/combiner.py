"""
APEX-IN Strategy Combiner, Cost-Aware Gate, and Order Netting
Ensures:
1. Expected move > 2x (round-trip charges + modeled spread friction).
2. Opposing orders on the same contract are netted before order dispatch.
3. 'No trade' is the default output when market edge does not survive costs.
"""

from typing import List, Dict, Optional
import logging
from backend.app.strategies.sleeve_f import StrategySignal
from backend.app.charges.engine import ChargesEngine

logger = logging.getLogger(__name__)

class StrategyCombiner:
    def __init__(self, charges_engine: ChargesEngine):
        self.charges_engine = charges_engine

    def cost_aware_gate(self, signal: StrategySignal, modeled_spread: float = 1.0) -> bool:
        """
        Calculates full round-trip charges + modeled spread.
        Rejects signal unless: signal.expected_move > 2 * (total_charges + spread_cost).
        """
        try:
            rt_charges = self.charges_engine.calculate_round_trip(
                instrument_type=signal.instrument_type,
                entry_side=signal.side,
                entry_price=signal.price,
                exit_price=signal.target_price,
                quantity=signal.quantity,
            )
            charges_inr = float(rt_charges.total_charges)
            spread_cost_inr = modeled_spread * signal.quantity
            total_friction = charges_inr + spread_cost_inr

            # For options, expected move in INR; for futures, points * qty
            if signal.instrument_type == "FUT":
                expected_profit_inr = signal.expected_move * signal.quantity
            else:
                expected_profit_inr = signal.expected_move

            hurdle = 2.0 * total_friction
            if expected_profit_inr < hurdle:
                logger.info(
                    f"[COST GATE REJECT] {signal.tradingsymbol}: Expected profit Rs {expected_profit_inr:.2f} "
                    f"< 2x friction Rs {hurdle:.2f} (Charges: {charges_inr:.2f}, Spread: {spread_cost_inr:.2f})"
                )
                return False

            return True
        except Exception as e:
            logger.error(f"Error in cost_aware_gate: {e}")
            return False

    def net_signals(self, signals: List[StrategySignal]) -> List[StrategySignal]:
        """
        Nets signals targeting the exact same instrument token.
        If long qty == short qty on same contract, cancels both out (0 net).
        """
        token_map: Dict[str, List[StrategySignal]] = {}
        for s in signals:
            token_map.setdefault(s.instrument_token, []).append(s)

        netted_signals: List[StrategySignal] = []
        for token, sigs in token_map.items():
            if len(sigs) == 1:
                netted_signals.append(sigs[0])
                continue

            # Calculate net quantity: BUY is +, SELL is -
            net_qty = 0
            buy_sig = None
            sell_sig = None

            for s in sigs:
                if s.side == "BUY":
                    net_qty += s.quantity
                    buy_sig = s
                else:
                    net_qty -= s.quantity
                    sell_sig = s

            if net_qty > 0 and buy_sig:
                buy_sig.quantity = net_qty
                netted_signals.append(buy_sig)
            elif net_qty < 0 and sell_sig:
                sell_sig.quantity = abs(net_qty)
                netted_signals.append(sell_sig)
            else:
                logger.info(f"[NETTING] Opposing signals for token {token} perfectly neutralized to 0.")

        return netted_signals
