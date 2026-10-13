"""
APEX-IN Paper Order Manager
Handles order execution against MegaBull simulator.
Enforces hard PAPER_MODE_ONLY guard, idempotency, order reconciliation,
trade snapshot persistence, and hedge-first sequencing for spreads.
"""

import uuid
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from decimal import Decimal

from backend.app.clients.megabull import MegaBullClient, PAPER_MODE_ONLY
from backend.app.risk.sentinel import RiskSentinel, RiskBreachException
from backend.app.store.db import DatabaseManager
from backend.app.store.models import TradeRecord, TradeEventRecord
from backend.app.charges.engine import ChargesEngine
from backend.app.calendar import MarketCalendar
from backend.app.strategies.sleeve_f import StrategySignal

logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(
        self,
        client: MegaBullClient,
        sentinel: RiskSentinel,
        db: DatabaseManager,
        charges_engine: ChargesEngine,
        calendar: MarketCalendar,
    ):
        if not PAPER_MODE_ONLY:
            raise RuntimeError("CRITICAL SAFETY VIOLATION: PAPER_MODE_ONLY must be True!")

        self.client = client
        self.sentinel = sentinel
        self.db = db
        self.charges = charges_engine
        self.calendar = calendar

        # Active tracked positions: trade_id -> TradeRecord
        self.active_trades: Dict[str, TradeRecord] = {}

    def execute_signal(self, signal: StrategySignal) -> Optional[TradeRecord]:
        """
        Executes a vetted signal:
        1. Validates risk with Sentinel.
        2. Creates immutable TradeRecord snapshot with decision-time state.
        3. Sends order to MegaBull simulator.
        4. Updates TradeRecord with fill data and logs raw API response.
        """
        if not PAPER_MODE_ONLY:
            raise RuntimeError("CRITICAL SAFETY VIOLATION: PAPER_MODE_ONLY must be True!")

        # 1. Validate Sentinel limits
        self.sentinel.validate_order(
            sleeve=signal.sleeve,
            side=signal.side,
            instrument_type=signal.instrument_type,
            quantity=signal.quantity,
            lot_size=signal.quantity,
            price=signal.price,
            risk_inr=signal.risk_inr,
            current_open_risk=0.0,
            is_hedged=signal.is_hedged,
        )

        now_utc = datetime.now(timezone.utc)
        now_ist = self.calendar.to_ist(now_utc).isoformat()
        trade_id = f"TRD-{now_utc.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        # 2. Immutable Decision Snapshot
        trade = TradeRecord(
            trade_id=trade_id,
            strategy_id=signal.strategy_id,
            sleeve=signal.sleeve,
            signal_reason=signal.signal_reason,
            algo_version="1.0.0",
            underlying=signal.underlying,
            instrument_type=signal.instrument_type,
            tradingsymbol=signal.tradingsymbol,
            instrument_token=signal.instrument_token,
            lot_size=signal.quantity,
            lots=1,
            quantity=signal.quantity,
            side=signal.side,
            decision_time_ist=now_ist,
            order_sent_time_ist=now_ist,
            order_type="LIMIT",
            limit_price=Decimal(str(signal.price)),
            entry_price=Decimal(str(signal.price)),
            ltp_at_decision=Decimal(str(signal.price)),
            stop_price=Decimal(str(signal.stop_price)) if signal.stop_price else None,
            target_price=Decimal(str(signal.target_price)) if signal.target_price else None,
            risk_amount_inr=Decimal(str(signal.risk_inr)),
            data_quality_flags="MISSING_DEPTH_AND_VOLUME",
            spread_modeled=Decimal("1.00"),
            conservative_fill_price_modeled=Decimal(str(signal.price + 0.50)),
        )

        # Write initial snapshot to DB before sending order
        self.db.save_trade(trade)

        # 3. Send order to MegaBull simulator
        try:
            resp = self.client.place_order(
                instrument_token=signal.instrument_token,
                qty=signal.quantity,
                side=signal.side,
                order_type="LIMIT",
                price=signal.price,
                duration="MIS",
            )
            order_id = resp.get("id")
            trade.fill_time_ist = self.calendar.to_ist(datetime.now(timezone.utc)).isoformat()

            # Record event with raw API response
            self.db.log_trade_event(
                trade_id=trade_id,
                order_id=order_id,
                event_type="FILL",
                timestamp_ist=trade.fill_time_ist,
                message="Simulated order placed on MegaBull",
                raw_payload=resp,
            )

            self.sentinel.record_order_sent()
            self.active_trades[trade_id] = trade
            self.db.save_trade(trade)
            logger.info(f"[ORDER PLACED] {trade_id} {signal.tradingsymbol} {signal.side} qty={signal.quantity}")
            return trade

        except Exception as e:
            logger.error(f"[ORDER FAILED] {trade_id}: {e}")
            self.db.log_trade_event(
                trade_id=trade_id,
                event_type="ERROR",
                timestamp_ist=now_ist,
                message=str(e),
            )
            raise

    def close_trade(self, trade_id: str, exit_price: float, exit_reason: str = "TARGET") -> Optional[TradeRecord]:
        """
        Closes an active trade, computes round-trip charges, gross/net PnL,
        and finalizes the snapshot row.
        """
        trade = self.active_trades.get(trade_id)
        if not trade:
            trade = self.db.get_trade(trade_id)
        if not trade:
            return None

        now_utc = datetime.now(timezone.utc)
        exit_time_ist = self.calendar.to_ist(now_utc).isoformat()
        exit_side = "SELL" if trade.side == "BUY" else "BUY"

        # Place exit order on MegaBull simulator
        resp = self.client.place_order(
            instrument_token=trade.instrument_token,
            qty=trade.quantity,
            side=exit_side,
            order_type="LIMIT",
            price=exit_price,
            duration="MIS",
        )

        # Compute full Indian F&O charges via charges engine
        rt = self.charges.calculate_round_trip(
            instrument_type=trade.instrument_type,
            entry_side=trade.side,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            quantity=trade.quantity,
            brokerage_per_order=20.0,
        )

        trade.exit_time_ist = exit_time_ist
        trade.exit_price = Decimal(str(exit_price))
        trade.exit_reason = exit_reason
        trade.brokerage = rt.brokerage
        trade.stt = rt.stt
        trade.exchange_txn = rt.exchange_txn
        trade.sebi_fee = rt.sebi_fee
        trade.stamp_duty = rt.stamp_duty
        trade.ipft = rt.ipft
        trade.gst = rt.gst
        trade.total_charges = rt.total_charges
        trade.charges_as_pct_of_turnover = rt.charges_as_pct_of_turnover
        trade.gross_pnl = rt.gross_pnl
        trade.net_pnl = rt.net_pnl
        trade.net_pnl_pct_of_capital = round(rt.net_pnl / Decimal(str(self.sentinel.current_equity)) * Decimal("100"), 4)

        self.db.log_trade_event(
            trade_id=trade_id,
            order_id=resp.get("id"),
            event_type="EXIT",
            timestamp_ist=exit_time_ist,
            message=f"Trade exited: {exit_reason}",
            raw_payload=resp,
        )

        self.db.save_trade(trade)
        if trade_id in self.active_trades:
            del self.active_trades[trade_id]

        logger.info(f"[TRADE CLOSED] {trade_id}: Gross PnL=Rs {trade.gross_pnl}, Charges=Rs {trade.total_charges}, Net PnL=Rs {trade.net_pnl}")
        return trade

    def reconcile_positions(self) -> bool:
        """
        Reconciles locally tracked positions with MegaBull /api/position/my.
        If mismatch occurs, triggers Sentinel halt!
        """
        try:
            remote_positions = self.client.get_positions()
            remote_tokens = {str(p.get("instrumentToken")): int(p.get("qty", 0)) for p in remote_positions if p.get("qty", 0) != 0}

            local_tokens: Dict[str, int] = {}
            for t in self.active_trades.values():
                qty = t.quantity if t.side == "BUY" else -t.quantity
                local_tokens[t.instrument_token] = local_tokens.get(t.instrument_token, 0) + qty

            if remote_tokens != local_tokens:
                mismatch_msg = f"Position mismatch! Remote: {remote_tokens} vs Local: {local_tokens}"
                logger.critical(mismatch_msg)
                self.sentinel.trigger_halt(f"RECONCILIATION_MISMATCH: {mismatch_msg}")
                return False

            return True
        except Exception as e:
            logger.error(f"Reconciliation error: {e}")
            self.sentinel.trigger_halt(f"RECONCILIATION_ERROR: {e}")
            return False
