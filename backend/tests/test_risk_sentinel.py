"""
Tests for Risk Sentinel & Forced Breach Protection
Validates that every single risk rule violation is blocked,
the drawdown ladder operates correctly, naked option selling is prohibited,
and breaches force an immediate halt.
"""

import pytest
from datetime import datetime, timezone, timedelta
from backend.app.risk.sentinel import RiskSentinel, RiskConfig, RiskBreachException
from backend.app.clients.megabull import PAPER_MODE_ONLY

def test_paper_guard_enabled():
    assert PAPER_MODE_ONLY is True, "PAPER_MODE_ONLY must be hard-coded to True!"

def test_naked_option_prohibition():
    """Rule 7: No naked option selling."""
    sentinel = RiskSentinel()

    # Selling naked CE without hedge leg must raise RiskBreachException
    with pytest.raises(RiskBreachException) as exc:
        sentinel.validate_order(
            sleeve="O_SPREAD",
            side="SELL",
            instrument_type="CE",
            quantity=65,
            lot_size=65,
            price=150.0,
            risk_inr=2000.0,
            current_open_risk=0.0,
            is_hedged=False,  # Unhedged!
        )
    assert "NAKED_OPTION_PROHIBITED" in str(exc.value)

    # Hedged option sell must pass
    passed = sentinel.validate_order(
        sleeve="O_SPREAD",
        side="SELL",
        instrument_type="CE",
        quantity=65,
        lot_size=65,
        price=150.0,
        risk_inr=2000.0,
        current_open_risk=0.0,
        is_hedged=True,  # Hedged!
    )
    assert passed is True

def test_per_trade_risk_breach():
    """Rule 5: Per-trade risk <= 1% of capital (Rs 5,000 on Rs 5L)."""
    sentinel = RiskSentinel(RiskConfig(initial_capital=500000.0, max_trade_risk_pct=0.01))

    # Risk of Rs 6,000 > Rs 5,000 limit -> must fail
    with pytest.raises(RiskBreachException) as exc:
        sentinel.validate_order(
            sleeve="F",
            side="BUY",
            instrument_type="FUT",
            quantity=65,
            lot_size=65,
            price=24500.0,
            risk_inr=6000.0,  # Exceeds 1%
            current_open_risk=0.0,
        )
    assert "PER_TRADE_RISK_BREACH" in str(exc.value)

def test_total_open_risk_breach():
    """Rule 5: Total open risk <= 3% of capital (Rs 15,000 on Rs 5L)."""
    sentinel = RiskSentinel(RiskConfig(initial_capital=500000.0, max_total_risk_pct=0.03))

    # Open risk Rs 12,000 + new risk Rs 4,000 = Rs 16,000 > Rs 15,000 limit -> must fail
    with pytest.raises(RiskBreachException) as exc:
        sentinel.validate_order(
            sleeve="F",
            side="BUY",
            instrument_type="FUT",
            quantity=65,
            lot_size=65,
            price=24500.0,
            risk_inr=4000.0,
            current_open_risk=12000.0,
        )
    assert "TOTAL_RISK_BREACH" in str(exc.value)

def test_daily_loss_limit_forces_halt():
    """Daily loss limit 2.5% (Rs 12,500 on Rs 5L) -> flatten and halt."""
    sentinel = RiskSentinel(RiskConfig(initial_capital=500000.0, daily_loss_limit_pct=0.025))

    # Update equity with day loss Rs -13,000
    sentinel.update_equity(current_equity=487000.0, day_pnl=-13000.0, week_pnl=-13000.0)

    assert sentinel.is_halted is True
    assert sentinel.kill_switch_active is True
    assert "Daily loss breach" in sentinel.halt_reason

    # Subsequent orders must be rejected
    with pytest.raises(RiskBreachException) as exc:
        sentinel.validate_order(
            sleeve="F", side="BUY", instrument_type="FUT", quantity=65, lot_size=65,
            price=24500.0, risk_inr=2000.0, current_open_risk=0.0,
        )
    assert "SENTINEL_HALTED" in str(exc.value)

def test_drawdown_ladder():
    """
    Drawdown ladder:
    -6% -> halve size
    -10% -> disable option buying sleeve
    -15% -> full halt
    """
    sentinel = RiskSentinel(RiskConfig(initial_capital=500000.0))

    # Step 1: Drawdown -6.5% (Equity 467,500 from peak 500,000)
    sentinel.update_equity(current_equity=467500.0, day_pnl=-5000.0, week_pnl=-20000.0)
    assert sentinel.get_sizing_multiplier() == 0.5, "Size multiplier must be 0.5 at -6% drawdown"

    # Step 2: Drawdown -10.5% (Equity 447,500)
    sentinel.update_equity(current_equity=447500.0, day_pnl=-5000.0, week_pnl=-25000.0)
    assert "O_BUY" in sentinel.disabled_sleeves, "O_BUY sleeve must be disabled at -10% drawdown"

    with pytest.raises(RiskBreachException) as exc:
        sentinel.validate_order(
            sleeve="O_BUY", side="BUY", instrument_type="CE", quantity=65, lot_size=65,
            price=100.0, risk_inr=1500.0, current_open_risk=0.0,
        )
    assert "SLEEVE_DISABLED" in str(exc.value)

    # Step 3: Drawdown -15.2% (Equity 424,000) -> Full Halt!
    sentinel.update_equity(current_equity=424000.0, day_pnl=-5000.0, week_pnl=-76000.0)
    assert sentinel.is_halted is True
    assert sentinel.get_sizing_multiplier() == 0.0

def test_quote_freshness_veto():
    """Quotes older than 5.0 seconds must be rejected."""
    sentinel = RiskSentinel()

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=7.0)
    with pytest.raises(RiskBreachException) as exc:
        sentinel.validate_order(
            sleeve="F", side="BUY", instrument_type="FUT", quantity=65, lot_size=65,
            price=24500.0, risk_inr=2000.0, current_open_risk=0.0,
            quote_timestamp_utc=stale_time,
        )
    assert "STALE_DATA_BREACH" in str(exc.value)

def test_premium_floor_breach():
    """Option premium below Rs 20 must be rejected."""
    sentinel = RiskSentinel()

    with pytest.raises(RiskBreachException) as exc:
        sentinel.validate_order(
            sleeve="O_BUY", side="BUY", instrument_type="CE", quantity=65, lot_size=65,
            price=12.50,  # Below Rs 20
            risk_inr=800.0, current_open_risk=0.0,
        )
    assert "PREMIUM_FLOOR_BREACH" in str(exc.value)
