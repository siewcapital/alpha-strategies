# Rob Hoffman Inventory Retracement Bar (IRB) Strategy - Research Document

## Source
- **Primary Source**: Rob Hoffman - Award-winning trader and developer of the IRB strategy
- **Strategy Type**: Trend-following pullback strategy
- **Markets**: Originally developed for futures/forex, backtested on crypto (BTC)
- **Source URLs**: 
  - https://best-trading-platforms.com (backtest data)
  - Various trading education sources documenting the IRB methodology

---

## Strategy Logic

The Rob Hoffman Inventory Retracement Bar (IRB) strategy is designed to identify when short-term counter-trend institutional activity (inventory adjustments) has ceased, allowing the market to resume its original trend.

### Core Principle
Institutional investors occasionally need to adjust their positions, causing temporary counter-trend movements against the prevailing trend. The IRB strategy identifies when these adjustments complete, signaling a high-probability continuation of the original trend.

### Key Concepts
1. **Trend Identification**: Establish a clear trend using EMA and multi-timeframe analysis
2. **IRB Detection**: Identify candles showing institutional retracement characteristics
3. **Breakout Entry**: Enter when price breaks beyond the IRB in the trend direction
4. **Risk Management**: Use the IRB range for stop-loss placement

---

## Entry/Exit Rules

### 1. Trend Identification (Filter)

**EMA Trend Filter:**
- Use 20-period Exponential Moving Average (EMA20)
- **Uptrend**: EMA20 rising at approximately 45-degree angle
- **Downtrend**: EMA20 falling at approximately 45-degree angle
- **Multi-Timeframe Alignment**: Higher timeframe trend must align with trading timeframe

**Overlay Set (Optional Enhancement):**
- Use multiple EMAs (e.g., EMA8, EMA13, EMA21, EMA50)
- **Bullish alignment**: Faster EMAs above slower EMAs (EMA8 > EMA13 > EMA21 > EMA50)
- **Bearish alignment**: Faster EMAs below slower EMAs

### 2. IRB Identification

**Bullish IRB (in uptrend):**
- Bearish candle that opens and closes at least 45% below its high
- Candle has lower wick extending downward
- Volume ideally lower than preceding bars (indicates retracement, not reversal)
- Avoid overextended IRBs (range significantly above ATR of last 10 bars)

**Bearish IRB (in downtrend):**
- Bullish candle that opens and closes at least 45% above its low
- Candle has upper wick extending upward
- Volume ideally lower than average

### 3. Entry Rules

**Long Entry:**
1. Confirm uptrend via EMA filter
2. Identify bullish IRB (pullback candle)
3. **Entry**: Price breaks 1 tick/cent above the HIGH of the IRB
4. **Timing**: Breakout should occur within next 20 bars

**Short Entry:**
1. Confirm downtrend via EMA filter
2. Identify bearish IRB
3. **Entry**: Price breaks 1 tick/cent below the LOW of the IRB
4. **Timing**: Breakout should occur within next 20 bars

### 4. Exit Rules

**Stop-Loss:**
- **Long**: Place stop below the LOW of the IRB (or recent swing low)
- **Short**: Place stop above the HIGH of the IRB (or recent swing high)
- Alternative: Use ATR-based stop (e.g., 1.5x ATR from entry)

**Take-Profit:**
- **Fixed R:R**: Target 1.5:1 or 2:1 risk-reward ratio
- **Trailing Stop**: Move stop to breakeven once +1R reached, trail with ATR
- **Time-based**: Exit if trade doesn't move in 10 bars

**Invalidation:**
- If price reverses beyond the opposite side of IRB after entry, exit immediately

---

## Risk Management

### Position Sizing
- Risk 1-2% of capital per trade
- Calculate position size: `Position = (Account Risk $) / (Entry - Stop Loss)`

### Risk Controls
- Maximum 1 open trade per timeframe
- No trading during major news events (optional filter)
- Skip trades where IRB range > 2x ATR (overextended)

### Trade Management
- Move stop to breakeven once price reaches 1R profit
- Partial exits at 1.5R and 2R (scale out 50% each)

---

## Assets & Timeframes

### Recommended Assets
- **Primary**: BTC/USD (high volatility, strong trends)
- **Secondary**: ETH/USD
- **Others**: Major crypto pairs with sufficient liquidity

### Timeframes
- **Optimal**: 15-minute (balanced signal frequency vs. noise)
- **Alternative**: 5-minute (more signals, more noise)
- **Conservative**: 1-hour (fewer signals, higher quality)

### Backtest Parameters
- **Minimum Period**: 2 years of historical data
- **Transaction Costs**: 0.1% per trade (taker fees)
- **Slippage**: Account for spread in live trading

---

## Why It Works

### 1. Institutional Behavior
The strategy exploits temporary inventory adjustments by large players. When institutions need to rebalance, they create temporary price dips in uptrends (and rallies in downtrends) that get absorbed.

### 2. Trend Alignment
By requiring trend confirmation before entry, the strategy filters out counter-trend losses and focuses on high-probability continuation moves.

### 3. Defined Risk
The IRB structure provides a natural stop-loss level. If price breaks the opposite side of the IRB, the setup is invalidated, keeping losses small and contained.

### 4. Volatility Capture
Crypto markets exhibit strong trending behavior with frequent pullbacks, making this strategy particularly well-suited for BTC and ETH.

---

## Potential Issues

### 1. Whipsaws in Ranging Markets
The strategy performs poorly in sideways/choppy markets where trends fail to continue. The EMA filter helps but doesn't eliminate all false signals.

### 2. Late Entries
Waiting for the IRB breakout can result in missing the optimal entry point, especially in fast-moving markets.

### 3. Stop Placement Risk
Placing stops too close (just below IRB low) can result in stop-outs from normal volatility before trend continuation.

### 4. Timeframe Sensitivity
Lower timeframes (5m) generate more signals but with lower win rates. Higher timeframes (1h) have fewer signals but better quality.

### 5. Market Regime Dependency
The strategy works best in trending markets. During extended consolidation periods, consecutive losses can occur.

### Mitigation Strategies
- Use ADX filter (ADX > 25) to avoid ranging markets
- Implement session filters (trade only active market hours)
- Consider multiple timeframe confirmation
- Add volume confirmation on breakout

---

## Documented Backtest Results

### Bitcoin (BTC) - 15-Minute Timeframe
- **Win Rate**: 62%
- **Risk-Reward**: 1:1.5
- **Return**: 206% over test period
- **Consecutive Wins**: 8
- **Consecutive Losses**: 5
- **Risk per Trade**: 2%

### Alternative Backtest (BTC 15m - 1 month)
- **Winning Trades**: 43
- **Losing Trades**: 21
- **Total Gain**: 43.5%
- **Max Consecutive Wins**: 10

### AUD/JPY - 5-Minute Timeframe
- **Win Rate**: 63%
- **Trades**: 200
- **ROI**: 181%

---

## Implementation Notes

### Code Structure
1. **Trend Detection Module**: EMA calculation and trend state
2. **IRB Detection Module**: Pattern recognition for IRB candles
3. **Signal Generation**: Entry/exit logic
4. **Risk Management**: Position sizing and stop calculation
5. **Backtest Engine**: Performance calculation with transaction costs

### Visualization Requirements
- Equity curve showing account growth over time
- Drawdown chart highlighting maximum drawdown periods
- Monthly returns heatmap for consistency analysis
- Trade distribution (wins vs losses)

### Metrics to Track
- Sharpe Ratio (risk-adjusted returns)
- Sortino Ratio (downside risk focus)
- Calmar Ratio (return vs max drawdown)
- Maximum Drawdown
- Win Rate
- Profit Factor (gross profit / gross loss)
- Average Win/Loss ratio

---

## References
1. Rob Hoffman - Become a Better Trader (original strategy source)
2. Best Trading Platforms - IRB Strategy Backtest Results
3. Broadway Infosys - IRB Trading Strategy Documentation
4. TradingView Community - IRB Indicator Implementations

---

*Document created for ATLAS ALPHA HUNTER pipeline - Phase 2*
*Date: March 15, 2026*
