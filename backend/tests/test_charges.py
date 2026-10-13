"""
Tests for APEX-IN Charges Engine
Verifies Indian F&O statutory levies (post-April-2026 rates), brokerage, golden test cases,
side rules (STT on sell only, stamp on buy only), and rounding rules.
"""

import pytest
from decimal import Decimal
from backend.app.charges.engine import ChargesEngine

@pytest.fixture
def engine():
    return ChargesEngine()

def test_nifty_futures_sanity_check(engine):
    """
    Sanity check from Section 2:
    A Nifty futures round trip at ~23,150 with a lot of ~65 and Rs 40 total brokerage
    should come to roughly Rs 900 (STT is ~84% of it, ~Rs 752), within a few percent.
    Turnover per leg = 23,150 * 65 = 15,04,750 INR.
    STT (sell leg, 0.05%) = 15,04,750 * 0.0005 = 752.38 INR.
    Brokerage = 20 * 2 = 40 INR.
    Exchange txn (both legs, 0.00173%) = 2 * 15,04,750 * 0.0000173 = 52.06 INR.
    Stamp duty (buy leg, 0.002%) = 15,04,750 * 0.00002 = 30.10 INR.
    SEBI fee = 2 * 15,04,750 * 0.000001 = 3.01 INR.
    IPFT = 2 * 15,04,750 * 0.000001 = 3.01 INR.
    GST = 18% on (40 + 52.06 + 3.01 + 3.01) = 17.65 INR.
    Total ~ 898.21 INR.
    """
    rt = engine.calculate_round_trip(
        instrument_type="FUT",
        entry_side="BUY",
        entry_price=23150.0,
        exit_price=23150.0,
        quantity=65,
        exchange="NSE",
        brokerage_per_order=20.0,
    )
    assert 870.0 <= float(rt.total_charges) <= 930.0, f"Expected ~900, got {rt.total_charges}"
    stt_share = float(rt.stt / rt.total_charges)
    assert 0.80 <= stt_share <= 0.88, f"STT should be ~84% of total charges, got {stt_share:.2%}"
    assert rt.entry_leg.stt == Decimal("0.00"), "Buy leg must have ZERO STT"
    assert rt.exit_leg.stt > Decimal("700.00"), "Sell leg must have STT"
    assert rt.exit_leg.stamp_duty == Decimal("0.00"), "Sell leg must have ZERO stamp duty"
    assert rt.entry_leg.stamp_duty > Decimal("25.00"), "Buy leg must have stamp duty"

def test_option_round_trip_golden_case(engine):
    """
    Test option round trip on a ~Rs 6,500 premium position (e.g. 1 lot 65 @ 100 premium).
    Entry: BUY 65 qty @ 100 = 6,500 INR turnover.
    Exit: SELL 65 qty @ 110 = 7,150 INR turnover.
    Brokerage = 20 + 20 = 40 INR.
    STT (sell leg, 0.15% of 7,150) = 10.73 INR.
    Exchange txn (0.035% on 6,500 + 7,150) = 2.28 + 2.50 = 4.78 INR.
    Stamp duty (buy leg, 0.003% of 6,500) = 0.20 INR.
    SEBI fee (0.0001% of 13,650) = 0.01 INR.
    IPFT (0.0005% of 13,650) = 0.07 INR.
    GST (18% of brokerage 40 + exch 4.78 + sebi 0.01 + ipft 0.07 = 44.86) = 8.07 INR.
    Total charges ~ 63.86 INR (~1% of premium position).
    Gross PnL = (110 - 100) * 65 = 650.00 INR.
    Net PnL = 650 - 63.86 = 586.14 INR.
    """
    rt = engine.calculate_round_trip(
        instrument_type="CE",
        entry_side="BUY",
        entry_price=100.0,
        exit_price=110.0,
        quantity=65,
        exchange="NSE",
        brokerage_per_order=20.0,
    )
    assert 60.0 <= float(rt.total_charges) <= 70.0, f"Expected ~64, got {rt.total_charges}"
    assert rt.gross_pnl == Decimal("650.00")
    assert rt.net_pnl == rt.gross_pnl - rt.total_charges
    assert rt.entry_leg.stt == Decimal("0.00")
    assert rt.exit_leg.stamp_duty == Decimal("0.00")
    assert rt.entry_leg.stamp_duty > Decimal("0.00")
    assert rt.exit_leg.stt > Decimal("0.00")

def test_stt_sell_only_and_stamp_buy_only(engine):
    """Verifies statutory rule: STT only on SELL, stamp duty only on BUY."""
    buy_leg = engine.calculate_leg(
        side="BUY",
        instrument_type="PE",
        price=150.0,
        quantity=65,
        exchange="NSE"
    )
    assert buy_leg.stt == Decimal("0.00"), "STT must be 0 on BUY leg"
    assert buy_leg.stamp_duty > Decimal("0.00"), "Stamp duty must be > 0 on BUY leg"

    sell_leg = engine.calculate_leg(
        side="SELL",
        instrument_type="PE",
        price=150.0,
        quantity=65,
        exchange="NSE"
    )
    assert sell_leg.stt > Decimal("0.00"), "STT must be > 0 on SELL leg"
    assert sell_leg.stamp_duty == Decimal("0.00"), "Stamp duty must be 0 on SELL leg"

def test_no_negative_charges(engine):
    """All charge components must be non-negative."""
    for inst in ["FUT", "CE", "PE"]:
        for side in ["BUY", "SELL"]:
            leg = engine.calculate_leg(side=side, instrument_type=inst, price=50.0, quantity=50)
            assert leg.brokerage >= 0
            assert leg.stt >= 0
            assert leg.exchange_txn >= 0
            assert leg.sebi_fee >= 0
            assert leg.stamp_duty >= 0
            assert leg.ipft >= 0
            assert leg.gst >= 0
            assert leg.total_charges >= 0
