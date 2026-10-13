# APEX-IN Data Manifest & Source Catalog

Specification Date: 2026-10-13  
Target Forward-Test Window: >= 60 Live Market Sessions  
Storage Engine: PostgreSQL / SQLite (Local Test) + CSV Snapshots  

---

## 1. Primary Market Data Sources

### 1.1 MegaBull Simulator (`https://api.megabull.in`)
- **Type:** Forward-test paper execution and simulated market feed.
- **Polling Frequency:** 2.0 seconds during active session (09:15 to 15:30 IST).
- **Available Fields:** Last Traded Price (`ltp`), `tradingSymbol`, `instrumentName`, `instrumentToken`, virtual equity, executed order fills.
- **Unavailable Fields:** `bid`, `bid_qty`, `ask`, `ask_qty`, `volume`, `open_interest` (OI), `implied_volatility` (IV).
- **Data Gap Handling:** All unavailable fields are strictly stored as `NULL` in the database and exported as empty string `""` in CSV. Never fabricate synthetic bids or volumes. Column `data_quality_flags` is marked `"MISSING_DEPTH_AND_VOLUME"`.

### 1.2 NSE / BSE Historical Bhavcopy (EOD)
- **Source:** Official NSE & BSE daily derivatives reports (`https://www.nseindia.com/all-reports`).
- **Frequency:** Daily at 18:00 IST post-market.
- **Use:** Settlement verification, strike open interest distribution, PCR (Put-Call Ratio), and end-of-day baseline calibration.

### 1.3 Pluggable Broker Market Depth (Secondary Feed)
- **Candidate Adapters:** Angel One SmartAPI (Free WebSocket Depth 5 / 20) / DhanHQ v2.
- **Status:** Architecture implemented in `backend/app/clients/marketdata.py`. Active feed pending owner credential configuration.

---

## 2. Market Data Schema & Snapshots

Every tick and trade snapshot is recorded with:
- **Decision Timestamp:** UTC ISO 8601 stored, IST ISO 8601 displayed.
- **Underlying:** `NIFTY` (NSE), `SENSEX` (BSE), `INDIA VIX` (NSE).
- **Contract Type:** `INDEX`, `FUT`, `CE`, `PE`.
- **Modeled Spread (`spread_modeled`):** Dedicated column estimating conservative bid-ask friction (0.75% for ATM options, 1.0 point for Nifty futures, 3.0 points for Sensex futures).
- **Conservative Fill (`conservative_fill_price_modeled`):** Used as the headline P&L metric to prevent LTP fill optimism.

---

## 3. Session Recording Log

| Session ID | Date (IST) | Market Regime | VIX Range | Quotes Logged | Trades Executed | Status |
|---|---|---|---|---|---|---|
| SESS-20261013-01 | 2026-10-13 | Sideways | 13.2 - 13.6 | Baseline Setup | 0 | Ready |
