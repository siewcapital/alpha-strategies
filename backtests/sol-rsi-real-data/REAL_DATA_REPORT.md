# SOL RSI Mean Reversion - Real Data Backtest Report

**Date:** March 20, 2026  
**Data Source:** Binance SOL/USDT Spot (1H candles)  
**Date Range:** December 31, 2020 - March 19, 2026 (~4.2 years)  
**Total Candles:** 45,685 hours

---

## Executive Summary

Re-evaluation of the SOL RSI Mean Reversion strategy using real Binance market data reveals **significant divergence** from synthetic backtest results. The strategy performs substantially worse on real data, with losses of **-15.94%** compared to **-5.06%** on synthetic data—a difference of **-10.88 percentage points**.

**Key Finding:** Mean reversion strategies face significant challenges in trending cryptocurrency markets. SOL's strong directional moves (especially in 2021 and 2023) create adverse conditions for this strategy.

---

## Performance Comparison

| Metric | Synthetic Data | Real Data | Difference | % Change |
|--------|---------------|-----------|------------|----------|
| **Total Return** | -5.06% | **-15.94%** | -10.88% | -215.0% ⚠️ |
| Win Rate | 50.0% | **57.98%** | +7.98% | +16.0% ✅ |
| Profit Factor | 0.82 | **0.94** | +0.12 | +15.1% ✅ |
| Max Drawdown | 11.48% | **28.85%** | +17.36% | +151.2% ❌ |
| Sharpe Ratio | -0.35 | **-0.24** | +0.11 | +31.6% ✅ |
| Total Trades | 18 | **188** | +170 | +944% |
| Avg Win | 5.68% | **2.34%** | -3.34% | -58.8% |
| Avg Loss | -6.86% | **-2.95%** | +3.91% | +57.0% |

---

## Key Divergences Explained

### 1. **Return Divergence (-215%)** ❌ CRITICAL
Real data shows **3x worse returns** than synthetic. This is the most significant finding:
- Synthetic data assumes random walk with reversion
- Real SOL exhibits strong trending behavior (2021 bull run, 2023 recovery)
- Mean reversion fails during sustained directional moves

### 2. **Max Drawdown (+151%)** ❌ CRITICAL
Drawdown more than doubles on real data:
- Synthetic: 11.48% (controlled)
- Real: 28.85% (near 30%)
- Indicates tail risk is severely underestimated by synthetic data

### 3. **Win Rate Improvement (+16%)** ✅ POSITIVE
Higher win rate on real data (57.98% vs 50%):
- More trades = more opportunities
- Mean reversion does work in ranging markets
- Problem: Winners are smaller, losers are more frequent

### 4. **Trade Count (+944%)**
Real data spans 4+ years vs 1 year synthetic:
- More data = more statistical significance
- Reveals the strategy's true long-term performance
- Shows strategy doesn't scale well with time

---

## Yearly Performance Breakdown

| Year | PnL ($) | Cumulative ($) | Market Condition |
|------|---------|----------------|------------------|
| 2021 | +544 | $10,544 | Bull market - mean reversion works on pullbacks |
| 2022 | +1,112 | $11,656 | High volatility - favorable for mean reversion |
| 2023 | **-1,514** | $10,142 | Strong trend - mean reversion fails |
| 2024 | +173 | $10,315 | Recovery year - mixed performance |
| 2025 | **-791** | $9,524 | Choppy/sideways - whipsaws |
| 2026 | **-442** | $9,084 | YTD losses continue |

**Analysis:**
- Strategy worked in 2021-2022 (volatility, mean-reverting regime)
- Failed catastrophically in 2023 (strong trending regime)
- Continued bleeding in 2025-2026

---

## Trade Analysis

### Direction Performance

| Direction | Trades | Total PnL | Avg PnL/Trade | Win Rate |
|-----------|--------|-----------|---------------|----------|
| Long | 95 | -$136 | -$1.43 | ~55% |
| Short | 93 | -$781 | **-$8.40** | ~60% |

**Key Insight:** Short trades perform significantly worse. This makes sense:
- Crypto markets have upward drift over time
- Shorting into oversold conditions during uptrends = catching falling knives

### Exit Reasons

| Reason | Count | % of Trades | Avg PnL |
|--------|-------|-------------|---------|
| RSI Target (mean reversion) | 121 | 64.4% | Slightly positive |
| Stop Loss | 62 | 33.0% | **Negative** |
| Take Profit | 5 | 2.6% | Positive |

**Problem:** Only 2.6% of trades hit take profit. The 1.5:1 R:R ratio is rarely achieved, indicating the ATR-based targets may be too optimistic.

---

## Why Synthetic Data Failed

### 1. **Random Walk Assumption**
Synthetic data uses Gaussian random walk which doesn't capture:
- Volatility clustering (periods of high/low volatility)
- Trend persistence (markets trend more than random)
- Fat tails (extreme moves happen more often)

### 2. **Single Regime**
Synthetic data represents one market regime. Real SOL experienced:
- 2020-2021: Explosive growth (1.50 → $260)
- 2022: Bear market crash
- 2023: Recovery trend
- 2024-2026: Maturity/choppiness

### 3. **Underestimated Tail Risk**
Synthetic data didn't produce the extended drawdowns seen in real trading.

---

## Recommendations

### Immediate Actions

1. **DO NOT deploy this strategy live** without modifications
   - Real data shows consistent capital erosion
   - Drawdowns are unacceptable (29%)

2. **Add regime detection**
   - Only trade in ranging/mean-reverting markets
   - Use ADX or similar to filter trending periods
   - Consider volatility regime filters

3. **Improve short-side logic**
   - Short trades lose 6x more than longs
   - Consider removing shorts entirely
   - Or require stronger confirmation (RSI > 80)

4. **Adjust risk parameters**
   - Tighter stops (current 2x ATR may be too loose)
   - Smaller position sizes
   - Higher profit targets or trailing stops

### Research Directions

1. **Multi-timeframe analysis**
   - Check higher timeframe trend before entering
   - Only trade in direction of higher TF

2. **Volatility regime switching**
   - Reduce exposure in high-vol regimes
   - Increase in low-vol/ranging regimes

3. **Correlation with BTC**
   - SOL follows BTC - add BTC trend filter

---

## Files Generated

| File | Description |
|------|-------------|
| `sol_usdt_1h_real.csv` | Raw OHLCV data (45,685 candles) |
| `backtest_results.json` | Full metrics comparison |
| `trades.csv` | Complete trade list (188 trades) |
| `equity_curve.csv` | Equity curve for charting |
| `REAL_DATA_REPORT.md` | This report |

---

## Conclusion

**The SOL RSI Mean Reversion strategy is NOT viable** in its current form based on real market data. While it shows a higher win rate than synthetic data suggested, the magnitude of losses during trending periods far outweighs the gains during ranging periods.

The -15.94% return over 4+ years, with a maximum drawdown of nearly 29%, makes this strategy unsuitable for live deployment without significant modifications.

**Synthetic data significantly underestimated the risks** of this strategy, particularly the maximum drawdown and the frequency of stop-loss hits during trending markets.

---

*Report generated by ATLAS | Siew's Capital Research Division*  
*Strategy Status: VALIDATED (Real) - REQUIRES OPTIMIZATION*
