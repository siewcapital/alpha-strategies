# Strategy Research: Multi-Factor Regime-Adaptive Allocation

## Source Analysis
- **Primary Source:** Original research based on established quant factors
- **Author:** ATLAS (internal research)
- **Date Published:** 2026-03-30
- **Research Validation:** Literature review of Mebane Faber, AllocateSmartly, Khan & Lederman

## Core Strategy Logic

### Philosophy
Most quantitative strategies fail because they assume market regime is static. A trend-following strategy works brilliantly in trending markets but blows up in ranges. A mean-reversion strategy does the opposite. **This strategy solves that by detecting regime and dynamically weighting factor exposures.**

### The Four Core Factors

#### 1. Trend-Following (TF)
- **Signal:** Price > N-day SMA → long, price < N-day SMA → short
- **Lookback:** 20/50/200 day (adaptive)
- **Edge source:** Behavioral bias (disposition effect), institutional momentum
- **Works best in:** Trending, low-vol regimes

#### 2. Mean-Reversion (MR)
- **Signal:** Z-score of price vs N-day mean > threshold → expect reversion
- **Lookback:** 20 day
- **Edge source:** Occasional price spikes revert to fundamental value
- **Works best in:** Ranging, low-vol regimes

#### 3. Volatility Breakout (VB)
- **Signal:** ATR > 2x 20-day ATR mean → volatility expansion, momentum follows
- **Lookback:** 20 day
- **Edge source:** Volatility clustering (GARCH effect), momentum in vol expansion
- **Works best in:** High-vol, breakout regimes

#### 4. Momentum (MOM)
- **Signal:** Returns over N periods > median → long, < median → short
- **Lookback:** 20/60 day
- **Edge source:** Serial correlation in returns, behavioral momentum
- **Works best in:** Moderate trending regimes

### Regime Detection
Using a composite regime score:
- **Trend Strength:** ADX > 25 = trending
- **Range Strength:** RSI(14) between 40-60 = ranging
- **Volatility:** ATR percentile > 70% = high vol
- **Composite Score:** Weighted combination → regime label

### Adaptive Weighting
```
IF regime == "TRENDING":
    weights = {TF: 0.5, MR: 0.1, VB: 0.2, MOM: 0.2}
ELIF regime == "RANGING":
    weights = {TF: 0.1, MR: 0.5, VB: 0.2, MOM: 0.2}
ELIF regime == "HIGH_VOL":
    weights = {TF: 0.2, MR: 0.2, VB: 0.5, MOM: 0.1}
ELIF regime == "CALM":
    weights = {TF: 0.2, MR: 0.3, VB: 0.1, MOM: 0.4}
```

### Entry Rules
1. Calculate composite factor score from weighted signals
2. Score > +threshold → long, < -threshold → short
3. Entry size proportional to confidence (score magnitude)

### Exit Rules
1. Regime change → rebalance weights immediately
2. Stop loss: 2x ATR from entry
3. Time stop: 10 trading days max
4. Trailing stop: Pull below 20-day SMA

### Risk Management
- Max position: 20% of portfolio per asset
- Max leverage: 3x
- Max drawdown cutoff: 20% portfolio value
- Correlation filter: Max 3 correlated positions

## Why It Should Work
1. **Regime detection prevents blow-ups:** Trend-following strategies fail in ranges; this avoids that by reducing exposure
2. **Factor diversification:** Four uncorrelated factors reduce drawdown
3. **Adaptive weighting:** The market changes; fixed strategies don't
4. **Avoids overfitting:** Regime detection is robust across many parameter choices

## Potential Issues
- Regime detection lag: By the time we detect a regime change, it may have reversed
- Factor correlation: In crisis, all factors become correlated (correlation breakdown)
- Parameter sensitivity: Number of regimes and thresholds need careful calibration
- Transaction costs: Frequent rebalancing between regimes can eat profits

## Implementation Plan
1. Build regime detector (ADX, RSI, ATR percentile)
2. Build individual factor signal generators
3. Build composite score + adaptive weighting
4. Build backtest engine with realistic costs
5. Test on 5+ years of multi-asset data

## Similar Strategies Already Built
- `hmm_crypto_regime`: Hidden Markov Model regime detection (different approach)
- `crypto_momentum_rotation`: Momentum-only strategy (no regime adaptation)
- `volatility_mean_reversion`: Single factor (vol only)

**This is NEW:** Composite multi-factor with real-time regime-adaptive weighting.
