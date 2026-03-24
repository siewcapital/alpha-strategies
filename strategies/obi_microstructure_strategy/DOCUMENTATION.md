# OBI Microstructure Strategy - Complete Documentation

**Strategy Name:** Order Book Imbalance (OBI) Microstructure Scalping  
**Asset Class:** BTC Perpetual Futures  
**Timeframe:** 1-Minute  
**Holding Period:** 1-5 minutes  
**Status:** Architecture Complete, Pending L2 Data Validation  
**Last Updated:** March 20, 2026

---

## 📖 Table of Contents

1. [Overview](#overview)
2. [Theoretical Foundation](#theoretical-foundation)
3. [Strategy Logic](#strategy-logic)
4. [Implementation Details](#implementation-details)
5. [Backtest Results](#backtest-results)
6. [Risk Management](#risk-management)
7. [Real-World Considerations](#real-world-considerations)
8. [Performance Metrics](#performance-metrics)
9. [Deployment Checklist](#deployment-checklist)
10. [References](#references)

---

## Overview

The Order Book Imbalance (OBI) strategy exploits short-term order flow imbalances to scalp micro-movements in the BTC perpetual futures market. By measuring the relative strength of bids versus asks in the limit order book, the strategy identifies moments of buying or selling pressure before they materialize in price movement.

### Key Characteristics

| Attribute | Value |
|-----------|-------|
| **Style** | Microstructure Scalping |
| **Directionality** | Market Neutral (Long/Short) |
| **Holding Time** | 1-5 minutes |
| **Trade Frequency** | High (100+ per day) |
| **Win Rate Target** | >55% with 1.5:1 R:R |
| **Latency Requirement** | <50ms (ideally <10ms) |
| **Data Requirements** | Level 2 Order Book |

---

## Theoretical Foundation

### Order Book Imbalance (OBI)

The core metric is calculated as:

```
OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
```

Where:
- **BidVolume**: Cumulative volume at bid levels (top N levels)
- **AskVolume**: Cumulative volume at ask levels (top N levels)
- **Range**: -1.0 (all asks) to +1.0 (all bids)

### Academic Basis

This strategy is grounded in market microstructure theory:

1. **Cont, Stoikov & Talreja (2010)** - Order book dynamics modeling
   - Order book imbalance predicts short-term price direction
   - Imbalance has predictive power on timescales of seconds to minutes

2. **Zhang (2013)** - High-frequency trading with microstructure
   - OBI signals have half-life of 30-60 seconds
   - Requires rapid execution to capture edge

3. **Avellaneda & Stoikov (2008)** - Market making models
   - Order flow toxicity impacts microstructure signals
   - Informed flow can make OBI signals adverse

### Why It Should Work

1. **Order Flow Precedes Price**: Large imbalances indicate institutional accumulation/distribution
2. **Short-Term Momentum**: Imbalances create temporary price pressure
3. **Mean Reversion**: Imbalances tend to normalize quickly (seconds to minutes)

### Why It Might Fail

1. **Adverse Selection**: Large imbalances often attract informed traders
2. **Latency Arbitrage**: Slower traders get picked off by faster ones
3. **Market Regime**: Works best in liquid, range-bound markets

---

## Strategy Logic

### Entry Signals

#### Long Entry
```
IF OBI > +0.30 AND OBI(t-1) > +0.30 (2 consecutive readings)
THEN Enter Long
```

#### Short Entry
```
IF OBI < -0.30 AND OBI(t-1) < -0.30 (2 consecutive readings)
THEN Enter Short
```

**Rationale**: Single-bar spikes can be noise. Two consecutive readings confirm sustained pressure.

### Exit Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| OBI Reversion | Signal | OBI returns to neutral range (-0.1 to +0.1) |
| Time Stop | Risk | Maximum hold of 5 minutes |
| Stop Loss | Risk | -0.3% from entry price |
| Take Profit | Target | +0.5% from entry price (1.67:1 R:R) |

**Exit Priority**: 
1. Stop loss (hard limit)
2. Take profit (target reached)
3. Time stop (max duration)
4. Signal reversion (soft exit)

### Position Sizing

```python
position_size = min(
    account_balance * 0.20,  # 20% max per trade
    max_position_dollar_value  # Exchange limit
)
```

---

## Implementation Details

### Data Requirements

| Requirement | Specification | Why It Matters |
|-------------|---------------|----------------|
| Level 2 Data | Top 10+ levels | Surface OBI only uses top level |
| Update Frequency | <100ms | OBI changes rapidly |
| Timestamp Precision | Microsecond | Sequence validation |
| Latency | <50ms to exchange | Execution speed critical |

### OBI Calculation

```python
def calculate_obi(order_book: OrderBook, levels: int = 5) -> float:
    """
    Calculate Order Book Imbalance.
    
    Args:
        order_book: Current L2 order book state
        levels: Number of price levels to include (default 5)
    
    Returns:
        OBI value between -1.0 and +1.0
    """
    bid_volume = sum(level['volume'] for level in order_book.bids[:levels])
    ask_volume = sum(level['volume'] for level in order_book.asks[:levels])
    
    total_volume = bid_volume + ask_volume
    if total_volume == 0:
        return 0.0
    
    obi = (bid_volume - ask_volume) / total_volume
    return obi
```

### Signal Generation

```python
def generate_signal(obi_current: float, obi_previous: float) -> Optional[Signal]:
    """Generate trading signal based on OBI."""
    
    # Long signal: Strong buying pressure sustained
    if obi_current > 0.30 and obi_previous > 0.30:
        return Signal(direction=LONG, confidence=obi_current)
    
    # Short signal: Strong selling pressure sustained
    if obi_current < -0.30 and obi_previous < -0.30:
        return Signal(direction=SHORT, confidence=abs(obi_current))
    
    return None
```

### Exchange Compatibility

| Exchange | L2 WebSocket | Latency (ms) | Recommendation |
|----------|--------------|--------------|----------------|
| **Bybit** | ✅ Full | ~30 | **Preferred** |
| **Binance** | ✅ Full | ~50 | Good alternative |
| **OKX** | ✅ Full | ~40 | Good alternative |
| **dYdX** | ✅ Full | ~100 | Latency concern |
| **Hyperliquid** | ✅ Full | ~20 | Emerging choice |

---

## Backtest Results

### Synthetic Data Results

*Warning: Synthetic data may not capture true microstructure dynamics*

| Metric | Value | Assessment |
|--------|-------|------------|
| Total Trades | 1,858 | High frequency as expected |
| Win Rate | 25.4% | ❌ Below target (need >50%) |
| Profit Factor | 0.22 | ❌ Losing strategy |
| Total Return | -33.81% | ❌ Significant losses |
| Max Drawdown | 33.82% | ❌ Unacceptable |
| Sharpe Ratio | -232.25 | ❌ Terrible risk-adjusted return |
| Avg Trade Duration | 3.9 min | Within target (1-5 min) |
| Commission Paid | -$1,858 | 0.05% per side |

### Analysis of Synthetic Results

**Why the strategy failed on synthetic data:**

1. **No Real Order Book Dynamics**: Synthetic data uses random walk, not real order flow
2. **Missing Adverse Selection**: Synthetic data doesn't model informed flow
3. **No Latency**: Synthetic execution is instant; real world has slippage
4. **Simplified Microstructure**: Real OBI signals decay faster than synthetic

**What this tells us:**
- Synthetic backtests are **NOT reliable** for microstructure strategies
- Real L2 data testing is **MANDATORY**
- Paper trading on real data is the next step

### Real Data Requirements for Valid Backtest

To properly validate this strategy, we need:

1. **Historical L2 Data**: Minimum 3 months of tick-by-tick order book
2. **Trade Reconstruction**: Match our hypothetical fills against actual trades
3. **Latency Simulation**: Model execution delay (10-100ms)
4. **Slippage Model**: Account for market impact

---

## Risk Management

### Position Limits

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max Position Size | 20% of account | Concentration risk |
| Max Concurrent Trades | 3 | Correlation risk |
| Daily Loss Limit | 2% of account | Circuit breaker |
| Consecutive Losses | 5 | Pause trading |

### Stop Loss Strategy

```python
# Hard stop at -0.3%
if unrealized_pnl < -0.003 * position_value:
    close_position(market_order=True)

# Trailing stop after +0.3% profit
if unrealized_pnl > 0.003 * position_value:
    trailing_stop = entry_price * 1.001  # Lock in 0.1%
```

### Risk Controls

1. **Pre-Trade Checks**
   - Sufficient balance
   - Within daily loss limit
   - Not during high-impact news
   - Exchange connectivity confirmed

2. **In-Trade Monitoring**
   - Position P&L tracked every 100ms
   - Stop loss orders held server-side
   - Connection loss = immediate position close

3. **Post-Trade Analysis**
   - All trades logged with millisecond timestamps
   - Slippage vs expected calculated
   - Adverse selection detected

---

## Real-World Considerations

### Latency Optimization

| Component | Target | Implementation |
|-----------|--------|----------------|
| Data Feed | <10ms | Colocated server |
| Signal Generation | <1ms | Optimized C++/Rust |
| Order Submission | <5ms | WebSocket direct |
| Total Latency | <20ms | End-to-end |

### Colocation Options

| Provider | Location | Cost/Month | Latency |
|----------|----------|------------|---------|
| AWS Tokyo | Japan | ~$500 | ~30ms to Bybit |
| AWS Singapore | Singapore | ~$500 | ~20ms to Bybit |
| Equinix TY2 | Tokyo | ~$2000 | ~5ms to Bybit |

### Adverse Selection Detection

Signs you're being picked off:
1. OBI signal triggers → You enter → Price immediately reverses
2. Win rate <40% despite positive OBI readings
3. Average slippage >0.05%
4. Frequent "fake" imbalances that vanish after entry

**Mitigation:**
- Require larger OBI threshold (>0.40)
- Add confirmation from trade flow (not just quotes)
- Implement "fade" logic if adverse selection detected

---

## Performance Metrics

### Target Metrics

| Metric | Target | Minimum |
|--------|--------|---------|
| Win Rate | >55% | >50% |
| Profit Factor | >1.3 | >1.1 |
| Sharpe Ratio | >1.5 | >0.5 |
| Max Drawdown | <10% | <20% |
| Avg Trade Duration | 2-4 min | <5 min |
| Daily Trades | 50-200 | >20 |

### Current Status

| Metric | Synthetic | Real Data | Status |
|--------|-----------|-----------|--------|
| Win Rate | 25.4% | TBD | 🚧 Pending |
| Profit Factor | 0.22 | TBD | 🚧 Pending |
| Sharpe Ratio | -232.25 | TBD | 🚧 Pending |
| Max Drawdown | 33.82% | TBD | 🚧 Pending |

---

## Deployment Checklist

### Phase 1: Data Acquisition
- [ ] Subscribe to historical L2 data (3+ months)
- [ ] Validate data quality (no gaps, correct timestamps)
- [ ] Build order book reconstruction engine
- [ ] Test against known market events

### Phase 2: Backtest with Real Data
- [ ] Run strategy on historical L2 data
- [ ] Model realistic latency (20-50ms)
- [ ] Include slippage estimates (0.02-0.05%)
- [ ] Achieve target metrics (PF > 1.3, Sharpe > 1.0)

### Phase 3: Paper Trading
- [ ] Connect to exchange testnet
- [ ] Run for minimum 2 weeks
- [ ] Compare fills to expected
- [ ] Measure actual latency and slippage

### Phase 4: Live Trading (Small Size)
- [ ] Start with 10% of intended size
- [ ] Monitor for 1 month
- [ ] Gradually scale up if metrics hold
- [ ] Daily P&L review

### Phase 5: Full Deployment
- [ ] 100% intended position size
- [ ] Automated risk monitoring
- [ ] Weekly strategy review
- [ ] Quarterly re-optimization

---

## References

### Academic Papers

1. **Cont, R., Stoikov, S., & Talreja, R. (2010)**  
   "A Stochastic Model for Order Book Dynamics"  
   https://ssrn.com/abstract=1692219

2. **Zhang, S. (2013)**  
   "Need for Speed: An Empirical Analysis of Hard and Soft Information in a High Frequency World"  
   https://ssrn.com/abstract=2262380

3. **Avellaneda, M., & Stoikov, S. (2008)**  
   "High-frequency trading in a limit order book"  
   Quantitative Finance, Vol. 8, No. 3

4. **Biais, B., Hillion, P., & Spatt, C. (1995)**  
   "An Empirical Analysis of the Limit Order Book"  
   Journal of Finance, Vol. 50, No. 5

### Industry Resources

- Binance API Documentation: https://binance-docs.github.io/
- Bybit API Documentation: https://bybit-exchange.github.io/
- Crypto Market Microstructure (Blog): https://eliquant.substack.com/

---

## Disclaimer

⚠️ **WARNING**: This strategy is HIGH RISK and requires:
- Professional-grade infrastructure
- Sub-50ms latency
- Sophisticated risk management
- Continuous monitoring

**Synthetic backtests are NOT predictive** for microstructure strategies. Real L2 data testing is mandatory before deployment.

**Past performance does not guarantee future results.**

---

*Documentation by ATLAS Research Division*  
*Siew's Capital | Alpha Strategies*  
*Last Updated: March 20, 2026*
