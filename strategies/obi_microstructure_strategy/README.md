# OBI Microstructure Strategy

## Overview

Order Book Imbalance (OBI) microstructure strategy exploiting short-term order flow imbalances for scalping opportunities.

**Status**: ✅ Implemented with Backtest

---

## Strategy Logic

### Core Concept

Order Book Imbalance (OBI) measures the relative strength of bids vs asks:

```
OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
```

- **OBI > 0**: More bids than asks = buying pressure
- **OBI < 0**: More asks than bids = selling pressure
- **OBI ≈ 0**: Balanced order book

### Entry Signals

| Condition | Signal |
|-----------|--------|
| OBI > +0.3 | Long (strong buying pressure) |
| OBI < -0.3 | Short (strong selling pressure) |
| 2 consecutive signals | Confirmation required |

### Exit Conditions

| Trigger | Description |
|---------|-------------|
| OBI Reversion | OBI returns to neutral range (-0.1 to +0.1) |
| Time Stop | Maximum hold of 5 minutes |
| Stop Loss | -0.3% from entry |
| Take Profit | +0.5% from entry (1.67:1 R:R) |

---

## Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| OBI Threshold | ±0.30 | Entry signal threshold |
| Neutral Zone | ±0.10 | Exit when OBI in this range |
| Max Hold | 5 minutes | Time-based exit |
| Stop Loss | 0.30% | Tight risk control |
| Take Profit | 0.50% | Scalp target |
| Position Size | 20% | Per-trade allocation |
| Commission | 0.05% | Per side |

---

## Backtest Results

*Synthetic data, 1 week, 1-minute resolution*

| Metric | Value |
|--------|-------|
| Total Trades | 1,858 |
| Win Rate | 25.4% |
| Profit Factor | 0.22 |
| Total Return | -33.81% |
| Max Drawdown | 33.82% |
| Sharpe Ratio | -232.25 |
| Avg Trade Duration | 3.9 min |

### Analysis

⚠️ **Backtest shows negative returns on synthetic data.**

This is expected because:
1. Synthetic data may not capture true order book dynamics
2. OBI signals often lead to adverse selection (informed flow)
3. Requires L2 data quality that synthetic data doesn't replicate
4. Real-world implementation needs latency optimization

### Real-World Considerations

- **Latency Critical**: Requires colocation/sub-10ms execution
- **Adverse Selection**: Large imbalances often attract informed traders
- **Data Quality**: Need full L2 depth, not just top-of-book
- **Market Regime**: Works best in range-bound, liquid markets

---

## Implementation Notes

### Data Requirements

- Level 2 order book data
- Minimum 10 levels of depth
- Sub-second timestamps
- Bid/ask volume at each level

### Exchange Compatibility

| Exchange | L2 Availability | Latency |
|----------|----------------|---------|
| Binance | ✅ Full | ~50ms |
| Bybit | ✅ Full | ~30ms |
| OKX | ✅ Full | ~40ms |
| dYdX | ✅ Full | ~100ms |

### Risk Management

- Maximum 3 concurrent positions
- Daily loss limit: 2%
- Circuit breaker: Pause after 5 consecutive losses

---

## Files

```
obi_microstructure_strategy/
├── backtest.py         # Strategy implementation
├── requirements.txt    # Dependencies
└── results.json        # Backtest results
```

## Running the Backtest

```bash
cd obi_microstructure_strategy
pip install -r requirements.txt
python backtest.py
```

---

## References

- [Cont, Stoikov & Talreja (2010)](https://ssrn.com/abstract=1692219) - Order book dynamics
- [Zhang (2013)](https://ssrn.com/abstract=2262380) - High-frequency trading with microstructure

## Disclaimer

This strategy is for educational purposes. OBI-based strategies are highly sensitive to execution quality and market microstructure. Synthetic backtests may not reflect real-world performance.
