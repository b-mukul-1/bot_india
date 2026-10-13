"""
APEX-IN Database Models (SQLAlchemy)
Postgres-compatible schema for trades, trade_events, and system state.
Never drops data; preserves all entry/exit snapshots and raw API payloads.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class TradeRecord(Base):
    """
    Round-trip trade record holding immutable entry decision snapshot,
    market data at fill, exit snapshot, charges breakdown, and PnL.
    """
    __tablename__ = "trades"

    # Identity
    trade_id = Column(String(64), primary_key=True, index=True)
    strategy_id = Column(String(64), nullable=False)
    sleeve = Column(String(32), nullable=False)  # "F", "O_BUY", "O_SPREAD"
    signal_reason = Column(String(255), nullable=True)
    algo_version = Column(String(32), default="1.0.0")
    config_hash = Column(String(64), nullable=True)

    # Instrument
    underlying = Column(String(32), nullable=False)  # "NIFTY", "SENSEX"
    instrument_type = Column(String(16), nullable=False)  # "FUT", "CE", "PE"
    tradingsymbol = Column(String(64), nullable=False)
    instrument_token = Column(String(32), nullable=False)
    expiry = Column(String(32), nullable=True)
    strike = Column(Numeric(10, 2), nullable=True)
    lot_size = Column(Integer, nullable=False, default=1)
    lots = Column(Integer, nullable=False, default=1)
    quantity = Column(Integer, nullable=False)
    side = Column(String(8), nullable=False)  # "BUY" or "SELL"

    # Entry Decision & Execution
    decision_time_ist = Column(String(64), nullable=False)
    order_sent_time_ist = Column(String(64), nullable=True)
    fill_time_ist = Column(String(64), nullable=True)
    order_type = Column(String(16), nullable=False, default="LIMIT")
    limit_price = Column(Numeric(12, 2), nullable=True)
    entry_price = Column(Numeric(12, 2), nullable=True)  # Fill price
    ltp_at_decision = Column(Numeric(12, 2), nullable=True)

    # Market snapshot at entry (NULL if missing from provider)
    bid = Column(Numeric(12, 2), nullable=True)
    bid_qty = Column(Integer, nullable=True)
    ask = Column(Numeric(12, 2), nullable=True)
    ask_qty = Column(Integer, nullable=True)
    spread_abs = Column(Numeric(12, 2), nullable=True)
    spread_pct = Column(Numeric(8, 4), nullable=True)
    mid = Column(Numeric(12, 2), nullable=True)
    slippage_vs_mid = Column(Numeric(12, 2), nullable=True)
    volume = Column(Integer, nullable=True)
    oi = Column(Integer, nullable=True)
    oi_change = Column(Integer, nullable=True)
    underlying_spot = Column(Numeric(12, 2), nullable=True)
    india_vix = Column(Numeric(8, 2), nullable=True)
    iv = Column(Numeric(8, 4), nullable=True)
    delta = Column(Numeric(8, 4), nullable=True)
    theta = Column(Numeric(8, 4), nullable=True)

    # Risk & Sizing
    stop_price = Column(Numeric(12, 2), nullable=True)
    target_price = Column(Numeric(12, 2), nullable=True)
    risk_amount_inr = Column(Numeric(12, 2), nullable=True)
    margin_or_premium_used = Column(Numeric(12, 2), nullable=True)
    data_quality_flags = Column(String(128), default="OK")

    # Modeled Spread & Conservative Fill
    spread_modeled = Column(Numeric(12, 2), nullable=True)
    conservative_fill_price_modeled = Column(Numeric(12, 2), nullable=True)

    # Exit Snapshot
    exit_time_ist = Column(String(64), nullable=True)
    exit_price = Column(Numeric(12, 2), nullable=True)
    exit_reason = Column(String(32), nullable=True)  # STOP, TARGET, TRAIL, TIME, EOD_SQUAREOFF, KILL, MANUAL
    exit_bid = Column(Numeric(12, 2), nullable=True)
    exit_ask = Column(Numeric(12, 2), nullable=True)
    exit_volume = Column(Integer, nullable=True)
    holding_seconds = Column(Integer, nullable=True)
    mae = Column(Numeric(12, 2), nullable=True)
    mfe = Column(Numeric(12, 2), nullable=True)
    conservative_exit_price_modeled = Column(Numeric(12, 2), nullable=True)

    # Charges Breakdown (Total round-trip)
    brokerage = Column(Numeric(12, 2), nullable=False, default=0.0)
    stt = Column(Numeric(12, 2), nullable=False, default=0.0)
    exchange_txn = Column(Numeric(12, 2), nullable=False, default=0.0)
    sebi_fee = Column(Numeric(12, 2), nullable=False, default=0.0)
    stamp_duty = Column(Numeric(12, 2), nullable=False, default=0.0)
    ipft = Column(Numeric(12, 2), nullable=False, default=0.0)
    gst = Column(Numeric(12, 2), nullable=False, default=0.0)
    total_charges = Column(Numeric(12, 2), nullable=False, default=0.0)
    charges_as_pct_of_turnover = Column(Numeric(8, 4), nullable=True)

    # P&L
    gross_pnl = Column(Numeric(12, 2), nullable=True)
    net_pnl = Column(Numeric(12, 2), nullable=True)
    net_pnl_pct_of_capital = Column(Numeric(8, 4), nullable=True)
    r_multiple = Column(Numeric(8, 2), nullable=True)
    conservative_net_pnl_modeled = Column(Numeric(12, 2), nullable=True)

    # Audit Timestamps
    created_at_utc = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at_utc = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    events = relationship("TradeEventRecord", back_populates="trade", cascade="all, delete-orphan")


class TradeEventRecord(Base):
    """
    Lifecycle event log (place, fill, modify, cancel, reconcile)
    Preserves exact raw API responses from MegaBull.
    """
    __tablename__ = "trade_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(64), ForeignKey("trades.trade_id"), nullable=False, index=True)
    order_id = Column(Integer, nullable=True, index=True)
    event_type = Column(String(32), nullable=False)  # PLACE, FILL, MODIFY, CANCEL, RECONCILE
    timestamp_utc = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    timestamp_ist = Column(String(64), nullable=False)
    message = Column(String(255), nullable=True)
    raw = Column(JSON, nullable=True)

    trade = relationship("TradeRecord", back_populates="events")


class SystemStateRecord(Base):
    """
    Key-value persistence for system equity, peak equity, drawdown,
    risk sentinel counters, and reconciliation anchors.
    """
    __tablename__ = "system_state"

    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at_utc = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# Indexes for efficient querying by date, underlying, and strategy
Index("ix_trades_underlying_created", TradeRecord.underlying, TradeRecord.created_at_utc)
Index("ix_trades_sleeve_created", TradeRecord.sleeve, TradeRecord.created_at_utc)
