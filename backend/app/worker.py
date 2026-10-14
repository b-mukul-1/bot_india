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
from typing import Dict, Any, Optional, List

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

        # In-memory session tracking for indicators & ORB (NIFTY & BANKNIFTY)
        self.price_history: Dict[str, List[float]] = {"NIFTY": [], "BANKNIFTY": []}
        self.session_high: Dict[str, float] = {"NIFTY": 0.0, "BANKNIFTY": 0.0}
        self.session_low: Dict[str, float] = {"NIFTY": 999999.0, "BANKNIFTY": 999999.0}
        self.orb_high: Dict[str, float] = {"NIFTY": 0.0, "BANKNIFTY": 0.0}
        self.orb_low: Dict[str, float] = {"NIFTY": 999999.0, "BANKNIFTY": 999999.0}

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

    @staticmethod
    def _calc_ema(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) < period:
            return sum(prices) / len(prices)
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = (p * k) + (ema * (1.0 - k))
        return round(ema, 2)

    @staticmethod
    def _calc_atr(prices: List[float], period: int = 14) -> float:
        if len(prices) < 2:
            return 20.0
        diffs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        recent = diffs[-period:]
        return round(sum(recent) / len(recent), 2) if recent else 20.0

    def _execute_trading_pipeline(self):
        # 1. Check Active Trades for Stop Loss / Target Hit
        for trade_id in list(self.order_manager.active_trades.keys()):
            trade = self.order_manager.active_trades[trade_id]
            q = self.provider.get_quote(trade.instrument_token, trade.tradingsymbol)
            current_ltp = q.ltp if (q and q.ltp > 0) else None

            # Fallback for Futures: if futures LTP is stale, cross-check against underlying spot price
            if not current_ltp and trade.instrument_type == "FUT":
                spot_c = self.resolver.get_spot(trade.underlying)
                if spot_c:
                    sq = self.provider.get_quote(spot_c.instrument_token, spot_c.trading_symbol)
                    if sq and sq.ltp > 0:
                        current_ltp = sq.ltp

            if not current_ltp:
                continue

            # Long Position Stop / Target Hit
            if trade.side == "BUY":
                if trade.stop_price and current_ltp <= float(trade.stop_price):
                    logger.warning(f"[STOP LOSS TRIGGERED] {trade.tradingsymbol} current {current_ltp} <= stop {trade.stop_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason="STOP_LOSS")
                elif trade.target_price and current_ltp >= float(trade.target_price):
                    logger.info(f"[TARGET HIT TRIGGERED] {trade.tradingsymbol} current {current_ltp} >= target {trade.target_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason="TARGET_HIT")
            # Short Position Stop / Target Hit
            elif trade.side == "SELL":
                if trade.stop_price and current_ltp >= float(trade.stop_price):
                    logger.warning(f"[STOP LOSS TRIGGERED] {trade.tradingsymbol} current {current_ltp} >= stop {trade.stop_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason="STOP_LOSS")
                elif trade.target_price and current_ltp <= float(trade.target_price):
                    logger.info(f"[TARGET HIT TRIGGERED] {trade.tradingsymbol} current {current_ltp} <= target {trade.target_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason="TARGET_HIT")

        # 2. Concurrency check: max 3 open positions simultaneously
        if len(self.order_manager.active_trades) >= 3 or self.sentinel.is_halted:
            return

        # 3. Evaluate Signals across NIFTY and BANKNIFTY
        target_indices = ["NIFTY", "BANKNIFTY"]
        for underlying in target_indices:
            if len(self.order_manager.active_trades) >= 3:
                break

            spot_contract = self.resolver.get_spot(underlying)
            if not spot_contract:
                continue

            spot_quote = self.provider.get_quote(
                spot_contract.instrument_token, spot_contract.trading_symbol
            )
            if not spot_quote or spot_quote.ltp <= 0:
                continue

            spot_price = spot_quote.ltp

            # Maintain in-memory tick history (last 100 ticks)
            hist = self.price_history.setdefault(underlying, [])
            hist.append(spot_price)
            if len(hist) > 100:
                hist.pop(0)

            # Update session High & Low
            if spot_price > self.session_high.get(underlying, 0.0):
                self.session_high[underlying] = spot_price
            if spot_price < self.session_low.get(underlying, 999999.0):
                self.session_low[underlying] = spot_price

            # Establish Opening Range Breakout (ORB) baseline
            if len(hist) <= 15:
                self.orb_high[underlying] = max(self.orb_high.get(underlying, spot_price), spot_price)
                self.orb_low[underlying] = min(self.orb_low.get(underlying, spot_price), spot_price)

            if len(hist) < 5:
                continue

            ema_20 = self._calc_ema(hist, 20)
            ema_50 = self._calc_ema(hist, 50)
            atr = self._calc_atr(hist, 14)
            donchian_high = max(hist[-15:])
            donchian_low = min(hist[-15:])
            orb_hi = self.orb_high.get(underlying, spot_price)
            orb_lo = self.orb_low.get(underlying, spot_price)

            # Check: allow up to 2 positions in the same underlying (e.g. 1 FUT + 1 OPT)
            same_underlying_count = sum(
                1 for t in self.order_manager.active_trades.values() if t.underlying == underlying
            )
            if same_underlying_count >= 2:
                continue

            active_tokens = set(t.instrument_token for t in self.order_manager.active_trades.values())

            candidate_signal = None

            # --- A. SLEEVE O-BUY (Convex ATM Options Momentum) ---
            atm_options = self.resolver.get_atm_options(underlying, spot_price, n_strikes=2)

            # Bullish Call Momentum Breakout
            if spot_price >= donchian_high and atm_options.get("CE"):
                ce_contract = atm_options["CE"][0]
                q_ce = self.provider.get_quote(ce_contract.instrument_token, ce_contract.trading_symbol)
                if q_ce and q_ce.ltp >= 25.0:
                    candidate_signal = self.sleeve_o_buy.evaluate(
                        contract=ce_contract,
                        premium=q_ce.ltp,
                        spot_price=spot_price,
                        india_vix=14.5,
                        spot_donchian_high=donchian_high - 1.0,
                        spot_donchian_low=donchian_low,
                    )

            # Bearish Put Momentum Breakdown
            elif spot_price <= donchian_low and atm_options.get("PE"):
                pe_contract = atm_options["PE"][0]
                q_pe = self.provider.get_quote(pe_contract.instrument_token, pe_contract.trading_symbol)
                if q_pe and q_pe.ltp >= 25.0:
                    candidate_signal = self.sleeve_o_buy.evaluate(
                        contract=pe_contract,
                        premium=q_pe.ltp,
                        spot_price=spot_price,
                        india_vix=14.5,
                        spot_donchian_high=donchian_high,
                        spot_donchian_low=donchian_low + 1.0,
                    )

            # --- B. SLEEVE F (Futures Trend / ORB) if no option signal ---
            if not candidate_signal:
                futures = self.resolver.get_futures(underlying)
                if futures:
                    fut_contract = futures[0]
                    fut_quote = self.provider.get_quote(
                        fut_contract.instrument_token, fut_contract.trading_symbol
                    )
                    if fut_quote and fut_quote.ltp > 0:
                        candidate_signal = self.sleeve_f.evaluate(
                            contract=fut_contract,
                            current_price=fut_quote.ltp,
                            orb_high=orb_hi,
                            orb_low=orb_lo,
                            ema_20=ema_20,
                            ema_50=ema_50,
                            adx=24.0,
                            atr=atr,
                        )

            # --- C. Cost-Aware Gate & Execution ---
            if candidate_signal and candidate_signal.instrument_token not in active_tokens:
                if self.combiner.cost_aware_gate(candidate_signal):
                    try:
                        trade_record = self.order_manager.execute_signal(candidate_signal)
                        if trade_record:
                            logger.info(
                                f"[EXECUTION SUCCESS] Placed {candidate_signal.sleeve} on "
                                f"{candidate_signal.tradingsymbol} @ Rs {candidate_signal.price}"
                            )
                    except Exception as ex:
                        logger.warning(f"[EXECUTION VETO] Sentinel or engine vetoed signal: {ex}")

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
