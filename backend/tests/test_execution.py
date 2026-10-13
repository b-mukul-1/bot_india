"""
Tests for Strategy Combiner, Cost Gate, Order Manager, and Reconciliation
"""

import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from backend.app.charges.engine import ChargesEngine
from backend.app.strategies.combiner import StrategyCombiner
from backend.app.strategies.sleeve_f import StrategySignal
from backend.app.risk.sentinel import RiskSentinel
from backend.app.store.db import DatabaseManager
from backend.app.calendar import MarketCalendar
from backend.app.execution.order_manager import OrderManager

@pytest.fixture
def charges_engine():
    return ChargesEngine()

@pytest.fixture
def combiner(charges_engine):
    return StrategyCombiner(charges_engine)

def test_cost_aware_gate_rejection(combiner):
    """Signals where expected move is smaller than 2x total charges + spread friction must be rejected."""
    # Option trade with tiny expected move of Rs 40 (while round-trip charges alone are ~Rs 64 + spread)
    low_edge_signal = StrategySignal(
        strategy_id="O_BUY",
        sleeve="O_BUY",
        underlying="NIFTY",
        instrument_token="16868098",
        tradingsymbol="NIFTY2680424750CE",
        instrument_type="CE",
        side="BUY",
        quantity=65,
        price=100.0,
        stop_price=95.0,
        target_price=100.60, # Expected move is only 0.60 * 65 = Rs 39
        signal_reason="TEST_LOW_EDGE",
        risk_inr=325.0,
        expected_move=39.0,
    )
    assert combiner.cost_aware_gate(low_edge_signal, modeled_spread=0.80) is False

    # High edge signal with expected move of Rs 650 (target 110 from 100)
    high_edge_signal = StrategySignal(
        strategy_id="O_BUY",
        sleeve="O_BUY",
        underlying="NIFTY",
        instrument_token="16868098",
        tradingsymbol="NIFTY2680424750CE",
        instrument_type="CE",
        side="BUY",
        quantity=65,
        price=100.0,
        stop_price=70.0,
        target_price=110.0,
        signal_reason="TEST_HIGH_EDGE",
        risk_inr=1950.0,
        expected_move=650.0,
    )
    assert combiner.cost_aware_gate(high_edge_signal, modeled_spread=0.80) is True

def test_signal_netting(combiner):
    """Opposing orders for the exact same contract must be neutralized to 0 net."""
    sig1 = StrategySignal(
        strategy_id="SLEEVE_F",
        sleeve="F",
        underlying="NIFTY",
        instrument_token="14866434",
        tradingsymbol="NIFTY26AUGFUT",
        instrument_type="FUT",
        side="BUY",
        quantity=65,
        price=24500.0,
        stop_price=24400.0,
        target_price=24800.0,
        signal_reason="LONG_FUT",
        risk_inr=6500.0,
        expected_move=300.0,
    )
    sig2 = StrategySignal(
        strategy_id="SLEEVE_O_SPREAD",
        sleeve="O_SPREAD",
        underlying="NIFTY",
        instrument_token="14866434",
        tradingsymbol="NIFTY26AUGFUT",
        instrument_type="FUT",
        side="SELL",
        quantity=65,
        price=24500.0,
        stop_price=24600.0,
        target_price=24200.0,
        signal_reason="SHORT_FUT",
        risk_inr=6500.0,
        expected_move=300.0,
    )

    netted = combiner.net_signals([sig1, sig2])
    assert len(netted) == 0, "Opposing signals should cancel out completely to 0."

def test_reconciliation_mismatch_forces_halt(tmp_path):
    """Unknown remote position on MegaBull must immediately halt the sentinel."""
    db_file = tmp_path / "recon_test.db"
    db = DatabaseManager(f"sqlite:///{db_file}")
    db.init_tables()
    sentinel = RiskSentinel()
    calendar = MarketCalendar()
    charges = ChargesEngine()

    mock_client = MagicMock()
    # Remote MegaBull reports 1 open position for token 99999
    mock_client.get_positions.return_value = [
        {"instrumentToken": "99999", "qty": 65, "instrumentName": "UNKNOWN_POS"}
    ]

    order_mgr = OrderManager(
        client=mock_client,
        sentinel=sentinel,
        db=db,
        charges_engine=charges,
        calendar=calendar,
    )

    # Local active trades is empty!
    success = order_mgr.reconcile_positions()
    assert success is False
    assert sentinel.is_halted is True
    assert "RECONCILIATION_MISMATCH" in sentinel.halt_reason
