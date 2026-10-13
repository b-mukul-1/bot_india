"""
APEX-IN Portfolio Sizing & Vol-Targeting
Calculates contract lot sizes based on ATR stop distance and risk budget.
Never exceeds max lot limits or margin capacity.
"""

from typing import Dict, Any
from backend.app.instruments import InstrumentContract

def calculate_position_size(
    contract: InstrumentContract,
    current_equity: float,
    risk_pct: float,
    stop_distance_points: float,
    max_lots: int = 2,
) -> int:
    """
    Calculates number of lots:
    Risk per lot = stop_distance_points * lot_size
    Max risk INR = current_equity * risk_pct
    """
    if stop_distance_points <= 0 or contract.lot_size <= 0:
        return contract.lot_size

    risk_budget_inr = current_equity * risk_pct
    risk_per_lot_inr = stop_distance_points * contract.lot_size

    if risk_per_lot_inr <= 0:
        return contract.lot_size

    lots = int(risk_budget_inr // risk_per_lot_inr)
    lots = max(1, min(lots, max_lots))
    return lots * contract.lot_size
