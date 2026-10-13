"""
Tests for InstrumentResolver
Verifies dynamic resolution of Nifty and Sensex spot, futures, and option contracts.
"""

import pytest
import os
from backend.app.instruments import InstrumentResolver

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_instruments.csv")

@pytest.fixture
def resolver():
    assert os.path.exists(CSV_PATH), f"Sample CSV missing at {CSV_PATH}"
    return InstrumentResolver(csv_path=CSV_PATH)

def test_resolve_indices(resolver):
    nifty = resolver.get_spot("NIFTY")
    assert nifty is not None
    assert nifty.instrument_token == "256265"
    assert nifty.exchange == "NSE"
    assert nifty.lot_size == 65

    sensex = resolver.get_spot("SENSEX")
    assert sensex is not None
    assert sensex.instrument_token == "265"
    assert sensex.exchange == "BSE"
    assert sensex.lot_size == 10

    vix = resolver.get_spot("INDIA VIX")
    assert vix is not None
    assert vix.instrument_token == "264969"

def test_resolve_futures(resolver):
    nifty_futs = resolver.get_futures("NIFTY")
    assert len(nifty_futs) >= 1
    fut = nifty_futs[0]
    assert fut.instrument_type == "FUT"
    assert fut.underlying == "NIFTY"
    assert fut.lot_size == 65

    sensex_futs = resolver.get_futures("SENSEX")
    assert len(sensex_futs) >= 1
    sfut = sensex_futs[0]
    assert sfut.instrument_type == "FUT"
    assert sfut.underlying == "SENSEX"
    assert sfut.exchange == "BSE"
    assert sfut.lot_size == 10

def test_resolve_options_and_atm(resolver):
    nifty_opts = resolver.get_options("NIFTY")
    assert len(nifty_opts) > 500

    # Test ATM options resolution around spot 24,750
    atm = resolver.get_atm_options("NIFTY", spot_price=24750.0, n_strikes=5)
    assert len(atm["CE"]) > 0
    assert len(atm["PE"]) > 0

    ce_strikes = [o.strike for o in atm["CE"]]
    # Should include 24750 or closest strikes
    assert any(abs(s - 24750) <= 100 for s in ce_strikes)
