# SEBI Retail-Algo Framework Compliance & Going Live Checklist

Document Date: 2026-10-13  
Regulatory Context: SEBI Mandates for Retail Algorithmic Trading (Effective 1 April 2026)  
Current Status: **PAPER TRADING ONLY ON MEGABULL (HARD-GUARDED)**  

---

> [!WARNING]
> APEX-IN is currently locked to `PAPER_MODE_ONLY = True`. Real money trading cannot and must not be enabled until the owner explicitly signs off, all acceptance gates are met (>= 60 sessions live forward test), and the full checklist below is satisfied.

---

## 1. Regulatory Requirements (SEBI Framework Post-April 2026)

Under SEBI circulars and exchange guidelines for retail algorithmic trading:

1. **Broker-Approved Routing:**
   - Orders must route through a SEBI-registered broker's official open API (e.g., Zerodha Kite Connect, Angel One SmartAPI, DhanHQ, Upstox).
   - Direct-to-exchange DMA (Direct Market Access) is restricted to institutional members.
2. **Strategy / Algo ID Tagging:**
   - Every order sent via API must carry a registered Strategy/Algo ID approved by the broker/exchange.
3. **Static IP Whitelisting & 2FA:**
   - The server hosting the execution engine must possess a whitelisted static IP registered with the broker.
   - Initial daily login must satisfy mandatory Two-Factor Authentication (TOTP / Biometric).
4. **Broker Kill Switch:**
   - The broker's web terminal and API must support an emergency kill switch that halts all algorithmic order flows and flattens open positions within seconds.
5. **Rate Limits & Order Throttle:**
   - Retail algorithmic flow must remain strictly below 10 orders/second per segment per exchange.
   - APEX-IN enforces a maximum rate of 2 orders/second and a cap of 40 orders per day.
6. **Domestic Hosting:**
   - Trading algorithms interacting with Indian exchange APIs must be hosted on servers located within India (e.g. AWS ap-south-1 Mumbai, GCP asia-south1, or Indian VPS provider).
7. **Daily Session Invalidation:**
   - Broker API auth tokens expire daily at session close. Automated daily re-authentication protocols must be established.

---

## 2. Technical & Capital Prerequisites

- [ ] **Acceptance Gate Passed:** At least 60 forward-test sessions on MegaBull simulator completed with positive Deflated Sharpe and net expectancy after conservative modeled fills.
- [ ] **Conservative Fill Survival:** Verified that strategies maintain positive edge when fills are modeled at full ask (buys) and full bid (sells) plus slippage.
- [ ] **Cost Buffer Verified:** P&L remains positive at 2x statutory charges and slippage.
- [ ] **Trade-Only API Credentials:** API keys configured with trading permissions only (zero fund transfer/withdrawal access).
- [ ] **Initial Sizing:** Commencing with strictly **1 lot** on all sleeves.
- [ ] **Explicit Owner Sign-Off:** Written authorization from the owner to unlock live trading.
