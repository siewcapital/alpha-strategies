# Alpha Strategies

A systematic collection of quantitative trading strategies, arbitrage opportunities, and prediction market edges.

## Strategies

| Strategy | Asset(s) | Status | Performance (Backtest) |
|----------|----------|--------|------------------------|
| **[SOL RSI Mean Reversion](strategies/sol-rsi-mean-reversion/)** | SOL/USDT | ✅ TESTED | Sharpe: 0.83 |
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
