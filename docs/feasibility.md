# Feasibility Analysis: Daily Return Targets vs Indian F&O Market Realities

Author: APEX-IN Architecture Engine  
Date: 2026-10-13  
Virtual Capital: Rs 5,00,000  
Target: 20% - 30% per day (Aspirational Owner Target)  

---

## 1. Executive Summary & Honest Verdict

> [!CAUTION]
> **Verdict: Unachievable as a sustained daily baseline; achievable only as an extreme right-tail outlier on rare directional expansion days.**  
> Attempting to target 20% to 30% daily return on a Rs 5,00,000 capital base requires risking 10% to 20% of equity per trade, which causes mathematical certainty of account ruin (100% drawdown) within 15-30 trading sessions.

---

## 2. The Compounding Math

- **At 20% daily return compounded:**  
  Rs 5,00,000 becomes **Rs 15.6 Crore in 20 sessions (1 month)** and **Rs 1,000+ Trillion in 1 year** (larger than global GDP).
- In real derivative markets, market liquidity and exchange freeze quantities cap maximum single-order capacity (e.g. Nifty freeze quantity = 1,800 contracts).

---

## 3. The Impact of Statutory Levies (The Friction Burden)

Under post-April 2026 Indian tax laws, transaction charges form an insurmountable hurdle for high-frequency or excessive trading:

| Friction Source | Rate / Impact | Cost on Rs 5L Capital Base |
|---|---|---|
| **STT on Futures (Sell)** | 0.05% of traded turnover | ~Rs 752 per round-trip lot |
| **STT on Options (Sell)** | 0.15% of premium | ~Rs 11 per round-trip lot |
| **Brokerage** | Rs 20 flat per executed leg | Rs 40 per round trip |
| **Exchange Txn Charges** | NSE: 0.00173% Fut / 0.035% Opt | ~Rs 52 on Fut / ~Rs 5 on Opt |
| **GST** | 18% on (Brokerage + Txn + SEBI) | ~Rs 18 per Fut / ~Rs 8 per Opt |
| **Stamp Duty** | 0.002% Fut / 0.003% Opt | ~Rs 30 on Fut / ~Rs 0.20 on Opt |

### Churn Scaling
- 10 futures round trips per day = **~Rs 9,000 in charges (~1.8% of capital lost daily to friction alone)**.
- 50 option round trips per day = **~Rs 3,200 in charges (~0.64% of capital lost daily)**.
- Over 20 trading days in a month, aggressive churning consumes **15% to 35% of total capital purely in statutory taxes and exchange fees** before factoring in bid-ask spread and slippage.

---

## 4. APEX-IN Protocol
1. **Never loosen risk limits** to chase the target. Risk remains strictly capped at 0.5% - 1.0% per trade (Rs 2,500 - 5,000).
2. **Never sell naked options.** Short options are strictly hedged defined-risk credit spreads with the long wing placed first.
3. **Report measured performance honestly.** All metrics report actual conservative fills vs the 20-30% target without obfuscation.
