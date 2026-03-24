# Strategy Research: Crypto Funding Rate Arbitrage

## Source Analysis
- **Primary Source:** Web Search - Multiple sources including CoinGlass, Binance, Medium articles
- **Author:** Various practitioners and institutional traders
- **Date Published:** 2026 (current market conditions)
- **Your Analysis Date:** 2026-03-24

## Core Strategy Logic

Funding rate arbitrage exploits the difference between perpetual futures prices and spot prices. The funding rate is paid between long and short traders to keep the perpetual price aligned with the spot price.

### Two Primary Types:

#### 1. Spot-to-Perpetual Arbitrage
- Buy crypto on spot market
- Short equivalent amount on perpetual futures
- Collect funding payments (if positive)
- Close both positions when rates turn unfavorable

#### 2. Cross-Exchange Funding Rate Arbitrage
- Long position on exchange with lower/negative funding rate
- Short position on exchange with higher/positive funding rate
- Market-neutral: profits from rate differential only
- No spot exposure needed

### Entry Rules
1. Identify funding rate differential > threshold (e.g., 0.01% per 8 hours)
2. Calculate expected annual return: rate * 3 * 365 (funding settles 3x daily)
3. Subtract trading fees, borrowing costs, and spread costs
4. Net expected return > minimum threshold (e.g., 5% APR)
5. Execute hedge ratio: 1:1 for perpetual/spot

### Exit Rules
1. Funding rate reverses sign
2. Net return drops below threshold after costs
3. Position reaches max holding period (typically 7-14 days)
4. Liquidation risk exceeds threshold (margin < 30% of position)

### Risk Management
- Position Size: Max 10% of portfolio per arbitrage pair
- Leverage: 2-3x max (to avoid liquidation in volatility)
- Max Drawdown Cutoff: 5% portfolio-level stop
- Correlation Check: Don't run multiple arb on correlated assets simultaneously
- Liquidation Buffer: Maintain 50%+ margin cushion

## Why It Should Work

1. **Market Inefficiency:** Funding rates vary between exchanges due to:
   - Different liquidity pools
   - Varying trader sentiment
   - Exchange-specific incentive programs

2. **Institutional Edge:** Most retail can't execute fast enough
   - Requires real-time monitoring
   - Needs cross-exchange infrastructure
   - Benefits from low-latency execution

3. **Regime Dependency:** Works best in:
   - High volatility periods (funding spikes)
   - New token listings (high funding dislocations)
   - Market stress (fear/greed extremes)

## Potential Issues

- **Overfitting Risk:** Historical funding patterns may not persist
- **Regime Change:** Institutional competition increasing
- **Liquidity Constraints:** Large positions face slippage
- **Implementation Slippage:** Delay between signal and execution
- **Exchange Risk:** Counterparty risk, API failures
- **Regulatory Risk:** Changing rules on crypto derivatives

## Similar Strategies Already Built

From memory:
1. DeFi Liquidation Arbitrage - Different (on-chain, liquidation-focused)
2. Polymarket Combinatorial Arbitrage - Different (prediction markets)
3. Crypto Cross-Sectional Momentum - Different (momentum-based)
4. StatArb with Kalman Filter - Different (statistical pairs trading)

This funding rate arbitrage is a NEW strategy type - market-neutral rate capture.

## Implementation Plan

1. Build data fetcher for funding rates across exchanges (Binance, Bybit, OKX)
2. Implement signal generator for rate differentials
3. Create execution engine with paper trading capability
4. Backtest on historical data (2023-2026)
5. Optimize for realistic slippage and fees
