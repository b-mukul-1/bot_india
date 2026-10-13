"""
APEX-IN Emergency Kill Switch
Cancels all pending orders and flattens open positions on MegaBull.
Can be triggered manually from Dashboard or automatically by Sentinel on breach.
"""

import logging
from typing import Dict, Any, List
from backend.app.clients.megabull import MegaBullClient
from backend.app.risk.sentinel import RiskSentinel
from backend.app.store.db import DatabaseManager

logger = logging.getLogger(__name__)

class KillSwitch:
    def __init__(self, client: MegaBullClient, sentinel: RiskSentinel, db: DatabaseManager):
        self.client = client
        self.sentinel = sentinel
        self.db = db

    def execute_halt_and_flatten(self, reason: str = "MANUAL_TRIGGER") -> Dict[str, Any]:
        """
        Executes emergency halt sequence:
        1. Halt Sentinel immediately to block any new incoming orders.
        2. Query and cancel all open orders on MegaBull.
        3. Query all open positions and square them off.
        4. Log event and persist state.
        """
        logger.critical(f"=== EXECUTING EMERGENCY KILL SWITCH: {reason} ===")
        self.sentinel.trigger_halt(f"Kill switch activated: {reason}")

        cancelled_orders: List[int] = []
        flattened_positions: List[Dict[str, Any]] = []

        # 1. Cancel open orders
        try:
            orders_resp = self.client.get_orders()
            open_orders = orders_resp.get("open", [])
            order_ids_to_cancel = [o["id"] for o in open_orders if "id" in o]

            if order_ids_to_cancel:
                logger.warning(f"Cancelling open orders: {order_ids_to_cancel}")
                self.client.cancel_orders(order_ids_to_cancel)
                cancelled_orders = order_ids_to_cancel
        except Exception as e:
            logger.error(f"Error cancelling orders during kill switch: {e}")

        # 2. Square off open positions
        try:
            positions = self.client.get_positions()
            for pos in positions:
                qty = int(pos.get("qty", 0))
                token = str(pos.get("instrumentToken", ""))
                if qty != 0 and token:
                    # If Long (qty > 0), place SELL. If Short (qty < 0), place BUY.
                    square_side = "SELL" if qty > 0 else "BUY"
                    square_qty = abs(qty)
                    logger.warning(f"Flattening position: {pos.get('instrumentName')} {square_side} {square_qty}")
                    self.client.place_order(
                        instrument_token=token,
                        qty=square_qty,
                        side=square_side,
                        order_type="MKT",
                        duration="MIS",
                    )
                    flattened_positions.append({"token": token, "side": square_side, "qty": square_qty})
        except Exception as e:
            logger.error(f"Error flattening positions during kill switch: {e}")

        summary = {
            "status": "HALTED",
            "reason": reason,
            "cancelled_orders": cancelled_orders,
            "flattened_positions": flattened_positions,
        }

        # Log to DB
        self.db.set_state("kill_switch_state", summary)
        return summary
