# Token Unlock Arbitrage Strategy

🔬 **Research-driven event strategy exploiting predictable price impacts around token unlock events.**

Based on empirical analysis of 35,000+ unlock events by Animoca Brands Research.

## The Edge

> **1% token unlock → 0.6% predictable price decline**  
> Optimal entry: 2 days before | Optimal exit: Day 4 after

## Quick Start

```bash
# Run backtest
cd backtest
python backtest.py

# Run tests
cd tests
python -m pytest test_strategy.py -v
```

## Strategy Overview

| Parameter | Value |
|-----------|-------|
| Direction | Short |
| Entry | 2 days before unlock (≥1% of supply) |
| Exit | Day 4 after unlock |
| Stop Loss | 2% |
| Position Size | Quarter-Kelly (max 10%) |
| Max Positions | 3 concurrent |

## Key Research Insights

1. **Anticipation = Selling Pressure**  
   Market prices in unlocks before they happen. Pre-unlock drop ≈ post-unlock drop.

2. **Timing is Everything**  
   - Day -2: Strongest pre-unlock impact
   - Days 0-1: Surprisingly little action  
   - Days 3-4: Peak selling pressure

3. **Size Threshold**  
   Only unlocks ≥1% of circulating supply matter. Small daily unlocks are noise.

## Installation

```bash
pip install -r requirements.txt  # numpy, pandas, pyyaml
```

## Usage

### Basic Backtest

```python
from backtest.backtest import BacktestEngine

engine = BacktestEngine('config/params.yaml')
metrics = engine.run_backtest()
engine.save_results('results/')
```

### Live Trading (Simulated)

```python
from src.strategy import TokenUnlockStrategy
from src.data_fetcher import DataAggregator

strategy = TokenUnlockStrategy('config/params.yaml')
aggregator = DataAggregator()

# Fetch upcoming unlocks
unlocks = aggregator.get_all_unlocks(days=90)
strategy.load_unlock_schedule(unlocks)

# Check for signals today
signals = strategy.generate_signals(datetime.now(), current_prices)
```

## Project Structure

```
token_unlock_arbitrage/
├── src/
│   ├── strategy.py          # Core strategy (600+ lines)
│   ├── risk_manager.py      # Risk controls
│   └── data_fetcher.py      # Data sources
├── backtest/
│   └── backtest.py          # Event-driven backtest
├── tests/
│   └── test_strategy.py     # Unit tests (20+ tests)
└── config/
    └── params.yaml          # Tunable parameters
```

## Performance (Synthetic Backtest)

Run `python backtest/backtest.py` for full results.

Expected performance on synthetic data:
- Win Rate: 60-70%
- Sharpe: 1.0-1.5
- Max DD: 15-25%

## Data Sources

- **CoinGecko API**: Market data, circulating supply
- **TokenUnlocks.app**: Unlock schedules (premium)
- **Manual CSV**: Backup/verification

## Risk Disclaimer

⚠️ **This is research code, not production-ready.**

- Backtest uses synthetic data
- Real unlock schedules can change
- Edge may decay with competition
- Always verify with paper trading first

## License

MIT License - Research purposes only.

---

**Built by:** ATLAS @ Siew's Capital  
**Model:** Token Unlock Event Arbitrage  
**Research Date:** April 2, 2026
