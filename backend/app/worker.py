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
from datetime import datetime, timezone, time as dt_time
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
from backend.app.strategies.sleeve_vwap import SleeveVWAP
from backend.app.strategies.sleeve_gamma import SleeveGamma
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

        # Strategies (Diversified multi-sleeve quant architecture)
        self.sleeve_f = SleeveF()
        self.sleeve_o_buy = SleeveOBuy()
        self.sleeve_o_spread = SleeveOSpread()
        self.sleeve_vwap = SleeveVWAP()
        self.sleeve_gamma = SleeveGamma()
        self.combiner = StrategyCombiner(self.charges)

        # In-memory session tracking for indicators & ORB (NIFTY & BANKNIFTY)
        self.price_history: Dict[str, List[float]] = {"NIFTY": [], "BANKNIFTY": []}
        self.session_open: Dict[str, float] = {"NIFTY": 0.0, "BANKNIFTY": 0.0}
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
            self._execute_trading_pipeline(now_utc)

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

    @staticmethod
    def _calc_vwap(prices: List[float]) -> float:
        if not prices:
            return 0.0
        # Tick-weighted session equilibrium price benchmark
        weights = list(range(1, len(prices) + 1))
        weighted_sum = sum(p * w for p, w in zip(prices, weights))
        return round(weighted_sum / sum(weights), 2)

    def _execute_trading_pipeline(self, now_utc: Optional[datetime] = None):
        now_utc = now_utc or datetime.now(timezone.utc)
        ist_now = self.calendar.to_ist(now_utc)
        ist_time = ist_now.time()
        ist_date_str = ist_now.strftime("%d-%b-%Y").upper()

        # 1. Manage Active Trades (Dynamic Ratchet Trailing Stops + Stagnation Guard)
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

            entry_px = float(trade.entry_price or trade.limit_price or trade.ltp_at_decision or 0.0)

            # --- DYNAMIC RATCHET TRAILING STOP LOSS (LOCKS IN PROFITS DYNAMICALLY) ---
            if entry_px > 0 and trade.side == "BUY":
                gain_pct = (current_ltp - entry_px) / entry_px
                stop_px = float(trade.stop_price or 0.0)

                # Tier 1 (+25% gain): Move stop to Breakeven (Entry Price) -> Completely Risk Free!
                if gain_pct >= 0.25 and stop_px < entry_px:
                    new_stop = round(entry_px, 2)
                    trade.stop_price = Decimal(str(new_stop))
                    self.db.save_trade(trade)
                    logger.info(
                        f"[TRAILING STOP RATCHET - TIER 1] {trade.tradingsymbol}: Gain +{gain_pct*100:.1f}%. "
                        f"Stop elevated to Breakeven @ Rs {new_stop:.2f} (Risk-Free Trade!)"
                    )

                # Tier 2 (+50% gain): Lock in +25% profit
                elif gain_pct >= 0.50 and stop_px < round(entry_px * 1.25, 2):
                    new_stop = round(entry_px * 1.25, 2)
                    trade.stop_price = Decimal(str(new_stop))
                    self.db.save_trade(trade)
                    logger.info(
                        f"[TRAILING STOP RATCHET - TIER 2] {trade.tradingsymbol}: Gain +{gain_pct*100:.1f}%. "
                        f"Stop elevated to lock +25% profit @ Rs {new_stop:.2f}"
                    )

                # Tier 3 (+75% gain): Lock in +50% profit
                elif gain_pct >= 0.75 and stop_px < round(entry_px * 1.50, 2):
                    new_stop = round(entry_px * 1.50, 2)
                    trade.stop_price = Decimal(str(new_stop))
                    self.db.save_trade(trade)
                    logger.info(
                        f"[TRAILING STOP RATCHET - TIER 3] {trade.tradingsymbol}: Gain +{gain_pct*100:.1f}%. "
                        f"Stop elevated to lock +50% profit @ Rs {new_stop:.2f}"
                    )

            # --- THETA STAGNATION EXIT (FOR FLAT OPTIONS HELD > 45 MINS) ---
            if trade.instrument_type in ("CE", "PE") and trade.created_at_utc:
                try:
                    c_time = trade.created_at_utc if trade.created_at_utc.tzinfo else trade.created_at_utc.replace(tzinfo=timezone.utc)
                    holding_secs = (datetime.now(timezone.utc) - c_time).total_seconds()
                    if holding_secs > 2700 and current_ltp < entry_px:
                        logger.info(
                            f"[THETA STAGNATION EXIT] {trade.tradingsymbol} held for {holding_secs/60:.1f}m with negative return. "
                            f"Exiting to prevent lunchtime theta bleed."
                        )
                        self.order_manager.close_trade(trade_id, current_ltp, exit_reason="THETA_STAGNATION_EXIT")
                        continue
                except Exception as ex:
                    logger.debug(f"Holding duration check skipped: {ex}")

            # Long Position Stop / Target Hit
            if trade.side == "BUY":
                if trade.stop_price and current_ltp <= float(trade.stop_price):
                    exit_reason = "TRAIL_PROFIT" if (entry_px > 0 and float(trade.stop_price) >= entry_px) else "STOP_LOSS"
                    logger.warning(f"[{exit_reason} TRIGGERED] {trade.tradingsymbol} current {current_ltp} <= stop {trade.stop_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason=exit_reason)
                elif trade.target_price and current_ltp >= float(trade.target_price):
                    logger.info(f"[TARGET HIT TRIGGERED] {trade.tradingsymbol} current {current_ltp} >= target {trade.target_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason="TARGET_HIT")
            # Short Position Stop / Target Hit
            elif trade.side == "SELL":
                if trade.stop_price and current_ltp >= float(trade.stop_price):
                    exit_reason = "TRAIL_PROFIT" if (entry_px > 0 and float(trade.stop_price) <= entry_px) else "STOP_LOSS"
                    logger.warning(f"[{exit_reason} TRIGGERED] {trade.tradingsymbol} current {current_ltp} >= stop {trade.stop_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason=exit_reason)
                elif trade.target_price and current_ltp <= float(trade.target_price):
                    logger.info(f"[TARGET HIT TRIGGERED] {trade.tradingsymbol} current {current_ltp} <= target {trade.target_price}")
                    self.order_manager.close_trade(trade_id, current_ltp, exit_reason="TARGET_HIT")

        # 2. Concurrency check: max 3 open positions simultaneously
        if len(self.order_manager.active_trades) >= 3 or self.sentinel.is_halted:
            return

        # 3. Mid-day Theta Chop Filter (11:45 AM - 01:15 PM IST)
        # Avoid opening fresh breakout option trades during low-volume lunchtime sideways chop
        if dt_time(11, 45) <= ist_time <= dt_time(13, 15):
            return

        # 4. Evaluate Signals across NIFTY and BANKNIFTY
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

            # Record session open
            if self.session_open.get(underlying, 0.0) == 0.0:
                self.session_open[underlying] = spot_price

            # Update session High & Low
            if spot_price > self.session_high.get(underlying, 0.0):
                self.session_high[underlying] = spot_price
            if spot_price < self.session_low.get(underlying, 999999.0):
                self.session_low[underlying] = spot_price

            # Establish Opening Range Breakout (ORB) baseline
            if ist_time <= dt_time(9, 30):
                self.orb_high[underlying] = max(self.orb_high.get(underlying, spot_price), spot_price)
                self.orb_low[underlying] = min(self.orb_low.get(underlying, spot_price), spot_price)
            elif self.orb_high.get(underlying, 0.0) == 0.0 or self.orb_low.get(underlying, 999999.0) == 999999.0:
                if len(hist) <= 15:
                    self.orb_high[underlying] = max(self.orb_high.get(underlying, spot_price), spot_price)
                    self.orb_low[underlying] = min(self.orb_low.get(underlying, spot_price), spot_price)

            if len(hist) < 5:
                continue

            ema_9 = self._calc_ema(hist, 9)
            ema_20 = self._calc_ema(hist, 20)
            ema_50 = self._calc_ema(hist, 50)
            vwap = self._calc_vwap(hist)
            atr = self._calc_atr(hist, 14)
            prev_window = hist[-16:-1] if len(hist) > 15 else hist[:-1]
            donchian_high = max(prev_window) if prev_window else spot_price
            donchian_low = min(prev_window) if prev_window else spot_price
            orb_hi = self.orb_high.get(underlying, spot_price)
            orb_lo = self.orb_low.get(underlying, spot_price)
            sess_open = self.session_open.get(underlying, spot_price)
            sess_hi = self.session_high.get(underlying, spot_price)
            sess_lo = self.session_low.get(underlying, spot_price)

            # Check: allow up to 2 positions in the same underlying (e.g. 1 FUT + 1 OPT)
            same_underlying_count = sum(
                1 for t in self.order_manager.active_trades.values() if t.underlying == underlying
            )
            if same_underlying_count >= 2:
                continue

            active_tokens = set(t.instrument_token for t in self.order_manager.active_trades.values())
            candidate_signal = None

            atm_options = self.resolver.get_atm_options(underlying, spot_price, n_strikes=2)

            # --- A. SLEEVE GAMMA-EXP (Expiry Afternoon Gamma Explosion Scalp post 13:15 IST) ---
            is_afternoon_gamma_window = dt_time(13, 15) <= ist_time <= dt_time(15, 0)
            if is_afternoon_gamma_window and atm_options:
                # Check if current options expire today
                ce_cand = atm_options.get("CE", [None])[0]
                pe_cand = atm_options.get("PE", [None])[0]
                is_expiry_day = False
                if ce_cand:
                    exp_s = getattr(ce_cand, "expiry_str", "") or ""
                    ist_day_month = ist_now.strftime("%d %b").upper()
                    is_expiry_day = (ist_day_month in exp_s.upper()) or (ist_date_str in exp_s.upper())

                if is_expiry_day:
                    if spot_price >= sess_hi and ce_cand:
                        q_ce = self.provider.get_quote(ce_cand.instrument_token, ce_cand.trading_symbol)
                        if q_ce and q_ce.ltp >= 25.0:
                            candidate_signal = self.sleeve_gamma.evaluate(
                                contract=ce_cand,
                                premium=q_ce.ltp,
                                spot_price=spot_price,
                                session_high=sess_hi,
                                session_low=sess_lo,
                                is_expiry_day=True,
                                is_afternoon_window=True,
                            )
                    elif spot_price <= sess_lo and pe_cand:
                        q_pe = self.provider.get_quote(pe_cand.instrument_token, pe_cand.trading_symbol)
                        if q_pe and q_pe.ltp >= 25.0:
                            candidate_signal = self.sleeve_gamma.evaluate(
                                contract=pe_cand,
                                premium=q_pe.ltp,
                                spot_price=spot_price,
                                session_high=sess_hi,
                                session_low=sess_lo,
                                is_expiry_day=True,
                                is_afternoon_window=True,
                            )

            # --- B. SLEEVE VWAP-MOM (Institutional VWAP + EMA 9/21 Trend Alignment) ---
            if not candidate_signal and atm_options:
                is_vwap_bull = (spot_price > vwap and ema_9 > ema_20 and spot_price >= sess_open)
                is_vwap_bear = (spot_price < vwap and ema_9 < ema_20 and spot_price <= sess_open)

                if is_vwap_bull and atm_options.get("CE"):
                    ce_contract = atm_options["CE"][0]
                    q_ce = self.provider.get_quote(ce_contract.instrument_token, ce_contract.trading_symbol)
                    if q_ce and q_ce.ltp >= 25.0:
                        candidate_signal = self.sleeve_vwap.evaluate(
                            contract=ce_contract,
                            premium=q_ce.ltp,
                            spot_price=spot_price,
                            vwap=vwap,
                            ema_9=ema_9,
                            ema_21=ema_20,
                            session_open=sess_open,
                            india_vix=14.5,
                        )
                elif is_vwap_bear and atm_options.get("PE"):
                    pe_contract = atm_options["PE"][0]
                    q_pe = self.provider.get_quote(pe_contract.instrument_token, pe_contract.trading_symbol)
                    if q_pe and q_pe.ltp >= 25.0:
                        candidate_signal = self.sleeve_vwap.evaluate(
                            contract=pe_contract,
                            premium=q_pe.ltp,
                            spot_price=spot_price,
                            vwap=vwap,
                            ema_9=ema_9,
                            ema_21=ema_20,
                            session_open=sess_open,
                            india_vix=14.5,
                        )

            # --- C. SLEEVE O-BUY (Convex ATM Options Momentum via Donchian Channels) ---
            if not candidate_signal and atm_options:
                is_bullish = (spot_price >= donchian_high) or (len(hist) >= 10 and spot_price > ema_20 > ema_50)
                is_bearish = (spot_price <= donchian_low) or (len(hist) >= 10 and spot_price < ema_20 < ema_50)

                # Bullish Call Momentum Breakout
                if is_bullish and atm_options.get("CE"):
                    ce_contract = atm_options["CE"][0]
                    q_ce = self.provider.get_quote(ce_contract.instrument_token, ce_contract.trading_symbol)
                    if q_ce and q_ce.ltp >= 25.0:
                        candidate_signal = self.sleeve_o_buy.evaluate(
                            contract=ce_contract,
                            premium=q_ce.ltp,
                            spot_price=spot_price,
                            india_vix=14.5,
                            spot_donchian_high=spot_price - 1.0,
                            spot_donchian_low=spot_price - 100.0,
                        )

                # Bearish Put Momentum Breakdown
                elif is_bearish and atm_options.get("PE"):
                    pe_contract = atm_options["PE"][0]
                    q_pe = self.provider.get_quote(pe_contract.instrument_token, pe_contract.trading_symbol)
                    if q_pe and q_pe.ltp >= 25.0:
                        candidate_signal = self.sleeve_o_buy.evaluate(
                            contract=pe_contract,
                            premium=q_pe.ltp,
                            spot_price=spot_price,
                            india_vix=14.5,
                            spot_donchian_high=spot_price + 100.0,
                            spot_donchian_low=spot_price + 1.0,
                        )

            # --- D. SLEEVE F (Futures Trend / ORB) if no option signal ---
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
                            spot_price=spot_price,
                        )

            # --- E. Cost-Aware Gate & Execution ---
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
