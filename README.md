# Alpha Strategies

A collection of quantitative trading strategies, arbitrage opportunities, and prediction market edges discovered through systematic research.

## Strategies

### [Polymarket HFT](./strategies/polymarket-hft/)
**Status**: ✅ Tested & Validated

High-frequency arbitrage on Polymarket's 5-minute BTC prediction markets.
- **Source**: [Twitter/X Analysis](https://x.com/qkl2058/status/2032673461747986556)
- **Reported Return**: 8,500% (85x) in 1 month
- **Backtest Result**: 2,645% median return
- **Market**: BTC 5-Minute Up/Down ($37M volume)
- **Edge**: 0.3% per trade at 273 trades/hour

**Key Findings**:
- Mathematically validated: High-frequency + small edge = exponential returns
- Requires limit orders only (no market orders)
- Total costs: ~$4.60/month
- 196,560 trades/month opportunity

## Repository Structure

```
strategies/
└── [strategy-name]/
    ├── backtest.py       # Strategy implementation
    ├── requirements.txt  # Dependencies
    └── results.md        # Analysis & findings
```

## Contributing

1. Find an edge/arbitrage/strategy
2. Implement backtest with realistic parameters
3. Document sources and validate results
4. Submit PR with findings

## Disclaimer

These strategies are for educational and research purposes only. Past performance does not guarantee future results. Always do your own research and understand the risks before deploying capital.

## License

MIT
