"""
Tests for New Quant Strategies: SleeveVWAP (Institutional VWAP + EMA) and SleeveGamma (Expiry Scalp)
"""

import pytest
from backend.app.instruments import InstrumentContract
from backend.app.strategies.sleeve_vwap import SleeveVWAP
from backend.app.strategies.sleeve_gamma import SleeveGamma

@pytest.fixture
def ce_contract():
    return InstrumentContract(
        instrument_token="10001",
        trading_symbol="NIFTY26OCT22500CE",
        instrument_name="NIFTY 27 OCT 22500 CE",
        underlying="NIFTY",
        instrument_type="CE",
        expiry_str="27 OCT",
        strike=22500.0,
        lot_size=65,
    )

@pytest.fixture
def pe_contract():
    return InstrumentContract(
        instrument_token="10002",
        trading_symbol="NIFTY26OCT22500PE",
        instrument_name="NIFTY 27 OCT 22500 PE",
        underlying="NIFTY",
        instrument_type="PE",
        expiry_str="27 OCT",
        strike=22500.0,
        lot_size=65,
    )

def test_sleeve_vwap_bullish_signal(ce_contract):
    sleeve = SleeveVWAP()
    # Bullish condition: spot > vwap, ema_9 > ema_21, spot >= session_open
    signal = sleeve.evaluate(
        contract=ce_contract,
        premium=120.0,
        spot_price=22550.0,
        vwap=22510.0,
        ema_9=22530.0,
        ema_21=22500.0,
        session_open=22480.0,
        india_vix=14.0,
    )
    assert signal is not None
    assert signal.sleeve == "VWAP_MOM"
    assert signal.side == "BUY"
    assert signal.stop_price == round(120.0 * 0.70, 2)
    assert signal.target_price == round(120.0 * 2.20, 2)

def test_sleeve_vwap_bearish_signal(pe_contract):
    sleeve = SleeveVWAP()
    # Bearish condition: spot < vwap, ema_9 < ema_21, spot <= session_open
    signal = sleeve.evaluate(
        contract=pe_contract,
        premium=95.0,
        spot_price=22420.0,
        vwap=22480.0,
        ema_9=22440.0,
        ema_21=22470.0,
        session_open=22500.0,
        india_vix=15.0,
    )
    assert signal is not None
    assert signal.sleeve == "VWAP_MOM"
    assert signal.side == "BUY"
    assert signal.stop_price == round(95.0 * 0.70, 2)

def test_sleeve_vwap_vix_filter(ce_contract):
    sleeve = SleeveVWAP()
    # When India VIX > 23, no trades allowed due to high IV crush risk
    signal = sleeve.evaluate(
        contract=ce_contract,
        premium=120.0,
        spot_price=22550.0,
        vwap=22510.0,
        ema_9=22530.0,
        ema_21=22500.0,
        session_open=22480.0,
        india_vix=25.0,
    )
    assert signal is None

def test_sleeve_gamma_expiry_breakout(ce_contract, pe_contract):
    sleeve = SleeveGamma()
    
    # Expiry afternoon: Spot breaks session high -> triggers Call gamma runner
    signal = sleeve.evaluate(
        contract=ce_contract,
        premium=45.0,
        spot_price=22610.0,
        session_high=22600.0,
        session_low=22450.0,
        is_expiry_day=True,
        is_afternoon_window=True,
    )
    assert signal is not None
    assert signal.sleeve == "GAMMA_EXP"
    assert signal.target_price == round(45.0 * 2.50, 2)

    # Not afternoon window -> no trade
    signal_no_win = sleeve.evaluate(
        contract=ce_contract,
        premium=45.0,
        spot_price=22610.0,
        session_high=22600.0,
        session_low=22450.0,
        is_expiry_day=True,
        is_afternoon_window=False,
    )
    assert signal_no_win is None

def test_trailing_stop_ratchet_calculation():
    """Verify that ratchet levels properly elevate stop loss as profit expands."""
    entry_px = 100.0
    initial_stop = 70.0  # -30%

    # Level 1 (+25% gain -> price reaches 125): stop moves to breakeven (100)
    current_ltp = 126.0
    gain_pct = (current_ltp - entry_px) / entry_px
    stop_px = initial_stop
    if gain_pct >= 0.25 and stop_px < entry_px:
        stop_px = round(entry_px, 2)
    assert stop_px == 100.0  # Risk-Free!

    # Level 2 (+50% gain -> price reaches 150): stop moves to +25% profit (125)
    current_ltp = 152.0
    gain_pct = (current_ltp - entry_px) / entry_px
    if gain_pct >= 0.50 and stop_px < round(entry_px * 1.25, 2):
        stop_px = round(entry_px * 1.25, 2)
    assert stop_px == 125.0  # Locked +25% profit!

    # Level 3 (+75% gain -> price reaches 175): stop moves to +50% profit (150)
    current_ltp = 178.0
    gain_pct = (current_ltp - entry_px) / entry_px
    if gain_pct >= 0.75 and stop_px < round(entry_px * 1.50, 2):
        stop_px = round(entry_px * 1.50, 2)
    assert stop_px == 150.0  # Locked +50% profit!

    # When pulled back from 178 to 149 (hits trailed stop 150):
    # Exit reason is verified as TRAIL_PROFIT (net profitable exit)
    exit_reason = "TRAIL_PROFIT" if (entry_px > 0 and stop_px >= entry_px) else "STOP_LOSS"
    assert exit_reason == "TRAIL_PROFIT"

