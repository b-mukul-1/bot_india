"""
APEX-IN CSV Export Engine
Generates streaming CSV with UTF-8 BOM encoding for Excel compatibility.
Exports all entry snapshot, market data, exit snapshot, charges breakdown, and PnL fields.
"""

import csv
import io
import codecs
from typing import List, Generator
from backend.app.store.models import TradeRecord, TradeEventRecord

TRADE_CSV_COLUMNS = [
    "trade_id",
    "strategy_id",
    "sleeve",
    "signal_reason",
    "algo_version",
    "config_hash",
    "underlying",
    "instrument_type",
    "tradingsymbol",
    "instrument_token",
    "expiry",
    "strike",
    "lot_size",
    "lots",
    "quantity",
    "side",
    "decision_time_ist",
    "order_sent_time_ist",
    "fill_time_ist",
    "order_type",
    "limit_price",
    "entry_price",
    "ltp_at_decision",
    "bid",
    "bid_qty",
    "ask",
    "ask_qty",
    "spread_abs",
    "spread_pct",
    "mid",
    "slippage_vs_mid",
    "volume",
    "oi",
    "oi_change",
    "underlying_spot",
    "india_vix",
    "iv",
    "delta",
    "theta",
    "stop_price",
    "target_price",
    "risk_amount_inr",
    "margin_or_premium_used",
    "data_quality_flags",
    "spread_modeled",
    "conservative_fill_price_modeled",
    "exit_time_ist",
    "exit_price",
    "exit_reason",
    "exit_bid",
    "exit_ask",
    "exit_volume",
    "holding_seconds",
    "mae",
    "mfe",
    "conservative_exit_price_modeled",
    "brokerage",
    "stt",
    "exchange_txn",
    "sebi_fee",
    "stamp_duty",
    "ipft",
    "gst",
    "total_charges",
    "charges_as_pct_of_turnover",
    "gross_pnl",
    "net_pnl",
    "net_pnl_pct_of_capital",
    "r_multiple",
    "conservative_net_pnl_modeled",
]

TRADE_EVENT_CSV_COLUMNS = [
    "id",
    "trade_id",
    "order_id",
    "event_type",
    "timestamp_ist",
    "message",
    "raw_json",
]

def format_val(val) -> str:
    """Formats value for CSV: empty string for None, string representation otherwise."""
    if val is None:
        return ""
    return str(val)

def export_trades_to_csv_bytes(trades: List[TradeRecord]) -> bytes:
    """
    Generates bytes with UTF-8 BOM followed by CSV rows.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")

    # Header
    writer.writerow(TRADE_CSV_COLUMNS)

    for t in trades:
        row = [format_val(getattr(t, col, "")) for col in TRADE_CSV_COLUMNS]
        writer.writerow(row)

    csv_text = output.getvalue()
    return codecs.BOM_UTF8 + csv_text.encode("utf-8")

def export_trade_events_to_csv_bytes(events: List[TradeEventRecord]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")

    writer.writerow(TRADE_EVENT_CSV_COLUMNS)
    for e in events:
        import json
        raw_str = json.dumps(e.raw) if e.raw else ""
        row = [
            format_val(e.id),
            format_val(e.trade_id),
            format_val(e.order_id),
            format_val(e.event_type),
            format_val(e.timestamp_ist),
            format_val(e.message),
            raw_str,
        ]
        writer.writerow(row)

    csv_text = output.getvalue()
    return codecs.BOM_UTF8 + csv_text.encode("utf-8")
