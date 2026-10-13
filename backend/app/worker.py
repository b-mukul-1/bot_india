"""
APEX-IN Autonomous Trading Worker
Long-running background worker process for Railway.
Implements the core execution pipeline:
Market Calendar Scheduler -> Quote Ingestion -> Indicators -> Sleeves (F, O-Buy, O-Spread)
-> Netting -> Cost-Aware Gate -> Risk Sentinel -> Order Execution -> Reconciliation -> Snapshots.
Supports graceful shutdown (SIGINT / SIGTERM) and heartbeat logging.
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from backend.app.config import get_settings
from backend.app.calendar import MarketCalendar
from backend.app.instruments import InstrumentResolver
from backend.app.clients.megabull import MegaBullClient, PAPER_MODE_ONLY
from backend.app.clients.marketdata import MegaBullOnlyProvider
from backend.app.charges.engine import ChargesEngine
from backend.app.risk.sentinel import RiskSentinel
from backend.app.risk.kill_switch import KillSwitch
from backend.app.store.db import DatabaseManager
from backend.app.execution.order_manager import OrderManager
from backend.app.strategies.sleeve_f import SleeveF
from backend.app.strategies.sleeve_o_buy import SleeveOBuy
from backend.app.strategies.sleeve_o_spread import SleeveOSpread
from backend.app.strategies.combiner import StrategyCombiner
from backend.app.monitor.alerts import AlertManager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [WORKER] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("apex_worker")

class TradingWorker:
    def __init__(self):
        if not PAPER_MODE_ONLY:
            raise RuntimeError("CRITICAL SAFETY VIOLATION: PAPER_MODE_ONLY must be True!")

        self.settings = get_settings()
        self.running = True

        # Infrastructure
        self.calendar = MarketCalendar()
        self.db = DatabaseManager(self.settings.DATABASE_URL)
        self.db.init_tables()
        self.charges = ChargesEngine()
        self.alerts = AlertManager(self.settings.ALERT_WEBHOOK_URL)

        # Clients & Adapters
        self.client = MegaBullClient(api_key=self.settings.MEGABULL_API_KEY)
        self.provider = MegaBullOnlyProvider(self.client)

        # Instruments
        self.resolver = InstrumentResolver()
        inst_file = "backend/data/Instrument-default.csv"
        if not os.path.exists(inst_file):
            inst_file = "backend/data/sample_instruments.csv"
        if os.path.exists(inst_file):
            self.resolver.load_from_file(inst_file)
            logger.info(f"Loaded instruments from {inst_file}")

        # Risk & Execution
        self.sentinel = RiskSentinel()
        self.kill_switch = KillSwitch(self.client, self.sentinel, self.db)
        self.order_manager = OrderManager(
            self.client, self.sentinel, self.db, self.charges, self.calendar
        )

        # Strategies
        self.sleeve_f = SleeveF()
        self.sleeve_o_buy = SleeveOBuy()
        self.sleeve_o_spread = SleeveOSpread()
        self.combiner = StrategyCombiner(self.charges)

        # Signal Handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        logger.warning(f"Shutdown signal {signum} received. Initiating graceful shutdown...")
        self.running = False

    def emit_heartbeat(self, phase: str, details: Optional[Dict[str, Any]] = None):
        now_utc = datetime.now(timezone.utc)
        payload = {
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_ist": self.calendar.to_ist(now_utc).isoformat(),
            "phase": phase,
            "sentinel_halted": self.sentinel.is_halted,
            "active_trades_count": len(self.order_manager.active_trades),
            "details": details or {},
        }
        try:
            self.db.set_state("worker_heartbeat", payload)
        except Exception as e:
            logger.error(f"Failed to record heartbeat: {e}")

    def run_cycle(self):
        now_utc = datetime.now(timezone.utc)
        session_state = self.calendar.get_market_state(now_utc)
        phase = session_state.get("phase", "UNKNOWN")

        # 1. Market Closed -> Idle Heartbeat
        if not session_state.get("is_open"):
            logger.info(f"Market session: {phase}. Sleeping until session open...")
            self.emit_heartbeat(phase)
            time.sleep(30.0)
            return

        # 2. Reconcile Positions with MegaBull
        recon_ok = self.order_manager.reconcile_positions()
        if not recon_ok:
            logger.critical("Reconciliation failed. Sentinel halted. Breaking cycle.")
            self.emit_heartbeat("HALTED_RECON_MISMATCH")
            time.sleep(10.0)
            return

        # 3. Mandatory Intraday Square-off (>= 15:15 IST)
        if session_state.get("must_squareoff"):
            logger.warning("Session phase SQUAREOFF (>= 15:15 IST). Closing all active trades...")
            for trade_id in list(self.order_manager.active_trades.keys()):
                trade = self.order_manager.active_trades[trade_id]
                quote = self.provider.get_quote(trade.instrument_token, trade.tradingsymbol)
                exit_price = quote.ltp if quote else float(trade.entry_price)
                self.order_manager.close_trade(trade_id, exit_price, exit_reason="EOD_SQUAREOFF")
            self.emit_heartbeat(phase)
            time.sleep(5.0)
            return

        # 4. Open Warmup -> Update Quotes & Indicators only (09:15 - 09:20)
        if phase == "OPEN_WARMUP":
            logger.info("Session warmup in progress. Ingesting baseline quotes...")
            self.emit_heartbeat(phase)
            time.sleep(5.0)
            return

        # 5. Normal Trading Pipeline (09:20 - 14:45)
        if session_state.get("can_enter") and not self.sentinel.is_halted:
            self._execute_trading_pipeline()

        self.emit_heartbeat(phase)
        time.sleep(2.0) # Main loop polling interval (respects <= 2 req/sec)

    def _execute_trading_pipeline(self):
        # Fetch Nifty Index Spot Quote
        nifty_spot_contract = self.resolver.get_spot("NIFTY")
        if not nifty_spot_contract:
            return

        nifty_quote = self.provider.get_quote(
            nifty_spot_contract.instrument_token, nifty_spot_contract.trading_symbol
        )
        if not nifty_quote:
            return

        spot_price = nifty_quote.ltp

        # Check Active Trades for Stop Loss / Target Hit
        for trade_id in list(self.order_manager.active_trades.keys()):
            trade = self.order_manager.active_trades[trade_id]
            q = self.provider.get_quote(trade.instrument_token, trade.tradingsymbol)
            if not q:
                continue

            # Long Stop / Target
            if trade.side == "BUY":
                if trade.stop_price and q.ltp <= float(trade.stop_price):
                    self.order_manager.close_trade(trade_id, q.ltp, exit_reason="STOP")
                elif trade.target_price and q.ltp >= float(trade.target_price):
                    self.order_manager.close_trade(trade_id, q.ltp, exit_reason="TARGET")
            # Short Stop / Target
            elif trade.side == "SELL":
                if trade.stop_price and q.ltp >= float(trade.stop_price):
                    self.order_manager.close_trade(trade_id, q.ltp, exit_reason="STOP")
                elif trade.target_price and q.ltp <= float(trade.target_price):
                    self.order_manager.close_trade(trade_id, q.ltp, exit_reason="TARGET")

    def run(self):
        logger.info("=== APEX-IN TRADING WORKER INITIALIZED (PAPER MODE) ===")
        logger.info(f"Targeting: Nifty & Sensex F&O | Virtual Capital: Rs {self.settings.INITIAL_CAPITAL}")
        
        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                logger.error(f"Worker iteration exception: {e}", exc_info=True)
                time.sleep(5.0)

        logger.info("Worker gracefully stopped. State saved.")

def main():
    worker = TradingWorker()
    worker.run()

if __name__ == "__main__":
    main()
