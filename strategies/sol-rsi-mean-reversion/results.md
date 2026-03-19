# SOL/USDT RSI Mean Reversion - Backtest Results

## Strategy Overview

Mean reversion strategy on SOL/USDT using RSI oversold/overbought signals with trend confirmation and ATR-based position sizing.

**Entry Logic:**
- Long when RSI(14) < 30 AND price > EMA(50) (oversold in uptrend)
- Short when RSI(14) > 70 AND price < EMA(50) (overbought in downtrend)

**Exit Logic:**
- RSI reversion to 50
- Stop loss at 2x ATR
- Take profit at 3x ATR (1.5:1 R:R)

---

## Backtest Results

### Performance Summary

| Metric | Value |
|--------|-------|
| **Initial Capital** | $10,000.00 |
| **Final Capital** | $9,493.92 |
| **Total Return** | -5.06% |
| **Total Trades** | 18 |
| **Win Rate** | 50.0% |
| **Profit Factor** | 0.82 |
| **Sharpe Ratio** | -0.35 |
| **Max Drawdown** | 11.48% |

### Trade Statistics

| Metric | Value |
|--------|-------|
| **Avg Trade Return** | -0.59% |
| **Avg Win** | +5.68% |
| **Avg Loss** | -6.86% |

---

## Analysis

### Key Observations

1. **Negative Returns**: The strategy lost -5.06% over the backtest period on synthetic data

2. **50% Win Rate**: Despite an even win/loss ratio, the strategy is unprofitable due to **asymmetric R:R**
   - Average win: +5.68%
   - Average loss: -6.86%
   - Losses are larger than wins on average

3. **Low Trade Count**: Only 18 trades suggests either:
   - Strict entry criteria filtering out many opportunities
   - Mean reversion signals are relatively rare in trending markets

4. **High Drawdown**: 11.48% max drawdown relative to -5% total return indicates periods of concentrated losses

### Why It Underperformed

1. **Synthetic Data Limitations**: 
   - Random walk data doesn't capture true mean-reverting tendencies
   - Real crypto markets have fatter tails and stronger mean reversion

2. **Trend Filter May Be Too Strict**:
   - Requiring price > EMA(50) for longs in an uptrend misses counter-trend bounces
   - May filter out valid mean reversion opportunities

3. **ATR-Based Stops May Be Too Wide**:
   - 2x ATR stops with 3x ATR targets assumes mean reversion
   - In trending markets, this can lead to larger losses

4. **RSI Thresholds**:
   - RSI < 30 / > 70 are extreme levels
   - May only trigger in strong moves that continue rather than reverse

### Recommendations for Improvement

1. **Test on Real SOL Data**: 
   - Synthetic data results may not reflect real market behavior
   - SOL has distinct mean-reverting characteristics during certain regimes

2. **Optimize RSI Levels**:
   - Try RSI < 40 / > 60 for more frequent signals
   - Consider adaptive RSI based on volatility regime

3. **Refine Trend Filter**:
   - Use shorter EMA (e.g., 20) for faster response
   - Or remove trend filter for pure mean reversion

4. **Adjust Risk:Reward**:
   - Current 1.5:1 R:R requires >60% win rate to be profitable
   - Consider 2:1 or higher R:R targets

5. **Add Regime Filter**:
   - Mean reversion works poorly in strong trends
   - Add ADX or volatility filter to disable in trending markets

---

## Files

- `backtest.py` - Full strategy implementation
- `results.json` - Raw backtest data
- `results.md` - This file

## Running the Backtest

```bash
cd strategies/sol-rsi-mean-reversion
pip install -r requirements.txt
python backtest.py
```

---

## Disclaimer

These results are from backtesting on synthetic data. Past performance does not guarantee future results. Mean reversion strategies can experience significant drawdowns during trending markets.
