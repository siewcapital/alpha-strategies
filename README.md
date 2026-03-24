# Crypto Funding Rate Arbitrage Strategy

Quantitative trading strategy that exploits funding rate differentials between cryptocurrency perpetual futures contracts across multiple exchanges.

## Strategy Overview

**Type:** Market-Neutral Arbitrage  
**Timeframe:** Intraday to Multi-day  
**Assets:** Top 10 Crypto Perpetuals  
**Exchanges:** Binance, Bybit, OKX  

## The Edge

Funding rates on crypto perpetual futures vary between exchanges due to:
- Different liquidity pools
- Varying trader sentiment
- Exchange-specific incentive programs

This strategy captures the differential by going long on the exchange with lower funding (or negative rates) and short on the exchange with higher funding.

## How It Works

### Two Modes

1. **Spot-to-Perpetual:** Buy spot, short perpetual, collect funding
2. **Cross-Exchange:** Long on low-funding CEX, short on high-funding CEX

### Entry Criteria
- Funding rate differential > 0.01% per 8-hour period
- Expected annual return after costs > 5%
- Position size within risk limits

### Exit Criteria
- Funding rate reverses sign
- Rate differential drops below threshold
- Max holding period (7 days) reached
- Stop loss triggered (5% portfolio drawdown)

## Architecture

```
funding_rate_arb/
├── README.md                    # This file
├── research.md                   # Strategy research notes
├── config/
│   └── params.yaml              # Strategy parameters
├── src/
│   ├── __init__.py
│   ├── strategy.py              # Core strategy logic (400+ lines)
│   ├── data_fetcher.py          # Exchange data fetching
│   └── risk_manager.py          # Risk management
├── backtest/
│   └── backtest.py              # Backtest engine
├── tests/
│   ├── test_strategy.py         # Unit tests
├── results/
│   ├── equity_curve.csv
│   ├── trades.csv
│   └── metrics.json
└── requirements.txt
```

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Edit `config/params.yaml` to adjust:

- `min_funding_diff`: Minimum rate differential (default: 0.01%)
- `min_expected_arb_return`: Minimum expected return (default: 5%)
- `max_leverage`: Maximum leverage (default: 2.5x)
- `max_position_size`: Max position as % of portfolio (default: 10%)

## Usage

### Run Backtest

```bash
cd backtest
python backtest.py
```

### Run Tests

```bash
python -m pytest tests/
```

### Live Trading (Paper First)

```python
from strategy import FundingRateArbitrageStrategy
from data_fetcher import FundingRateDataFetcher
import asyncio

async def main():
    # Initialize
    config = load_config("config/params.yaml")
    strategy = FundingRateArbitrageStrategy("config/params.yaml")
    
    # Fetch data
    async with FundingRateDataFetcher(config) as fetcher:
        funding_data = await fetcher.fetch_all_funding(["BTC", "ETH", "SOL"])
    
    # Scan opportunities
    opportunities = strategy.scan_opportunities(funding_data)
    
    # Execute
    for opp in opportunities:
        signal, position = strategy.generate_signal(opp, portfolio_value=100000)
        # ... execute via broker

asyncio.run(main())
```

## Performance (Backtest)

- **Period:** 2023-01-01 to 2026-03-24
- **Initial Capital:** $100,000
- **Expected Return:** Variable based on market conditions
- **Risk:** Market-neutral (hedge between exchanges)

## Risk Management

- Max 10% portfolio per position
- Max 5 concurrent positions
- Max 5% portfolio drawdown stop
- 50% minimum margin buffer

## Requirements

- Python 3.9+
- aiohttp
- pandas
- numpy
- pyyaml
- pytest

## Status

**ARCHITECTURE COMPLETE** - Ready for backtesting and optimization.

## Author

ATLAS (Siew's Capital) - 2026-03-24

## License

Proprietary - Siew's Capital
