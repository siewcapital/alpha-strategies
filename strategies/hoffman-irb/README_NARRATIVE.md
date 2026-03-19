# Narrative-Enhanced Hoffman IRB Strategy

Integrates [NarrativeAlpha](../../../NarrativeAlpha/) signals with the Hoffman Inventory Retracement Bar (IRB) strategy to improve win rate and risk-adjusted returns.

## Overview

**Base Strategy:** Rob Hoffman IRB (Inventory Retracement Bar)  
**Enhancement:** NarrativeAlpha signal filtering and position sizing  
**Expected Improvement:** Win rate 61% → 70-75%

## How It Works

### 1. Narrative Signal Filtering

The enhanced strategy checks narrative alignment before entering trades:

| Technical Setup | Narrative Signal | Action |
|----------------|------------------|--------|
| Long IRB breakout | Bullish narrative + High confidence | ✅ Enter (1.5x-2.0x size) |
| Long IRB breakout | Neutral narrative | ⚠️ Enter (0.5x size) |
| Long IRB breakout | Bearish narrative | ❌ Skip trade |
| Short IRB breakout | Bearish narrative + High confidence | ✅ Enter (1.5x-2.0x size) |
| Short IRB breakout | Neutral narrative | ⚠️ Enter (0.5x size) |
| Short IRB breakout | Bullish narrative | ❌ Skip trade |

### 2. Position Size Scaling

Position sizes are dynamically adjusted based on:

- **Confidence Level:** VERY_HIGH = 2.0x, HIGH = 1.5x, MEDIUM = 1.0x, LOW = 0.5x
- **Saturation:** If saturation > 90%, reduce size by 30% (mean reversion risk)
- **Velocity:** If velocity < 30%, reduce size by 20% (momentum fading)

### 3. Mean Reversion Protection

When narrative saturation exceeds 90% with positive sentiment:
- Position size reduced to 50%
- Prevents buying at peak hype

## Files

| File | Purpose |
|------|---------|
| `strategy.py` | Base Hoffman IRB implementation |
| `narrative_enhanced.py` | Narrative-enhanced version |
| `backtest.py` | Base strategy backtest |
| `backtest_narrative_comparison.py` | Compare base vs enhanced |
| `multi_asset_test.py` | Multi-asset testing |

## Usage

### Prerequisites

1. NarrativeAlpha API running on `localhost:8000`
2. Required packages: `yfinance`, `pandas`, `numpy`, `matplotlib`

### Run Comparison Backtest

```bash
cd strategies/hoffman-irb

# Compare base vs narrative-enhanced
python backtest_narrative_comparison.py --symbol BTC-USD --period 2y

# Run on different asset
python backtest_narrative_comparison.py --symbol ETH-USD --period 1y

# Mock mode (no API required)
python backtest_narrative_comparison.py --mock-narrative
```

### Use in Your Strategy

```python
from narrative_enhanced import NarrativeEnhancedHoffmanIRB

# Initialize enhanced strategy
strategy = NarrativeEnhancedHoffmanIRB(
    ema_period=20,
    irb_threshold=0.45,
    risk_per_trade=0.02,
    narrative_min_confidence="MEDIUM",  # Filter threshold
    narrative_api_url="http://localhost:8000",
    use_narrative_filter=True,
    use_position_scaling=True
)

# Run backtest with narrative signals
signals, equity_curve = strategy.run_backtest(
    data=data,
    initial_capital=10000.0,
    transaction_cost=0.001,
    symbol="BTC-USD"
)
```

## Integration with Live Trading

```python
from narrativealpha.integration import NarrativeSignalClient

# Create client
client = NarrativeSignalClient(api_url="http://localhost:8000")

# Check narrative before entering trade
if client.should_enter_long("BTC/USDT"):
    # Get position size adjustment
    multiplier = client.get_position_size_adjustment("BTC/USDT")
    position_size *= multiplier
    execute_long_entry()
```

## Research Foundation

Based on ATLAS Research: [Narrative-Driven Alpha Strategies](../../../research/narrative-driven-alpha-research.md)

**Key Findings:**
- Narratives lead price by 1-3 days in crypto markets
- Sentiment correlation with price: 0.4-0.6
- Filtering by narrative confidence reduces false breakouts
- Saturation > 90% predicts mean reversion

## Performance Expectations

| Metric | Base IRB | Narrative-Enhanced | Expected Change |
|--------|----------|-------------------|-----------------|
| Win Rate | ~61% | 70-75% | +9-14% |
| Sharpe Ratio | Variable | +0.2-0.5 | Improved |
| Max Drawdown | Variable | -5% to -8% | Reduced |
| Total Return | Variable | +15-20% | Improved |

*Note: Actual results depend on market conditions and narrative data quality.*

## Configuration

### Narrative Filter Levels

```python
# Conservative (fewer trades, higher quality)
narrative_min_confidence="HIGH"

# Balanced (recommended)
narrative_min_confidence="MEDIUM"

# Aggressive (more trades, lower filter)
narrative_min_confidence="LOW"
```

### API Connection

If NarrativeAlpha API is on different host/port:

```python
strategy = NarrativeEnhancedHoffmanIRB(
    narrative_api_url="http://narrative-api.internal:8080"
)
```

## Troubleshooting

### API Connection Issues

If API is unavailable, the strategy falls back to base behavior:
```
⚠️  NarrativeAlpha API unavailable - trading without narrative filter
```

### No Narrative Signals

If no signals exist for symbol:
- Strategy trades normally (no filtering)
- Position sizing remains at 1.0x

### Mock Mode

For testing without API:
```python
strategy = NarrativeEnhancedHoffmanIRB(
    use_narrative_filter=False  # Disables API calls
)
```

## Next Steps

1. **Live Paper Trading:** Test with real market data
2. **Multi-Asset Expansion:** Add ETH, SOL, FET, ONDO
3. **Signal Aggregation:** Combine with other alpha sources
4. **Performance Tracking:** Monitor signal accuracy over time

---

*Built by FORGE | Siew's Capital Engineering Division*
