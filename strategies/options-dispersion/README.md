# Options Dispersion Trading Strategy

A sophisticated correlation arbitrage strategy that exploits mispricing between index implied volatility and single-stock implied volatilities.

## Overview

**Strategy Type:** Correlation Arbitrage / Volatility Trading  
**Asset Class:** Equity Index Options + Single Stock Options  
**Edge:** Captures the "correlation risk premium" where index options trade rich relative to constituent options

## Core Concept

The implied volatility of an index is typically lower than the weighted average of its constituents due to diversification effects. However, index options often trade at a premium due to hedging demand. The strategy:

- **Long Dispersion Trade:** Sell index straddles (expensive) + Buy single-stock straddles (cheap)
- **Profits when:** Actual correlation < implied correlation
- **Loses when:** Correlation spikes (crisis periods)

## Mathematical Foundation

### Index Variance Decomposition
```
σ²_index = Σᵢ wᵢ²σᵢ² + ΣᵢΣⱼ wᵢwⱼσᵢσⱼρᵢⱼ
```

### Implied Correlation
```
ρ_implied = (σ²_index - Σᵢ wᵢ²σᵢ²) / (ΣᵢΣⱼ≠ᵢ wᵢwⱼσᵢσⱼ)
```

## Project Structure

```
options-dispersion/
├── src/
│   ├── indicators.py       # Correlation & volatility calculations
│   ├── strategy.py         # Main strategy implementation
│   └── risk_manager.py     # Position sizing & risk controls
├── backtest/
│   ├── backtest.py         # Backtest engine
│   └── data_loader.py      # Data generation/fetching
├── tests/
│   └── test_strategy.py    # Unit tests
├── config/
│   └── params.yaml         # Strategy parameters
└── research.md             # Strategy research document
```

## Key Parameters

### Signal Generation
- `z_score_threshold_long`: 2.0 (Enter when correlation z-score > 2)
- `z_score_threshold_exit`: 0.0 (Exit when reverts to mean)
- `lookback_window`: 90 days for historical correlation

### Risk Management
- `max_vega_exposure`: 0.5% of portfolio
- `max_loss_per_trade`: 2%
- `max_hold_days`: 30 (time stop)
- `vix_max`: 35 (no new positions when VIX > 35)

### Position Sizing
- `target_vega_exposure`: 0.1% per trade
- Delta-hedged via underlying

## Running the Strategy

### 1. Run Tests
```bash
cd strategies/options-dispersion
python tests/test_strategy.py
```

### 2. Run Backtest
```bash
cd strategies/options-dispersion
python backtest/backtest.py
```

### 3. Use in Your Code
```python
from src.strategy import DispersionStrategy
import yaml

# Load config
with open('config/params.yaml', 'r') as f:
    params = yaml.safe_load(f)

# Initialize strategy
strategy = DispersionStrategy(
    params=params,
    initial_capital=1_000_000
)

# Run backtest (see backtest/backtest.py for full example)
```

## Performance Expectations

Based on research and backtests:

| Metric | Expected Range |
|--------|----------------|
| Annual Return | 8-15% |
| Sharpe Ratio | 0.8-1.4 |
| Max Drawdown | -10% to -20% |
| Win Rate | 55-65% |

**Best Performance:** Low-volatility, sideways markets with sector rotation  
**Worst Performance:** Crisis periods with correlation spikes

## Risk Considerations

1. **Correlation Spike Risk:** Major losses possible during market crises
2. **Vega Risk:** Exposure to volatility changes
3. **Gamma Risk:** Delta-hedging losses on large moves
4. **Single-Stock Event Risk:** Earnings surprises, M&A

## Academic References

1. "The Correlation Risk Premium" - Rebonato et al.
2. "Dispersion Trading: Empirical Evidence" - CBOE Research
3. "Variance Risk Premiums" - Bollerslev, Tauchen, Zhou
4. "Trading Correlation" - Meissner

## Future Enhancements

- [ ] Real options data integration (Polygon, OptionMetrics)
- [ ] Machine learning for correlation prediction
- [ ] Multi-index dispersion (sector ETFs)
- [ ] Intraday delta hedging optimization
- [ ] Cross-asset dispersion (FX, rates)

## Disclaimer

This is a research implementation. Do not use for live trading without thorough validation and risk management. Options trading involves significant risk of loss.

## License

MIT
