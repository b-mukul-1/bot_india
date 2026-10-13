"""
Tests for DB persistence and CSV export
Verifies schema, BOM encoding, round-trip import into pandas, column matching,
and the fundamental accounting assertion: net_pnl == gross_pnl - total_charges.
"""

import io
import pytest
import pandas as pd
from decimal import Decimal
from backend.app.store.db import DatabaseManager
from backend.app.store.models import TradeRecord
from backend.app.charges.engine import ChargesEngine
from backend.app.export.csv_export import export_trades_to_csv_bytes, TRADE_CSV_COLUMNS

@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "test_trades.db"
    mgr = DatabaseManager(db_url=f"sqlite:///{db_file}")
    mgr.init_tables()
    return mgr

def test_trade_db_persistence_and_csv_export(db_manager):
    engine = ChargesEngine()
    # Compute round trip for a Nifty option trade
    rt = engine.calculate_round_trip(
        instrument_type="CE",
        entry_side="BUY",
        entry_price=120.0,
        exit_price=150.0,
        quantity=65,
        exchange="NSE",
        brokerage_per_order=20.0,
    )

    trade = TradeRecord(
        trade_id="TRD-20261014-001",
        strategy_id="O_BUY_MOMENTUM_V1",
        sleeve="O_BUY",
        signal_reason="Breakout_Above_20EMA",
        algo_version="1.0.0",
        config_hash="abc12345",
        underlying="NIFTY",
        instrument_type="CE",
        tradingsymbol="NIFTY2680424750CE",
        instrument_token="16868098",
        expiry="04 AUG",
        strike=Decimal("24750.00"),
        lot_size=65,
        lots=1,
        quantity=65,
        side="BUY",
        decision_time_ist="2026-10-14T10:15:00+05:30",
        order_sent_time_ist="2026-10-14T10:15:01+05:30",
        fill_time_ist="2026-10-14T10:15:02+05:30",
        order_type="LIMIT",
        limit_price=Decimal("120.00"),
        entry_price=Decimal("120.00"),
        ltp_at_decision=Decimal("119.80"),
        bid=None,  # Missing from feed -> NULL
        bid_qty=None,
        ask=None,
        ask_qty=None,
        volume=None,
        oi=None,
        underlying_spot=Decimal("24740.00"),
        india_vix=Decimal("13.40"),
        stop_price=Decimal("90.00"),
        target_price=Decimal("180.00"),
        risk_amount_inr=Decimal("1950.00"),
        margin_or_premium_used=Decimal("7800.00"),
        data_quality_flags="MISSING_DEPTH_AND_VOLUME",
        spread_modeled=Decimal("0.80"),
        conservative_fill_price_modeled=Decimal("120.40"),
        exit_time_ist="2026-10-14T11:45:00+05:30",
        exit_price=Decimal("150.00"),
        exit_reason="TARGET",
        holding_seconds=5400,
        conservative_exit_price_modeled=Decimal("149.60"),
        brokerage=rt.brokerage,
        stt=rt.stt,
        exchange_txn=rt.exchange_txn,
        sebi_fee=rt.sebi_fee,
        stamp_duty=rt.stamp_duty,
        ipft=rt.ipft,
        gst=rt.gst,
        total_charges=rt.total_charges,
        charges_as_pct_of_turnover=rt.charges_as_pct_of_turnover,
        gross_pnl=rt.gross_pnl,
        net_pnl=rt.net_pnl,
        net_pnl_pct_of_capital=Decimal("0.3840"),
        r_multiple=Decimal("1.00"),
    )

    db_manager.save_trade(trade)

    # Retrieve from DB
    loaded = db_manager.get_trade("TRD-20261014-001")
    assert loaded is not None
    assert loaded.tradingsymbol == "NIFTY2680424750CE"
    assert loaded.bid is None
    assert loaded.data_quality_flags == "MISSING_DEPTH_AND_VOLUME"
    assert loaded.net_pnl == loaded.gross_pnl - loaded.total_charges

    # Export to CSV bytes
    all_trades = db_manager.list_trades()
    csv_bytes = export_trades_to_csv_bytes(all_trades)

    # Re-import with pandas and assert correctness
    df = pd.read_csv(io.BytesIO(csv_bytes), encoding="utf-8")
    assert len(df) == 1
    assert list(df.columns) == TRADE_CSV_COLUMNS

    row = df.iloc[0]
    assert row["trade_id"] == "TRD-20261014-001"
    assert pd.isna(row["bid"]) or row["bid"] == ""
    assert row["data_quality_flags"] == "MISSING_DEPTH_AND_VOLUME"

    # Core accounting test: net_pnl = gross_pnl - total_charges
    gross = float(row["gross_pnl"])
    charges = float(row["total_charges"])
    net = float(row["net_pnl"])
    assert round(net, 2) == round(gross - charges, 2)
