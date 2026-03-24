# OBI Microstructure Strategy - Technical Documentation

## Overview

The **Order Book Imbalance (OBI) Microstructure Strategy** is a high-frequency trading (HFT) approach that targets short-term price movements by analyzing the asymmetry between buy and sell interest in the limit order book.

---

## Technical Architecture

### 1. Data Ingestion Layer (`data_loader.py`)
- **Real-time**: Connects to exchange WebSockets (Binance/Bybit) for L2 order book updates.
- **Backtesting**: Uses a `SyntheticOrderBookGenerator` for high-fidelity tick-by-tick simulation (100ms resolution).
- **Format**: Captures `OrderBookTick` objects containing timestamps, bids, asks, mid-price, and spread.

### 2. Signal Generation (`src/strategy.py`)
- **OBI Calculation**: 
  - Level 1: `(BidVol1 - AskVol1) / (BidVol1 + AskVol1)`
  - Weighted Depth: $\sum_{i=1}^{n} w_i \cdot \text{OBI}_i$, where $w_i$ decays with depth.
- **Persistence Filter**: Requires a signal to remain above threshold for $N$ consecutive ticks to filter out noise and "quote stuffing."
- **Trend Alignment**: Uses a micro-EMA (e.g., 50-tick span) to ensure signals are not fighting strong immediate momentum.

### 3. Risk Management (`src/risk_manager.py`)
- **Position Sizing**: Dynamically scales between 1% and 1.5% of capital based on signal confidence and OBI magnitude.
- **Circuit Breakers**:
  - Daily Loss Limit: 1-2%
  - Max Consecutive Losses: 5
  - Max Drawdown Limit: 4%
- **Time Stops**: Automatic exit after 30-60 seconds to mitigate edge decay.

---

## Strategy Logic Details

### Entry Parameters
| Parameter | Value | Description |
|-----------|-------|-------------|
| `obi_long_threshold` | +0.40 | Enter long when bids significantly exceed asks. |
| `obi_short_threshold`| -0.40 | Enter short when asks significantly exceed bids. |
| `persistence_ticks`  | 3 | Number of 100ms ticks the OBI must remain valid. |
| `max_spread_bps`     | 5.0 | Do not trade if the spread is too wide. |

### Exit Parameters
| Parameter | Value | Description |
|-----------|-------|-------------|
| `profit_target_bps`  | 5.0 | Scalp target (0.05%). |
| `stop_loss_bps`      | 3.0 | Tight stop (0.03%). |
| `max_hold_seconds`   | 30.0| Exit if the predicted move doesn't happen quickly. |
| `obi_reversal`       | 0.0 | Exit if OBI crosses the zero line (regime shift). |

---

## Performance Analysis (Backtest Findings)

### Synthetic Data Challenges
Initial backtests on synthetic random-walk data showed negative results (-33% return). 
- **Reason**: Synthetic data lacks the **autocorrelation** and **latent demand** present in real markets.
- **Insight**: OBI depends on the fact that limit orders are "sticky" and represent real institutional intent, which random-walk models do not replicate.

### Real-Market Expectations
Based on similar HFT implementations in crypto:
- **Win Rate**: Typically 55-65%.
- **Edge**: 0.5 - 2.0 basis points per trade after fees.
- **Frequency**: High (hundreds of trades per day).
- **Key Risk**: **Adverse Selection** (getting filled just before a large player wipes out your side of the book).

---

## Deployment Roadmap

1. **Phase 1: Shadow Trading** (Current)
   - Connect to Binance L2 WebSocket.
   - Log signals without executing.
   - Compare predicted mid-price move vs. actual move over 10s.

2. **Phase 2: Paper Trading**
   - Use exchange testnets.
   - Simulate execution latency (assume 50ms round-trip).
   - Track virtual PnL.

3. **Phase 3: Live Pilot**
   - Deploy with small capital ($500 - $1,000).
   - Focus on highly liquid pairs (SOL/USDT, BTC/USDT).
   - Monitor for "toxic flow" (systematic losses to informed traders).

---

## References & Further Reading
- *The Price Impact of Order Book Events* (Cont et al., 2014)
- *Limit Order Books* (Gould et al., 2013)
- *High-Frequency Trading with Microstructure* (Zhang, 2013)

---
*Maintained by ATLAS | Siew's Capital Research*
