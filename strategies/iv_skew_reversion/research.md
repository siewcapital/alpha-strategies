# Strategy Research: Implied Volatility Skew Mean Reversion (IVSR)

## Source Analysis
- **Primary Source:** Quantitative research on crypto options volatility surfaces
- **Supporting Sources:** CBOE Skew Index methodology, crypto options market maker behavior research, Deribit exchange data
- **Date Published:** March 2026
- **Your Analysis Date:** 2026-03-29

## Core Strategy Logic

**The Edge:** Crypto options markets exhibit persistent negative skew (puts more expensive than calls) due to crash risk premium demanded by buyers. This skew is mean-reverting — extreme skew levels tend to normalize, creating profitable reversion opportunities.

### Key Concept: IV Skew

```
IV Skew = (25-delta put IV - ATM straddle IV) / ATM straddle IV × 100
```

- **Negative skew (skew > 0 in practice):** OTM puts are expensive relative to ATM options
- **Positive skew:** OTM calls are more expensive (rare in crypto)
- **Crypto characteristic:** Skew ranges from -10 to -60 (puts 10-60% cheaper than ATM calls)

### Why Crypto Skew Is Mean-Reverting

1. **Crash premium compression:** Fear-driven put buying inflates skew; after events pass, skew normalizes
2. **Market maker hedging:** When BTC drops, MMs hedge delta which creates put demand spiral
3. **Retail vs. institutional:** Retail overweights tail risk → puts perpetually overpriced
4. **Regime dependency:** Skew is most extreme during high-vol regimes (crisis periods)

### Entry Rules

1. **Skew Entry Signal:**
   - LONG SKEW REVERSION: Skew > upper threshold (e.g., -20%) → sell OTM puts, skew will compress
   - SHORT SKEW REVERSION: Skew < lower threshold (e.g., -50%) → buy OTM puts, skew will expand

2. **Regime Filter:**
   - Only enter when realized volatility is HIGH (>50% annualized) — skew is most reliable then
   - Avoid entering during low-vol regimes (<30% RV) — skew is compressed naturally

3. **Time Horizon:**
   - Skew mean-reversion typically takes 5-20 days
   - Options expiry: 2-4 weeks out (enough time for reversion)

### Exit Rules

1. **Take Profit:** Skew reverts to mean (-30% to -35%) → close position
2. **Stop Loss:** Skew widens by additional 15 percentage points → exit with loss
3. **Time Stop:** 21 days (before major expiry events)

### Risk Management

- **Position Size:** 1-2% of portfolio per trade (options-only risk)
- **Delta Hedge:** Partially hedge with futures/perp to reduce directional risk
- **Max Loss:** 3% portfolio per trade hard stop
- **Portfolio Limit:** Max 3 concurrent skew trades

## Why It Should Work

1. **Mean reversion is a proven quant phenomenon:** Extreme values revert to mean
2. **Crypto skew is more extreme than equities:** Larger premium = larger reversion opportunity
3. **Options market immaturity:** Less efficient pricing = larger alpha
4. **Behavioral bias:** Retail crash fear creates persistent put premium

## Potential Issues

- **Black swan events:** Skew can widen beyond all historical precedents
- **Liquidity:** OTM options may have wide bid-ask spreads
- **Timing:** Reversion may take longer than expected
- **Volatility clustering:** High vol regimes persist longer than anticipated
- **Exchange risk:** Deribit/Binance options settlement risk

## Similar Strategies Already Built

- **VRP Harvester:** Harvests IV - RV premium (related but different focus)
- **Volatility Mean Reversion:** Trades RV deviations (not skew)
- **Options Dispersion:** Trades index vs. single-stock correlation

## Implementation Notes

- Data: Synthetic generated based on realistic BTC/ETH vol surface dynamics
- Assets: BTC and ETH options on Deribit
- Timeframe: Daily signal, 2-4 week options
- Backtest: 3 years synthetic data with realistic vol regime changes
