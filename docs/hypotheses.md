# APEX-IN Strategy Hypotheses & Pre-Registration

Pre-registration Date: 2026-10-13  
Target Capital: Rs 5,00,000 (MegaBull Virtual Balance)  
Sleeves: F (Futures Trend), O-Buy (Convex Options), O-Spread (Defined-Risk Credit Spreads)  

---

## 1. Sleeve F: Index Futures Trend & Opening Range Breakout (ORB)

### 1.1 Hypothesis
Intraday index futures exhibit persistent directional momentum following the initial 15-minute opening range (09:15-09:30 IST) when confirmed by EMA trend alignment (20 EMA > 50 EMA) and ADX > 20. Trailing stops based on 2x ATR protect capital while allowing asymmetric winners.

### 1.2 Execution Rules
- **Instruments:** NIFTY and SENSEX near-month futures.
- **Entry Window:** 09:30 to 14:30 IST.
- **Long Signal:** Price breaks above 15-min high AND Spot > 20 EMA > 50 EMA AND ADX > 20.
- **Short Signal:** Price breaks below 15-min low AND Spot < 20 EMA < 50 EMA AND ADX > 20.
- **Position Sizing:** Fixed risk per trade <= 0.5% - 1.0% of virtual equity (Rs 2,500 - 5,000). Max 1-2 lots.
- **Stop Loss:** 1.5x ATR from entry.
- **Take Profit / Trailing:** Trailing ATR stop; intraday square-off strictly at 15:15 IST.
- **Cost-Aware Gate:** Expected profit target must exceed 2x (estimated round-trip charges + 2.0 pts spread).

---

## 2. Sleeve O-Buy: Convex Option Buying (Momentum & Vol Expansion)

### 2.1 Hypothesis
Sudden intraday momentum expansions generate explosive directional moves in ATM / 1-strike OTM index options. By capping risk strictly to the premium paid (100% defined loss), long calls or puts capture high positive skewness (right-tail payoffs).

### 2.2 Execution Rules
- **Instruments:** NIFTY ATM or ATM +/- 1 strike Call (CE) or Put (PE).
- **Entry Filter:** India VIX < 22 (avoid excessive IV crush) and IV Percentile < 70%.
- **Long CE Signal:** Underlying spot breaks 20-period Donchian high with positive volume expansion.
- **Long PE Signal:** Underlying spot breaks 20-period Donchian low with positive volume expansion.
- **Risk Budget:** Max premium deployed per trade <= Rs 3,000 - 5,000 (<= 1% equity).
- **Hard Stop:** 35% loss of option entry premium.
- **Trailing Target:** Trail at 1.5x entry risk once trade moves +1R in profit. Intraday exit by 15:15 IST.

---

## 3. Sleeve O-Spread: Defined-Risk Vertical Credit Spreads

### 3.1 Hypothesis
In low-trend, high-IV environments (ADX < 20, India VIX elevated or range-bound), index option implied volatility overstates realized volatility. Selling out-of-the-money credit spreads with protective long wings captures time decay (theta) with strictly defined maximum risk.

### 3.2 Execution Rules
- **Instruments:** NIFTY weekly Bull Put Spreads (in bullish/sideways regimes) or Bear Call Spreads (in bearish/sideways regimes).
- **Strict Prohibition:** NEVER sell naked options. Every short option must have an accompanying long hedge leg.
- **Execution Sequence:** **The hedge leg (long wing) is ALWAYS placed and confirmed first** before the short leg is placed, ensuring no unhedged margin exposure.
- **Width:** 100 to 200 points on Nifty.
- **Max Loss:** Defined as (Spread Width - Premium Received) * Lot Size.
- **Margin Check:** Margin required must not exceed 25% of total virtual equity.
- **Exit Rules:** 50% max profit take-profit or 1.5x spread credit stop-loss. Auto-square-off by 15:15 IST.

---

## 4. Netting & Anti-Conflict Logic

If Sleeve F signals Long Futures while Sleeve O-Buy signals Long Put, or opposing sleeves trigger simultaneously:
1. Signal combiner evaluates net directional delta.
2. If opposite orders target the exact same contract, they are netted before submission to MegaBull.
3. If uncertainty or conflicting regimes persist, the Combiner outputs "NO_TRADE" (capital preservation).
