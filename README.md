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

## Strategies

| Strategy | Asset(s) | Status | Performance (Backtest) |
|----------|----------|--------|------------------------|
| **[SOL RSI Mean Reversion](strategies/sol-rsi-mean-reversion/)** | SOL/USDT | ✅ **OPTIMIZED** | **Sharpe: 3.32** (Phase 5) |
| **[Polymarket HFT](strategies/polymarket-hft/)** | BTC Binary | ✅ VALIDATED | Median Return: 2,645% |
| **[Hoffman IRB](strategies/hoffman-irb/)** | BTC, ETH, SOL | ✅ TESTED | Sharpe: 1.34-1.94 (ETH/SOL) |
| **[OBI Microstructure](strategies/obi_microstructure_strategy/)** | BTC Perp | ✅ READY | Architecture complete |
| **[Options Dispersion](strategies/options-dispersion/)** | Crypto Options | ✅ READY | Phase 8 complete |
| **[Cross-Exchange Funding Arb](strategies/cross_exchange_funding_arb/)** | Multiple | ⚠️ UNPROFITABLE | High fee sensitivity |
| **[VRP Harvester](strategies/vrp_harvester/)** | BTC, ETH | ⚠️ INCONCLUSIVE | Insufficient data |
| **[Polymarket Arbitrage](strategies/polymarket-arbitrage/)** | Multiple | 🚧 RESEARCH | In progress |

## Repository Structure

```
strategies/
└── [strategy-name]/
    ├── backtest/         # Simulation logic
    ├── src/              # Core implementation
    ├── config/           # Parameters & assets
    ├── research.md       # Theoretical foundation
    ├── results.md        # Performance report
    └── README.md         # Usage documentation
```

## Contributing

1. Discover a quantified edge or market inefficiency.
2. Implement backtest with realistic parameters (0.1% slippage, maker/taker fees).
3. Document theoretical foundation and results.
4. Submit PR for review and validation.

---
*Maintained by ATLAS Research & ALPHA HUNTER*
