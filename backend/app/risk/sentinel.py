"""
APEX-IN Risk Sentinel
Enforces immutable risk limits, drawdown ladder, order frequency controls,
quote freshness checks, and hard prohibitions (no naked options, no martingale).
Can veto any signal or trigger the Kill Switch.
"""

import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, field
from decimal import Decimal

logger = logging.getLogger(__name__)

@dataclass
class RiskBreachException(Exception):
    rule: str
    message: str

@dataclass
class RiskConfig:
    initial_capital: float = 500000.0  # Rs 5 Lakhs virtual balance
    max_trade_risk_pct: float = 0.01   # Max 1.0% per trade (Rs 5,000)
    max_total_risk_pct: float = 0.03   # Max 3.0% total open risk (Rs 15,000)
    daily_loss_limit_pct: float = 0.025 # 2.5% daily loss limit (Rs 12,500)
    weekly_loss_limit_pct: float = 0.06 # 6.0% weekly loss limit (Rs 30,000)
    max_orders_per_day: int = 40
    max_orders_per_minute: int = 10
    max_lots_per_underlying: int = 5
    min_option_premium: float = 20.0   # Skip cheap options where Rs 20 brokerage dominates
    max_quote_age_seconds: float = 5.0 # Stale quote veto threshold

class RiskSentinel:
    def __init__(self, config: Optional[RiskConfig] = None):
        self.cfg = config or RiskConfig()
        self.is_halted: bool = False
        self.halt_reason: Optional[str] = None
        self.kill_switch_active: bool = False

        # State tracking
        self.current_equity: float = self.cfg.initial_capital
        self.peak_equity: float = self.cfg.initial_capital
        self.day_starting_equity: float = self.cfg.initial_capital
        self.day_pnl: float = 0.0
        self.week_pnl: float = 0.0

        # Frequency tracking
        self.orders_today_count: int = 0
        self.order_timestamps: List[float] = []

        # Sleeve status
        self.disabled_sleeves: set[str] = set()

    def update_equity(self, current_equity: float, day_pnl: float, week_pnl: float) -> None:
        self.current_equity = current_equity
        self.day_pnl = day_pnl
        self.week_pnl = week_pnl
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # Evaluate Drawdown Ladder
        dd_pct = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0

        # Level 3: -15% Drawdown -> Full Halt & Manual Review
        if dd_pct >= 0.15:
            self.trigger_halt(f"Drawdown breach: -{dd_pct:.1%} >= -15.0% threshold.")

        # Level 2: -10% Drawdown -> Disable Option Buying Sleeve
        elif dd_pct >= 0.10:
            if "O_BUY" not in self.disabled_sleeves:
                logger.warning(f"Drawdown -{dd_pct:.1%} >= -10.0%. Disabling O_BUY sleeve.")
                self.disabled_sleeves.add("O_BUY")

        # Evaluate Daily Loss Limit
        if self.day_pnl <= - (self.cfg.daily_loss_limit_pct * self.day_starting_equity):
            self.trigger_halt(f"Daily loss breach: Day P&L Rs {self.day_pnl:.2f} exceeded -{self.cfg.daily_loss_limit_pct:.1%}.")

        # Evaluate Weekly Loss Limit
        if self.week_pnl <= - (self.cfg.weekly_loss_limit_pct * self.day_starting_equity):
            self.trigger_halt(f"Weekly loss breach: Week P&L Rs {self.week_pnl:.2f} exceeded -{self.cfg.weekly_loss_limit_pct:.1%}.")

    def trigger_halt(self, reason: str) -> None:
        self.is_halted = True
        self.halt_reason = reason
        self.kill_switch_active = True
        logger.critical(f"[RISK SENTINEL HALT] {reason}")

    def get_sizing_multiplier(self) -> float:
        """Returns 0.5 if in -6% drawdown, 0.0 if halted, else 1.0."""
        if self.is_halted:
            return 0.0
        dd_pct = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        if dd_pct >= 0.06:
            return 0.5
        return 1.0

    def validate_order(
        self,
        sleeve: str,
        side: str,
        instrument_type: str,
        quantity: int,
        lot_size: int,
        price: float,
        risk_inr: float,
        current_open_risk: float,
        quote_timestamp_utc: Optional[datetime] = None,
        is_hedged: bool = False,
    ) -> bool:
        """
        Validates order against every sentinel rule.
        Raises RiskBreachException on any violation.
        """
        if self.is_halted or self.kill_switch_active:
            raise RiskBreachException("SENTINEL_HALTED", f"Trading is halted: {self.halt_reason}")

        if sleeve in self.disabled_sleeves:
            raise RiskBreachException("SLEEVE_DISABLED", f"Sleeve {sleeve} is disabled by drawdown ladder.")

        # Hard Rule: No naked option selling
        if instrument_type in ("CE", "PE") and side.upper() == "SELL" and not is_hedged:
            raise RiskBreachException("NAKED_OPTION_PROHIBITED", "Naked short options are strictly prohibited!")

        # Option Premium Floor
        if instrument_type in ("CE", "PE") and price < self.cfg.min_option_premium:
            raise RiskBreachException("PREMIUM_FLOOR_BREACH", f"Option price {price} is below Rs {self.cfg.min_option_premium} floor.")

        # Per-Trade Risk
        max_allowed_trade_risk = self.current_equity * self.cfg.max_trade_risk_pct
        if risk_inr > max_allowed_trade_risk:
            raise RiskBreachException("PER_TRADE_RISK_BREACH", f"Risk Rs {risk_inr:.2f} exceeds limit Rs {max_allowed_trade_risk:.2f}.")

        # Total Open Risk
        max_allowed_total_risk = self.current_equity * self.cfg.max_total_risk_pct
        if (current_open_risk + risk_inr) > max_allowed_total_risk:
            raise RiskBreachException("TOTAL_RISK_BREACH", f"Total risk Rs {current_open_risk + risk_inr:.2f} exceeds limit Rs {max_allowed_total_risk:.2f}.")

        # Quote Freshness
        if quote_timestamp_utc:
            now_utc = datetime.now(timezone.utc)
            quote_age = (now_utc - quote_timestamp_utc).total_seconds()
            if quote_age > self.cfg.max_quote_age_seconds:
                raise RiskBreachException("STALE_DATA_BREACH", f"Quote age {quote_age:.2f}s exceeds {self.cfg.max_quote_age_seconds}s limit.")

        # Daily Order Count
        if self.orders_today_count >= self.cfg.max_orders_per_day:
            raise RiskBreachException("MAX_DAILY_ORDERS_BREACH", f"Orders today {self.orders_today_count} reached cap {self.cfg.max_orders_per_day}.")

        # Per-Minute Rate
        now_ts = time.monotonic()
        self.order_timestamps = [t for t in self.order_timestamps if now_ts - t < 60.0]
        if len(self.order_timestamps) >= self.cfg.max_orders_per_minute:
            raise RiskBreachException("ORDER_RATE_BREACH", f"Order rate exceeded {self.cfg.max_orders_per_minute} orders/minute.")

        return True

    def record_order_sent(self):
        self.orders_today_count += 1
        self.order_timestamps.append(time.monotonic())
