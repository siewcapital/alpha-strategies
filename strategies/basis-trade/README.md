# Strategy 9: Crypto Basis Trade (Cash-and-Carry Arbitrage)

**Status:** ✅ Implementation Complete  
**Priority:** HIGH  
**Expected Yield:** 9-15% annualized  
**Risk Profile:** Market-neutral, low-medium risk

---

## Overview

The basis trade exploits the price difference between spot cryptocurrency and perpetual futures contracts. This market-neutral strategy captures the premium (contango) that futures typically trade at over spot prices.

## Strategy Mechanics

### Basic Structure
```
Long Leg:  Buy BTC spot at $100,000
Short Leg: Sell BTC perpetual futures at $101,000
Basis:     1% over 30 days = ~12% annualized
```

### Execution Flow
1. Monitor basis across multiple exchanges
2. Enter when basis > threshold (5% annualized)
3. Hold until basis compression or target reached
4. Earn funding rate payments on short perp position

## Market Opportunity (2025)

| Asset | Typical Yield | Driver |
|-------|---------------|--------|
| BTC   | 9-12%         | ETF inflows, institutional demand |
| ETH   | 10-15%        | Strong basis, ETH ETF growth |
| SOL   | 6-20%         | High volatility, funding rate swings |

## Implementation Status

- [x] Research complete
- [x] Market analysis documented
- [x] Architecture design
- [x] Basis monitoring module
- [x] Position management system
- [x] Risk management framework
- [x] Execution engine
- [x] Paper trading bot
- [ ] Live exchange integration
- [ ] 1-week paper trading validation
- [ ] Live deployment

## Architecture

```
basis-trade/
├── README.md
├── src/
│   ├── __init__.py
│   ├── basis_monitor.py      # Monitor basis across exchanges
│   ├── position_manager.py   # Track positions and P&L
│   ├── execution.py          # Risk management & order execution
│   └── bot.py                # Main trading bot
├── data/
│   └── positions.json        # Position state storage
├── results/
│   └── opportunities_*.json  # Opportunity logs
└── config.yaml               # Configuration
```

### Components

#### 1. BasisMonitor
- Fetches spot and perpetual prices from multiple exchanges
- Calculates annualized basis
- Tracks funding rates
- Identifies opportunities above threshold

#### 2. PositionManager
- Tracks open positions
- Calculates unrealized P&L
- Manages position lifecycle
- Persists state to disk
- Generates performance reports

#### 3. RiskManager
- Position sizing based on capital
- Pre-trade validation
- Circuit breakers (drawdown, daily loss)
- Stop loss and take profit levels

#### 4. ExecutionEngine
- Simultaneous leg execution
- Slippage monitoring
- Error handling and reversion
- Order management

#### 5. BasisTradeBot
- Main orchestration
- Trading cycle management
- Signal generation
- Status reporting

## Usage

### Paper Trading (Default)

```bash
cd strategies/basis-trade/src

# Run with default settings ($10K capital, 5% min yield)
python bot.py

# Custom settings
python bot.py --capital 50000 --min-yield 8 --interval 30

# Specific exchanges only
python bot.py --exchanges binance bybit

# Run for limited cycles
python bot.py --cycles 10
```

### Live Trading

⚠️ **WARNING**: Only enable after thorough paper trading validation

```bash
python bot.py --live --capital 10000
```

### Monitor Basis Only

```bash
python basis_monitor.py
```

## Configuration

### Command Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--capital` | 10000.0 | Trading capital in USD |
| `--min-yield` | 5.0 | Minimum annualized yield to enter (%) |
| `--interval` | 60 | Seconds between check cycles |
| `--cycles` | None | Max cycles (None = infinite) |
| `--live` | False | Enable live trading |
| `--exchanges` | binance, bybit | Exchanges to monitor |

### Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Max position size | 30% of capital | Maximum per-position allocation |
| Max total exposure | 90% of capital | Maximum across all positions |
| Stop loss | Entry - 3% | Close if basis drops 3% from entry |
| Take profit | Entry + 5% | Close if basis increases 5% |
| Max leverage | 2x | Conservative leverage on perp leg |
| Daily loss limit | $1,000 | Halt trading if exceeded |
| Max drawdown | 5% | Halt trading if exceeded |

## Risk Considerations

1. **Funding rate volatility** — Dynamic sizing required
2. **Basis compression** — Diversify across symbols
3. **Counterparty risk** — Multi-exchange exposure
4. **Execution risk** — Simultaneous leg entry
5. **Liquidity risk** — Size positions appropriately

## Current Opportunities (Live Data)

Run `python basis_monitor.py` to see current opportunities.

Typical output:
```
================================================================================
BASIS TRADE OPPORTUNITIES
================================================================================
Exchange     Symbol   Spot           Perp           Basis %      Type      
--------------------------------------------------------------------------------
bybit        SOL      $89.62         $89.80         +7.34%       Contango  
binance      BTC      $70,539.73     $70,600.00     +3.12%       Contango  
================================================================================
```

## Performance Expectations

| Metric | Expected |
|--------|----------|
| Annualized Yield | 9-15% |
| Max Drawdown | <10% |
| Win Rate | ~70% |
| Sharpe Ratio | 1.5-2.0 |
| Time in Market | 60-80% |

## Next Steps

1. **Paper Trading Validation** (1 week)
   - Run bot with paper trading
   - Validate signals and execution
   - Monitor P&L vs expectations

2. **Live Deployment** (Week 2)
   - Start with $5K test capital
   - Monitor closely for first 48 hours
   - Scale to full allocation if successful

3. **Optimization**
   - Parameter tuning based on live data
   - Add more exchanges
   - Implement dynamic position sizing

## Resources

- [Understanding Basis Trading](https://www.cmegroup.com/education/courses/introduction-to-basis-trading.html)
- [Perpetual Futures Funding Rates](https://www.binance.com/en/support/faq/leverage-and-margin-of-crypto-trading-360043074591)

---

*Strategy 9 | Siew's Capital Alpha Suite | Updated March 2026*
