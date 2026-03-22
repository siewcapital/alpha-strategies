# Strategy Research: StatArb Alpha: Cointegrated Pairs Trading with Kalman Filter

## Source Analysis
- **Primary Source:** Inspired by @w1nklerr (X/Quant Research) + General Quant Trading Principles
- **Author:** ATLAS Quant Research (based on 2026 Crypto Market Trends)
- **Date Published:** 2026-03-22 (Current Research)
- **Your Analysis Date:** 2026-03-22

## Core Strategy Logic
The strategy identifies and exploits mean-reverting price relationships between highly correlated crypto assets (e.g., SOL/ETH, BTC/ETH). While traditional pairs trading uses a fixed hedge ratio (e.g., OLS), this strategy employs a **Kalman Filter** to dynamically update the hedge ratio in real-time, accounting for non-stationarity and changing market regimes.

### Entry Rules
1. **Cointegration Check:** Ensure the pair is cointegrated over a rolling 180-day window (Engle-Granger test p-value < 0.05).
2. **Kalman Smoothing:** Use a state-space model where the hedge ratio (β) is the hidden state.
3. **Signal (Z-Score):** Calculate the Z-score of the current spread (PriceA - β * PriceB).
4. **Trigger:** Enter Long Spread (Buy A, Sell B) if Z-Score < -2.0. Enter Short Spread (Sell A, Buy B) if Z-Score > 2.0.
5. **Filters:** Only enter if the estimated half-life of mean reversion is < 15 days (Ornstein-Uhlenbeck estimation).

### Exit Rules
1. **Mean Reversion:** Close position when the Z-score crosses 0.
2. **Stop Loss:** Exit if $|Z-Score| > 4.0$ (divergence risk) OR if cointegration p-value exceeds 0.10.
3. **Time Stop:** Max holding period of 30 days (based on estimated half-life).

### Risk Management
- **Hedge Ratio:** Dynamically updated via Kalman Filter (prevents beta drift).
- **Position Sizing:** Kelly Criterion (adjusted for win rate and profit factor) or volatility-adjusted sizing.
- **Correlation Monitor:** Exit if rolling 30-day correlation falls below 0.6.
- **Drawdown Limit:** 2% per trade, 10% per strategy.

## Why It Should Work
Crypto markets are highly inefficient and emotional. Assets within the same ecosystem (e.g., L1s, DeFi protocols) tend to be driven by common macro and sentiment factors. When their price relationship deviates significantly from its historical mean, it often represents a temporary dislocation that will be corrected as arbitrageurs (like this strategy) step in. The Kalman Filter provides a significant edge over static OLS by adapting to structural shifts in the hedge ratio.

## Potential Issues
- **Structural Breaks:** Permanent divergence due to fundamental news (e.g., hack, protocol failure).
- **Execution Latency:** High-frequency slippage can erode the small alpha of individual trades.
- **Overfitting:** The transition noise (Q) and observation noise (R) in the Kalman Filter can be over-tuned to historical data.
- **Liquidity:** Scaling to large size might be difficult in lower-cap pairs.

## Similar Strategies Already Built
- Crypto Cross-Sectional Momentum (similar universe, different logic).
- DeFi Liquidation Arbitrage (event-driven, not statistical).
- Polymarket Arbitrage (combinatorial, not pairs-based).
