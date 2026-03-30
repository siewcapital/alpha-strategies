# Multi-Factor Regime-Adaptive Strategy

**ATLAS Research | Siew's Capital**

A quantitative trading strategy that adapts factor exposures based on detected market regime. The strategy combines four uncorrelated factors (trend-following, mean-reversion, volatility breakout, momentum) and dynamically weights them based on whether the market is trending, ranging, high-volatility, or calm.

## Philosophy

Most quantitative strategies fail because they assume market regime is static. A trend-following strategy works brilliantly in trending markets but blows up in ranges. A mean-reversion strategy does the opposite.

**This strategy solves that by detecting regime and dynamically weighting factor exposures.**

## The Four Core Factors

### 1. Trend-Following (TF)
- **Signal:** Price > N-day SMA → long, price < N-day SMA → short
- **Lookback:** 20/50 day SMA crossover
- **Edge source:** Behavioral bias (disposition effect), institutional momentum

### 2. Mean-Reversion (MR)
- **Signal:** Z-score of price vs N-day mean > threshold → expect reversion
- **Lookback:** 20 day with 2.0 Z threshold
- **Edge source:** Occasional price spikes revert to fundamental value

### 3. Volatility Breakout (VB)
- **Signal:** ATR > 2x 20-day ATR mean → volatility expansion, momentum follows
- **Edge source:** Volatility clustering (GARCH effect), momentum in vol expansion

### 4. Momentum (MOM)
- **Signal:** Short ROC > Long ROC → bullish momentum
- **Lookback:** 10/30 day ROC comparison

## Adaptive Weighting by Regime

```
IF regime == "TRENDING":
    weights = {TF: 0.50, MR: 0.10, VB: 0.20, MOM: 0.20}
    
IF regime == "RANGING":
    weights = {TF: 0.10, MR: 0.50, VB: 0.20, MOM: 0.20}
    
IF regime == "HIGH_VOL":
    weights = {TF: 0.20, MR: 0.10, VB: 0.60, MOM: 0.10}
    
IF regime == "CALM":
    weights = {TF: 0.20, MR: 0.25, VB: 0.05, MOM: 0.50}
```

## Architecture

```
multi_factor_regime_adaptive/
├── README.md                    # This file
├── research.md                  # Strategy research notes
├── config/
│   └── params.yaml             # Tunable parameters
├── src/
│   ├── __init__.py
│   ├── strategy.py             # Main strategy orchestrator
│   ├── indicators.py           # Technical indicators (ADX, RSI, ATR, etc.)
│   ├── factor_signals.py       # Factor signal generators
│   └── risk_manager.py         # Kelly sizing, circuit breakers
├── backtest/
│   └── backtest.py             # Backtest engine with optimization
├── tests/
│   └── test_strategy.py        # Unit tests
└── requirements.txt
```

## Installation

```bash
pip install numpy pandas scipy scikit-learn matplotlib requests
```

## Running Backtests

```bash
# Basic backtest
python backtest/backtest.py ./results

# Or use the full suite with optimization
python -c "
from backtest.backtest import run_full_backtest_suite
results = run_full_backtest_suite(n_days=1500, n_assets=5, output_dir='./results')
"
```

## Key Risk Features

1. **Kelly Criterion Sizing** - Mathematically optimal position sizing, capped at 25%
2. **Volatility Targeting** - Positions scale inversely to realized vol
3. **Circuit Breakers** - Stops trading at 20% drawdown
4. **Max Position Limits** - 20% per asset, 3x max leverage
5. **Correlation Filtering** - Prevents over-concentration

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

## Backtest Configuration

```yaml
# Default parameters in config/params.yaml
signal_threshold: 0.3       # Min composite score for entry
stop_loss_atr: 2.0           # ATR multiples for stop
trailing_stop_atr: 1.5       # ATR multiples for trailing stop
time_stop_bars: 10           # Max bars to hold
max_kelly: 0.25              # Max Kelly fraction
max_position_pct: 0.20       # Max position concentration
max_drawdown: 0.20           # Circuit breaker threshold
```

## Performance Metrics

Expected metrics (from synthetic backtest):
- Sharpe: 0.5-1.5 (regime adaptation improves over fixed strategies)
- Max DD: 15-25%
- Win Rate: 50-60%
- Annualized Return: 10-30%

## Status

**Status:** ✅ ARCHITECTURE COMPLETE - Backtest validated

**GitHub:** Co-Messi/alpha-strategies/strategies/multi_factor_regime_adaptive/
