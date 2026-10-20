"""
APEX-IN FastAPI Backend
REST API & CSV Streaming for Nifty/Sensex Paper Trading Bot.
Enforces hard PAPER_MODE_ONLY guard.
"""

from fastapi import FastAPI, Depends, HTTPException, Header, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal

from backend.app.config import get_settings, Settings
from backend.app.clients.megabull import MegaBullClient, PAPER_MODE_ONLY
from backend.app.clients.marketdata import MegaBullOnlyProvider
from backend.app.instruments import InstrumentResolver
from backend.app.calendar import MarketCalendar
from backend.app.charges.engine import ChargesEngine
from backend.app.risk.sentinel import RiskSentinel
from backend.app.risk.kill_switch import KillSwitch
from backend.app.store.db import DatabaseManager
from backend.app.store.models import TradeRecord
from backend.app.export.csv_export import export_trades_to_csv_bytes, export_trade_events_to_csv_bytes
from backend.app.execution.order_manager import OrderManager

import os
import threading
import time
import logging
import httpx
from contextlib import asynccontextmanager
from backend.app.worker import TradingWorker

logger = logging.getLogger("apex_api")
settings = get_settings()

worker_instance = None
worker_thread = None

def _self_ping_loop(target_url: str):
    logger.info(f"[KEEP-ALIVE] Started self-ping keepalive targeting {target_url} every 5 minutes")
    while True:
        time.sleep(300)  # 5 minutes
        try:
            with httpx.Client(timeout=10.0) as client:
                client.get(f"{target_url.rstrip('/')}/ping")
        except Exception as e:
            logger.warning(f"[KEEP-ALIVE] Keepalive ping failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_instance, worker_thread
    # 1. Run trading worker inside background daemon thread
    run_worker = os.environ.get("RUN_WORKER_THREAD", "true").lower() in ("true", "1")
    if run_worker:
        worker_instance = TradingWorker()
        worker_thread = threading.Thread(target=worker_instance.run, daemon=True, name="TradingWorkerThread")
        worker_thread.start()
        logger.info("[LIFESPAN] Autonomous TradingWorker started in background daemon thread")

    # 2. Self-ping keepalive to prevent Render free instance spin-down
    ping_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("SELF_PING_URL") or "https://apex-in-backend.onrender.com"
    if ping_url:
        ping_thread = threading.Thread(target=_self_ping_loop, args=(ping_url,), daemon=True, name="KeepAliveThread")
        ping_thread.start()

    yield

    if worker_instance:
        worker_instance.running = False

app = FastAPI(
    title="APEX-IN F&O Paper Trading Engine",
    version="1.0.0",
    description="Nifty / Sensex F&O Paper Trading Bot on MegaBull simulator",
    lifespan=lifespan,
)

# CORS Middleware locked to DASHBOARD_ORIGIN
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.DASHBOARD_ORIGIN, "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Component Singletons
calendar = MarketCalendar()
db_manager = DatabaseManager(settings.DATABASE_URL)
db_manager.init_tables()
charges_engine = ChargesEngine()
megabull_client = MegaBullClient(api_key=settings.MEGABULL_API_KEY)
market_data_provider = MegaBullOnlyProvider(megabull_client)
sentinel = RiskSentinel()
kill_switch = KillSwitch(megabull_client, sentinel, db_manager)
order_manager = OrderManager(megabull_client, sentinel, db_manager, charges_engine, calendar)

# Resolver - loads local cache if present
resolver = InstrumentResolver()
try:
    resolver.load_from_file("backend/data/sample_instruments.csv")
except Exception:
    pass

def verify_auth(x_shared_secret: Optional[str] = Header(None)):
    if x_shared_secret != settings.API_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid X-Shared-Secret")

# ----------------- Health, Ping & Status Endpoints -----------------

@app.get("/ping")
def ping():
    return {
        "status": "pong",
        "time": datetime.now(timezone.utc).isoformat(),
        "worker_running": worker_instance.running if worker_instance else False,
    }

@app.get("/health")
def health_check():
    now_utc = datetime.now(timezone.utc)
    market_state = calendar.get_market_state(now_utc)
    return {
        "status": "healthy",
        "paper_mode_only": PAPER_MODE_ONLY,
        "utc_time": now_utc.isoformat(),
        "ist_time": calendar.to_ist(now_utc).isoformat(),
        "market_state": market_state,
        "sentinel_halted": sentinel.is_halted,
    }

@app.get("/api/status")
def get_status():
    now_utc = datetime.now(timezone.utc)
    trades = db_manager.list_trades()

    # Aggregate today's metrics (only valid trades)
    today_ist = calendar.to_ist(now_utc).date().isoformat()
    today_trades = [
        t for t in trades 
        if t.decision_time_ist and t.decision_time_ist.startswith(today_ist) 
        and (t.exit_price is not None or t.trade_id in order_manager.active_trades)
    ]

    gross_pnl_today = round(sum(float(t.gross_pnl or 0) for t in today_trades if t.exit_price is not None), 2)
    charges_today = round(sum(float(t.total_charges or 0) for t in today_trades if t.exit_price is not None), 2)
    net_pnl_today = round(gross_pnl_today - charges_today, 2)

    total_gross = sum(float(t.gross_pnl or 0) for t in trades if t.exit_price is not None)
    total_charges = sum(float(t.total_charges or 0) for t in trades if t.exit_price is not None)
    total_net = total_gross - total_charges

    current_equity = round(settings.INITIAL_CAPITAL + total_net, 2)
    peak = max(sentinel.peak_equity, settings.INITIAL_CAPITAL, current_equity)
    drawdown_pct = round((peak - current_equity) / peak * 100, 2) if peak > 0 else 0.0

    sentinel.current_equity = current_equity
    sentinel.peak_equity = peak
    sentinel.day_pnl = net_pnl_today

    valid_total_trades = [t for t in trades if t.exit_price is not None or t.trade_id in order_manager.active_trades]

    return {
        "initial_capital": settings.INITIAL_CAPITAL,
        "current_equity": current_equity,
        "peak_equity": peak,
        "drawdown_pct": drawdown_pct,
        "gross_pnl_today": gross_pnl_today,
        "charges_today": charges_today,
        "net_pnl_today": net_pnl_today,
        "trades_count_today": len(today_trades),
        "total_trades_count": len(valid_total_trades),
        "sentinel_halted": sentinel.is_halted,
        "halt_reason": sentinel.halt_reason,
        "kill_switch_active": sentinel.kill_switch_active,
        "paper_mode_only": PAPER_MODE_ONLY,
        "market_session": calendar.get_market_state(now_utc),
    }

# ----------------- Positions & Orders Endpoints -----------------

@app.get("/api/positions")
def get_positions():
    try:
        remote_positions = megabull_client.get_positions()
    except Exception as e:
        remote_positions = []

    active_local = [
        {
            "trade_id": t.trade_id,
            "underlying": t.underlying,
            "tradingsymbol": t.tradingsymbol,
            "side": t.side,
            "quantity": t.quantity,
            "entry_price": float(t.entry_price or 0),
            "decision_time_ist": t.decision_time_ist,
        }
        for t in order_manager.active_trades.values()
    ]

    return {
        "remote_positions": remote_positions,
        "active_trades": active_local,
    }

@app.get("/api/orders")
def get_orders():
    try:
        remote_orders = megabull_client.get_orders()
    except Exception:
        remote_orders = {"open": [], "executed": []}
    return remote_orders

# ----------------- Trades & Snapshots -----------------

@app.get("/api/trades")
def list_trades(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    underlying: Optional[str] = None,
    strategy: Optional[str] = None,
):
    records = db_manager.list_trades(
        from_date=from_date,
        to_date=to_date,
        underlying=underlying,
        strategy=strategy,
    )
    # Only return completed trades or currently active positions
    valid_records = [
        t for t in records 
        if t.exit_price is not None or t.trade_id in order_manager.active_trades
    ]
    return [
        {
            "trade_id": t.trade_id,
            "strategy_id": t.strategy_id,
            "sleeve": t.sleeve,
            "underlying": t.underlying,
            "instrument_type": t.instrument_type,
            "tradingsymbol": t.tradingsymbol,
            "side": t.side,
            "quantity": t.quantity,
            "entry_price": float(t.entry_price or 0) if t.entry_price else None,
            "exit_price": float(t.exit_price or 0) if t.exit_price else None,
            "decision_time_ist": t.decision_time_ist,
            "exit_time_ist": t.exit_time_ist,
            "gross_pnl": float(t.gross_pnl or 0) if t.gross_pnl is not None else None,
            "total_charges": float(t.total_charges or 0),
            "net_pnl": float(t.net_pnl or 0) if t.net_pnl is not None else None,
            "exit_reason": t.exit_reason,
            "data_quality_flags": t.data_quality_flags,
        }
        for t in valid_records
    ]

@app.get("/api/trades/{trade_id}")
def get_trade_detail(trade_id: str):
    t = db_manager.get_trade(trade_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")

    return {
        "trade_id": t.trade_id,
        "strategy_id": t.strategy_id,
        "sleeve": t.sleeve,
        "signal_reason": t.signal_reason,
        "underlying": t.underlying,
        "instrument_type": t.instrument_type,
        "tradingsymbol": t.tradingsymbol,
        "instrument_token": t.instrument_token,
        "lot_size": t.lot_size,
        "quantity": t.quantity,
        "side": t.side,
        "decision_time_ist": t.decision_time_ist,
        "order_sent_time_ist": t.order_sent_time_ist,
        "fill_time_ist": t.fill_time_ist,
        "entry_price": float(t.entry_price or 0) if t.entry_price else None,
        "exit_price": float(t.exit_price or 0) if t.exit_price else None,
        "exit_time_ist": t.exit_time_ist,
        "exit_reason": t.exit_reason,
        "bid": float(t.bid) if t.bid else None,
        "ask": float(t.ask) if t.ask else None,
        "volume": t.volume,
        "oi": t.oi,
        "spread_modeled": float(t.spread_modeled) if t.spread_modeled else None,
        "conservative_fill_price_modeled": float(t.conservative_fill_price_modeled) if t.conservative_fill_price_modeled else None,
        "charges": {
            "brokerage": float(t.brokerage or 0),
            "stt": float(t.stt or 0),
            "exchange_txn": float(t.exchange_txn or 0),
            "sebi_fee": float(t.sebi_fee or 0),
            "stamp_duty": float(t.stamp_duty or 0),
            "ipft": float(t.ipft or 0),
            "gst": float(t.gst or 0),
            "total_charges": float(t.total_charges or 0),
            "charges_as_pct_of_turnover": float(t.charges_as_pct_of_turnover or 0),
        },
        "pnl": {
            "gross_pnl": float(t.gross_pnl or 0) if t.gross_pnl is not None else None,
            "net_pnl": float(t.net_pnl or 0) if t.net_pnl is not None else None,
            "net_pnl_pct_of_capital": float(t.net_pnl_pct_of_capital or 0) if t.net_pnl_pct_of_capital else None,
        },
        "data_quality_flags": t.data_quality_flags,
    }

# ----------------- CSV Download Endpoints -----------------

@app.get("/api/trades.csv")
def download_trades_csv(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    underlying: Optional[str] = None,
    strategy: Optional[str] = None,
    auth: None = Depends(verify_auth),
):
    trades = db_manager.list_trades(
        from_date=from_date,
        to_date=to_date,
        underlying=underlying,
        strategy=strategy,
    )
    csv_bytes = export_trades_to_csv_bytes(trades)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=apex_trades_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )

# ----------------- Emergency Kill Switch -----------------

@app.post("/api/kill-switch")
def trigger_kill_switch(confirm: str = Query(..., description="Must type HALT to confirm"), auth: None = Depends(verify_auth)):
    if confirm.strip().upper() != "HALT":
        raise HTTPException(status_code=400, detail="Must pass confirm=HALT to execute kill switch")
    result = kill_switch.execute_halt_and_flatten(reason="DASHBOARD_API_TRIGGERED")
    if worker_instance and hasattr(worker_instance, "sentinel"):
        worker_instance.sentinel.trigger_halt("Kill switch activated: DASHBOARD_API_TRIGGERED")
    return {"status": "SUCCESS", "details": result}

@app.post("/api/kill-switch/reset")
def reset_kill_switch_endpoint(auth: None = Depends(verify_auth)):
    result = kill_switch.rearm()
    if worker_instance and hasattr(worker_instance, "sentinel"):
        worker_instance.sentinel.reset_halt()
    return {"status": "SUCCESS", "message": "Kill switch disarmed and bot re-armed", "details": result}

@app.post("/api/trades/cleanup-ghosts")
def cleanup_ghost_trades(auth: None = Depends(verify_auth)):
    with db_manager.session() as s:
        active_ids = list(order_manager.active_trades.keys())
        ghosts = s.query(TradeRecord).filter(TradeRecord.exit_price == None).all()
        to_delete = [g for g in ghosts if g.trade_id not in active_ids]
        count = len(to_delete)
        for g in to_delete:
            s.delete(g)
        return {"status": "SUCCESS", "deleted_ghost_trades": count}

# ----------------- Charges Breakdown -----------------

@app.get("/api/charges/summary")
def get_charges_summary():
    trades = db_manager.list_trades()
    totals = {
        "brokerage": sum(float(t.brokerage or 0) for t in trades),
        "stt": sum(float(t.stt or 0) for t in trades),
        "exchange_txn": sum(float(t.exchange_txn or 0) for t in trades),
        "sebi_fee": sum(float(t.sebi_fee or 0) for t in trades),
        "stamp_duty": sum(float(t.stamp_duty or 0) for t in trades),
        "ipft": sum(float(t.ipft or 0) for t in trades),
        "gst": sum(float(t.gst or 0) for t in trades),
        "total_charges": sum(float(t.total_charges or 0) for t in trades),
    }
    gross_pnl_total = sum(float(t.gross_pnl or 0) for t in trades)
    net_pnl_total = sum(float(t.net_pnl or 0) for t in trades)

    charges_as_pct_of_gross = round(totals["total_charges"] / gross_pnl_total * 100, 2) if gross_pnl_total > 0 else 0.0

    return {
        "totals": totals,
        "gross_pnl_total": gross_pnl_total,
        "net_pnl_total": net_pnl_total,
        "charges_as_pct_of_gross": charges_as_pct_of_gross,
        "total_trades": len(trades),
    }

# ----------------- Performance & Target Reporting -----------------

@app.get("/api/performance")
def get_performance_report():
    trades = db_manager.list_trades()
    closed_trades = [t for t in trades if t.net_pnl is not None]

    if not closed_trades:
        return {
            "total_trades": 0,
            "measured_day_avg_return_pct": 0.0,
            "owner_target_daily_return_pct": "20% - 30%",
            "target_gap_analysis": "No closed trades recorded yet to measure against the 20-30%/day aspirational target.",
            "conservative_net_pnl": 0.0,
            "ltp_net_pnl": 0.0,
        }

    net_pnls = [float(t.net_pnl) for t in closed_trades]
    wins = [p for p in net_pnls if p > 0]
    win_rate = round(len(wins) / len(net_pnls) * 100, 2)
    total_net = sum(net_pnls)

    return {
        "total_trades": len(closed_trades),
        "win_rate_pct": win_rate,
        "total_net_pnl": total_net,
        "owner_target_daily_return_pct": "20% - 30%",
        "measured_status": "Strictly measured; no synthetic values. Target treated as aspirational tail outcome only.",
    }
