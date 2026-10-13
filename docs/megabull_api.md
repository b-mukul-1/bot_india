# MegaBull API Specification & Observed Schemas

Documented on: 2026-10-13  
Spec Source: `https://megabull.in/api/megabull-openapi.json`  
Base URL: `https://api.megabull.in`  
Auth: Header `api-key: <KEY>` on every request.  

---

## 1. Authentication & Security
- **Header:** `api-key: <KEY>`
- **Key Expiry:** Keys are generated at `trade.megabull.in` -> Profile and expire after **1 month**.
- **Error Behavior:**
  - Missing header: HTTP 401 `{"path": "/...", "error": "AuthenticationException", "message": ["Missing api-key header"], "status": "UNAUTHORIZED"}`
  - Invalid / Expired key: HTTP 401 `{"path": "/...", "error": "AuthenticationException", "message": ["Invalid or expired API key"], "status": "UNAUTHORIZED"}`
  - The client must detect HTTP 401 / 403, immediately halt paper trading, set the risk sentinel kill switch, and trigger an alert to the owner.

---

## 2. Request & Response Schemas

### 2.1 Error Response (`ApiErrorResponse`)
Returned on 4xx/5xx:
```json
{
  "status": "UNAUTHORIZED",
  "error": "AuthenticationException",
  "message": [
    "Invalid or expired API key"
  ],
  "path": "/api/marketwatch/instruments"
}
```
Fields:
- `status`: String (e.g. `"BAD_REQUEST"`, `"UNAUTHORIZED"`, `"NOT_FOUND"`)
- `error`: String (e.g. `"AuthenticationException"`, `"ErrorMsgException"`)
- `message`: Array of Strings (Human-readable error messages)
- `path`: String (Request URI)

---

### 2.2 Order Placement (`POST /api/order/buysell`)
**Request Body (`OrderRequest`):**
```json
{
  "instrumentToken": "256265",
  "qty": 65,
  "type": "BUY",
  "duration": "MIS",
  "orderType": "LIMIT",
  "price": 25000.0,
  "triggerPrice": 24800.0
}
```
Field Specifications:
- `instrumentToken` (string, required): Instrument token resolved from instruments CSV.
- `qty` (int32, required): Quantity to trade (must be a valid multiple of contract `lotSize`).
- `type` (string, required, enum): `"BUY" | "SELL"`
- `duration` (string, required, enum): `"MIS"` (intraday) or `"CNC"` (delivery). APEX-IN uses `"MIS"`.
- `orderType` (string, required, enum): `"LIMIT" | "MKT" | "SL"`.
- `price` (double, optional): Limit price. **Required when `orderType` is `LIMIT`**.
- `triggerPrice` (double, optional): Trigger price. **Required when `orderType` is `SL`**.
*CRITICAL:* Do **NOT** send `id` in the request body.

**Response Body (`OrderResponse`):**
```json
{
  "id": 1049281,
  "instrumentToken": "256265",
  "instrumentName": "NIFTY 50",
  "executionType": "REGULAR",
  "qty": 65,
  "lotSize": 65,
  "type": "BUY",
  "duration": "MIS",
  "orderType": "LIMIT",
  "price": 25000.0,
  "status": "EXECUTED",
  "msg": "Order placed successfully",
  "createdTimestamp": "2026-10-13T10:15:00.000Z",
  "modifiedTimestamp": "2026-10-13T10:15:00.000Z"
}
```

---

### 2.3 Modify Order (`PUT /api/order/buysell/{orderId}`)
- Path parameter: `orderId` (int)
- Request Body: `OrderRequest` (same as place order, with updated price/qty/orderType)
- Response: `OrderResponse`

---

### 2.4 Bulk Cancel Orders (`PUT /api/order/bulk/cancel`)
- Query parameter: `roomId` (optional int)
- Request Body: Array of integers `[orderId1, orderId2, ...]`
- Response Body: Array of `OrderCancelResponse`
```json
[
  {
    "id": 1049281,
    "status": "CANCELLED",
    "instrumentName": "NIFTY 25 AUG FUT",
    "msg": "Order cancelled successfully"
  }
]
```

---

### 2.5 User Profile (`GET /api/user/my`)
Response Body (`UserResponse`):
```json
{
  "firstName": "Mukul",
  "lastName": "Bhardwaj",
  "phoneNumber": "9876543210",
  "emailId": "user@example.com",
  "virtualMoney": 500000.0,
  "virtualMoneyBlocked": 0.0,
  "virtualMoneyLeft": 500000,
  "brokerage": 20,
  "partner": 0,
  "notificationCount": 0,
  "premiumType": "PRO",
  "premiumExpiry": "2026-12-31T23:59:59.000Z"
}
```

---

### 2.6 Instruments CSV (`GET /api/marketwatch/instruments`)
- Parameter: `redirect=true` (boolean). When `true`, responds with HTTP 302 redirect to S3 instead of JSON.
- Default JSON response (`InstrumentDownloadResponse`):
```json
{
  "downloadUrl": "https://megabull-open.s3.us-east-1.amazonaws.com/Instrument-dev.csv"
}
```
- CSV Format: 3 columns with header:
  `"tradingSymbol","instrumentName","instrumentToken"`
- Examples:
  - `"NIFTY 50","NIFTY 50","256265"`
  - `"SENSEX","SENSEX","265"`
  - `"INDIA VIX","INDIA VIX","264969"`
  - `"NIFTY26AUGFUT","NIFTY 25 AUG  FUT","14866434"`
  - `"SENSEX26AUGFUT","SENSEX 27 AUG  FUT","211359237"`
  - `"NIFTY2680424750CE","NIFTY 04 AUG 24750 CE","16868098"`
  - `"SENSEX2680678600PE","SENSEX 06 AUG 78600 PE","215080453"`

---

### 2.7 Last Traded Price (`GET /api/marketwatch/ltp/{instrumentToken}`)
Response Body (`LtpResponse`):
```json
{
  "instrumentToken": "256265",
  "displayName": "NIFTY 50",
  "exchange": "NSE",
  "ltp": 25120.45
}
```

---

### 2.8 Open Positions (`GET /api/position/my`)
Response Body: Array of `PositionResponse`:
```json
[
  {
    "instrumentToken": "14866434",
    "instrumentName": "NIFTY 25 AUG FUT",
    "duration": "MIS",
    "qty": 65,
    "lotSize": 65,
    "type": "BUY",
    "priceAvg": 25100.0,
    "pl": 1329.25,
    "avgBuyPrice": 25100.0,
    "avgSellPrice": 0.0
  }
]
```

---

### 2.9 Order Collection (`GET /api/order/my`)
Response Body (`OrderCollectionResponse`):
```json
{
  "open": [
    {
      "id": 1049281,
      "instrumentToken": "256265",
      "status": "OPEN",
      "qty": 65,
      "price": 25000.0
    }
  ],
  "executed": [
    {
      "id": 1049280,
      "instrumentToken": "14866434",
      "status": "EXECUTED",
      "qty": 65,
      "price": 25100.0
    }
  ]
}
```

---

## 3. Data Gap Analysis & Resolution

### 3.1 The Gap
A comprehensive inspection of the MegaBull OpenAPI specification confirms:
- **Available:** Last Traded Price (`ltp`), `tradingSymbol`, `instrumentName`, `instrumentToken`, position summary (`avgBuyPrice`, `avgSellPrice`, `pl`, `qty`).
- **Unavailable / Missing in MegaBull:** `bid`, `bid_qty`, `ask`, `ask_qty`, `depth`, `volume`, `open_interest` (OI), `oi_change`, `iv`, `greeks`.

### 3.2 Evaluation of Free External Feeds
1. **Angel One SmartAPI:**
   - Free of cost, zero subscription fee.
   - Real-time Depth 5 and Depth 20 via WebSocket 2.0.
   - REST Quote API rate limit: 1 req/sec (up to 50 symbols).
2. **DhanHQ API (v2):**
   - Free of cost for active traders, zero AMC / API fee.
   - WebSocket depth feeds: 5-depth, 20-depth, up to 50 instruments per connection.
   - REST Quote API: 1 req/sec (up to 1,000 instruments batched).
3. **Zerodha Kite Connect:**
   - Paid: Rs 2,000/month for trade/quote API + Rs 2,000/month for historical API.
4. **NSE Scraping:**
   - Strictly forbidden (violates Terms of Service, anti-bot IP blocks).

### 3.3 APEX-IN Resolution & Protocol
Per Section 0, 1.2, and 6 of the APEX-IN specification:
1. **Never fabricate or invent numbers:** If no external feed credentials are provided, `bid`, `bid_qty`, `ask`, `ask_qty`, `volume`, and `oi` are stored strictly as `NULL` in the trade snapshot with `data_quality_flags="MISSING_DEPTH_AND_VOLUME"`.
2. **Conservative Modeled Spread:** For backtesting and conservative paper fill analysis, an explicit modeled spread is calculated and stored exclusively in dedicated columns:
   - `spread_modeled`: ATM options modeled at 0.5% - 1.0% of premium; Futures modeled at 1-2 index ticks.
   - `conservative_fill_price_modeled`: Entry fill assumed at `ltp + spread_modeled / 2` (buys) or `ltp - spread_modeled / 2` (sells).
   - `conservative_net_pnl_modeled`: Headline P&L computed using conservative fills.
3. **Secondary Market Data Adapter (`MarketDataProvider`):**
   - A modular `MarketDataProvider` interface is built in `backend/app/clients/marketdata.py`.
   - Pluggable adapters: `MegaBullOnlyProvider` (LTP only), `AngelSmartApiProvider`, and `DhanMarketDataProvider`.
   - When the owner provides credentials for Angel One or Dhan, depth, volume, and OI are merged automatically.
