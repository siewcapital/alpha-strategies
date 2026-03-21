# Alpha Strategies

A systematic collection of quantitative trading strategies, arbitrage opportunities, and prediction market edges.

## Phase Status

| Phase | Status | Date | Key Deliverables |
|-------|--------|------|------------------|
| Phase 1: Strategy Dev | ✅ Complete | Feb 2026 | 8 strategies implemented |
| Phase 2: Backtesting | ✅ Complete | Feb 2026 | All strategies backtested |
| Phase 3: Documentation | ✅ Complete | Mar 2026 | Full docs for all strategies |
| Phase 4: Production Prep | ✅ Complete | Mar 2026 | CCXT, paper trading, dashboard |
| **Phase 5: Real Data Validation** | **✅ Complete** | **Mar 20, 2026** | **Real Binance data, CCXT testnet, enhanced dashboard** |
| **Phase 6: Documentation & Dashboard** | **✅ Complete** | **Mar 22, 2026** | **Complete backtest docs, OBI docs, Polymarket README, Performance Dashboard** |

## Phase 5 Highlights (March 20, 2026)

### 1. SOL RSI Strategy - Re-evaluated with Real Data
- **Original (Real Data)**: -15.94% return, 28.85% max drawdown
- **Optimized Version**: +1.50% return, 0.97% max drawdown on fresh Binance data
- **Key fixes**: Long-only, ADX regime filter, HTF confirmation, tighter stops
- **Status**: Ready for testnet paper trading

### 2. CCXT Connector - Testnet Validated
- Binance testnet: ✅ All tests passed
- Funding rates, OHLCV, tickers: Working
- Multi-exchange support: Functional
- **File**: `trading_connectors/test_ccxt_testnet.py`

### 3. Dashboard Enhanced with Real-time Feeds
- WebSocket support via Flask-SocketIO
- Live price tickers (BTC, ETH, SOL)
- Real-time funding rate displays
- **File**: `dashboard/app_ws.py`

## Phase 6 Highlights (March 22, 2026)

### 1. SOL RSI Complete Backtest Results
- **New Document**: `strategies/sol-rsi-mean-reversion/RESULTS.md`
- 4.2 years of real Binance data analyzed
- Original vs Optimized comparison
- Yearly performance breakdown
- Filter statistics and trade analysis

### 2. OBI Microstructure Full Documentation
- **New Document**: `strategies/obi_microstructure_strategy/DOCUMENTATION.md`
- Theoretical foundation with academic references
- Implementation details and pseudocode
- Risk management specifications
- Real-world deployment checklist

### 3. Polymarket Strategies README
- **New Document**: `polymarket_paper/README.md`
- Complete API reference
- Paper trading environment documentation
- Example strategies
- Performance tracking guide

### 4. Performance Metrics Dashboard
- **New Tool**: `dashboard/performance_dashboard.py`
- Aggregates metrics from all strategies
- CSV export capability
- Command-line interface
- Run: `python dashboard/performance_dashboard.py`

## Strategies

| Strategy | Asset(s) | Status | Performance (Backtest) | Documentation |
|----------|----------|--------|------------------------|---------------|
| **[SOL RSI Mean Reversion](strategies/sol-rsi-mean-reversion/)** | SOL/USDT | ✅ **OPTIMIZED** | **Sharpe: 0.11** (Phase 5) | [RESULTS.md](strategies/sol-rsi-mean-reversion/RESULTS.md) |
| **[Polymarket HFT](polymarket_paper/)** | BTC Binary | ✅ VALIDATED | Median Return: 2,645% | [README.md](polymarket_paper/README.md) |
| **[Hoffman IRB](strategies/hoffman-irb/)** | BTC, ETH, SOL | ✅ TESTED | Sharpe: 1.34-1.94 (ETH/SOL) | [FINAL_REPORT.md](strategies/hoffman-irb/FINAL_REPORT.md) |
| **[OBI Microstructure](strategies/obi_microstructure_strategy/)** | BTC Perp | ⚠️ NEEDS VALIDATION | Sharpe: -232 (synthetic) | [DOCUMENTATION.md](strategies/obi_microstructure_strategy/DOCUMENTATION.md) |
| **[Options Dispersion](strategies/options-dispersion/)** | Crypto Options | ✅ READY | Phase 8 complete | [PHASE_8_REPORT.md](strategies/options-dispersion/PHASE_8_REPORT.md) |
| **[Cross-Exchange Funding Arb](strategies/cross_exchange_funding_arb/)** | Multiple | ⚠️ UNPROFITABLE | High fee sensitivity | README.md |
| **[VRP Harvester](strategies/vrp_harvester/)** | BTC, ETH | ⚠️ INCONCLUSIVE | Insufficient data | [results.md](strategies/vrp_harvester/results.md) |
| **[Polymarket Arbitrage](strategies/polymarket-arbitrage/)** | Multiple | 🚧 RESEARCH | In progress | TBD |

## Repository Structure

```
strategies/
├── sol-rsi-mean-reversion/
│   ├── RESULTS.md          # ✅ Complete backtest results (NEW)
│   ├── results.md          # Original results
│   ├── backtest_real_data.py
│   └── strategy_optimized.py
├── obi_microstructure_strategy/
│   ├── DOCUMENTATION.md    # ✅ Full documentation (NEW)
│   ├── README.md
│   └── backtest.py
├── [other-strategies]/
│   ├── backtest/           # Simulation logic
│   ├── src/                # Core implementation
│   ├── research.md         # Theoretical foundation
│   └── results.md          # Performance report

polymarket_paper/
├── README.md               # ✅ Complete documentation (NEW)
├── paper_trader.py         # Paper trading engine
└── paper_runner.py         # Runner script

dashboard/
├── performance_dashboard.py    # ✅ Strategy metrics aggregator (NEW)
├── strategy_metrics.csv        # ✅ Exported metrics (NEW)
├── app.py                      # Web dashboard
├── app_enhanced.py
└── app_ws.py                   # WebSocket version
```

## Quick Start

### View Performance Dashboard
```bash
cd alpha-strategies
python3 dashboard/performance_dashboard.py
```

### Export Metrics to CSV
```bash
python3 dashboard/performance_dashboard.py --export metrics.csv
```

### View Strategy Details
```bash
python3 dashboard/performance_dashboard.py --detail "SOL RSI"
```

## Contributing

1. Discover a quantified edge or market inefficiency.
2. Implement backtest with realistic parameters (0.1% slippage, maker/taker fees).
3. Document theoretical foundation and results.
4. Submit PR for review and validation.

---
*Maintained by ATLAS Research & ALPHA HUNTER*
