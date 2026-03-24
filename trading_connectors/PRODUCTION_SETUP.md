# Funding Arbitrage - Production Setup Guide

This guide describes how to configure the Cross-Exchange Funding Arbitrage strategy for live production trading.

## 1. Production Credentials

Funding Arbitrage requires API keys for each exchange you intend to trade on. Create a `.env` file in the project root with the following format:

```bash
# Binance Production
BINANCE_API_KEY=your_binance_key
BINANCE_API_SECRET=your_binance_secret

# Bybit Production
BYBIT_API_KEY=your_bybit_key
BYBIT_API_SECRET=your_bybit_secret

# OKX Production (Requires Passphrase)
OKX_API_KEY=your_okx_key
OKX_API_SECRET=your_okx_secret
OKX_PASSPHRASE=your_okx_passphrase

# Strategy Configuration
MIN_ARBITRAGE_SPREAD=0.0002  # 2 bps
MAX_POSITION_SIZE_USD=1000.0
```

## 2. Transitioning to Live

The `LiveFundingArbitrageRunner` supports a `--live` flag to switch from testnet to production.

### Verification Step
Run the production readiness script before launching:
```bash
python trading_connectors/prod_verify.py --exchanges binance bybit
```

### Launching
```bash
# Run with --live to enable real trading
python trading_connectors/live_runner.py --live --exchanges binance bybit --symbols BTCUSDT ETHUSDT
```

## 3. Fee Sensitivity Warning (ATLAS Finding)

Per ATLAS's research, Funding Arbitrage is highly sensitive to taker fees. 
**Recommended Production Settings:**
- Only trade if the spread is > 2.5 bps.
- Use exchanges where you have fee tier discounts (VIP levels).
- Monitor slippage on entry/exit closely via the dashboard.

## 4. Production Risk Management

- **Total Exposure**: Cap total exposure across all arbitrage legs.
- **Auto-Deleveraging (ADL)**: Be aware of ADL risk on one leg of the arbitrage.
- **Withdrawal Readiness**: Keep buffers of collateral to prevent liquidations during sharp price moves.

---
*Prepared by FORGE | Siew's Capital Engineering*
