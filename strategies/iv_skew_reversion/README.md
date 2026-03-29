# IV Skew Mean Reversion Strategy

**Strategy Type:** Volatility Arbitrage / Options
**Edge:** IV skew mean-reversion in crypto options markets
**Timeframe:** Daily signals, 2-4 week options

## Overview

The IV Skew Mean Reversion (IVSR) strategy exploits the observation that implied volatility (IV) skew in crypto options markets is mean-reverting. When OTM puts become extremely expensive relative to ATM options (skew very negative), the skew tends to normalize, creating profitable reversal opportunities.

**Core Trade:** Sell OTM puts when skew < -20% (puts expensive) → skew normalizes → profit.

## The Edge

Crypto options markets exhibit persistent negative skew because:
1. Retail demand for downside protection inflates put prices
2. Market makers are risk-averse and widen put spreads
3. Fear-driven buying creates "crash premium" in OTM puts

This premium is real but mean-reverting — extreme skew levels eventually normalize.

## Architecture

```
iv_skew_reversion/
├── config/
│   └── params.yaml              # All tunable parameters
├── src/
│   ├── __init__.py
│   ├── indicators.py            # Vol surface calculator, signal generator (400+ lines)
│   ├── strategy.py              # Main orchestrator (500+ lines)
│   └── risk_manager.py          # Position sizing, delta hedging (400+ lines)
├── backtest/
│   └── backtest.py              # Event-driven backtest engine (350+ lines)
├── tests/
│   └── test_strategy.py         # Unit tests
├── results/                     # Backtest outputs
├── research.md                  # Strategy research notes
└── README.md                    # This file
```

## Quick Start

### 1. Run Backtest

```bash
cd strategies/iv_skew_reversion
python backtest/backtest.py
```

### 2. Run Tests

```bash
cd strategies/iv_skew_reversion
python -m unittest tests.test_strategy
```

### 3. Use in Code

```python
from src import IVSkewReversionStrategy, RiskManager
import yaml

with open("config/params.yaml") as f:
    params = yaml.safe_load(f)

strategy = IVSkewReversionStrategy(params=params, initial_capital=1_000_000)

# Process market data
result = strategy.process_market_data(
    timestamp=pd.Timestamp.today(),
    asset="BTC",
    spot_price=50000,
    atm_straddle_iv=0.80,
    otm_put_iv=0.65,
    otm_call_iv=0.76,
    rv_30d=0.75,
)
```

## Strategy Logic

### Entry Signals

| Signal | Condition | Action |
|--------|-----------|--------|
| LONG_SKEW_REVERSION | Skew < -20% AND Z-score > 2 | Sell OTM puts |
| SHORT_SKEW_REVERSION | Skew > -50% AND Z-score < -2 | Buy OTM puts |

### Exit Rules

| Exit | Condition |
|------|-----------|
| Take Profit | Skew reverts to -30% to -35% |
| Stop Loss | Skew widens past -65% |
| Time Stop | 21 days maximum |

### Risk Management

- Position sizing: Kelly-based, 2% portfolio risk per trade
- Max concurrent trades: 3
- Delta hedge: 50% via futures/perp
- Portfolio max exposure: 20% notional
- Drawdown cutoff: 20%

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| skew_entry_long | -20% | Enter long skew when skew below this |
| skew_entry_short | -50% | Enter short skew when skew above this |
| skew_mean_reversion | -35% | Target skew for take profit |
| rv_min_entry | 50% | Min realized vol to enter (filter) |
| skew_z_threshold | 2.0 | Min Z-score to confirm signal |
| time_stop_days | 21 | Max holding period |

## Results (Synthetic Backtest 2021-2026)

See `results/` directory for full output.

- **Sharpe Ratio:** Expected 0.8-1.5 (varies by vol regime)
- **Max Drawdown:** Expected 10-25%
- **Win Rate:** Expected 55-65%
- **Trade Frequency:** 2-4 trades per month

## Key Insights

1. **Skew is persistent:** Crypto skew doesn't mean-revert quickly — requires patience
2. **Crisis periods are dangerous:** Skew can widen far beyond historical norms
3. **Vol regime matters:** High-vol regimes are best for skew reversion trades
4. **Delta hedging is essential:** Reduces directional exposure significantly
5. **Options data quality:** Real IV data from Deribit/Binance required for live trading

## Data Requirements

For live trading:
- ATM straddle IV (or ATM put/call IV)
- OTM put IV (10-25 delta)
- OTM call IV (25 delta)
- Realized vol (30-day Garman-Klass)
- Spot price

Sources: Deribit API, Binance options, OptionMetrics

## Limitations

- Synthetic backtest may not capture real skew dynamics
- Real market has wider spreads and slippage
- Black swan events can blow through stop losses
- Options liquidity varies significantly by strike/expiry

## Status

✅ Architecture Complete
✅ Unit Tests Passing
✅ Backtest Engine Built
⚠️ Needs Real Market Data Validation
