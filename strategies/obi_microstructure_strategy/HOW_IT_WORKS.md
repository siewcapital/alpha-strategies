# How OBI Microstructure Strategy Works

## Overview

The **Order Book Imbalance (OBI) Microstructure Strategy** is a high-frequency trading strategy that exploits short-term predictive power of order book imbalances to forecast near-term price movements.

---

## Core Concept: Why Order Book Imbalance Predicts Price

### The Basic Idea

When there are significantly more buy orders (bids) than sell orders (asks) at the top of the order book, this creates **buying pressure** that tends to push prices up. Conversely, when asks dominate, **selling pressure** pushes prices down.

```
Order Book Snapshot:
┌─────────────────────────────────────┐
│  Asks (Sell Orders)                 │
│  $100.50 │ 500 units                │
│  $100.40 │ 300 units                │
│  ───────────────────────            │
│  Bids (Buy Orders)                  │
│  $100.30 │ 800 units  ◄── More bids │
│  $100.20 │ 400 units                │
└─────────────────────────────────────┘
         ↑
   Imbalance favors buyers
   → Price likely to rise
```

### The Math Behind OBI

**Level 1 OBI Formula** (using best bid/ask only):

```
OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
```

**Example Calculation:**
- Best Bid Volume: 800 units
- Best Ask Volume: 300 units
- OBI = (800 - 300) / (800 + 300) = 500 / 1100 = **+0.45**

**Interpretation:**
| OBI Value | Meaning | Signal |
|-----------|---------|--------|
| +1.0 | All volume on bid side | Strong buy |
| +0.3 to +0.9 | More bids than asks | Moderate buy |
| 0 | Balanced | Neutral |
| -0.3 to -0.9 | More asks than bids | Moderate sell |
| -1.0 | All volume on ask side | Strong sell |

---

## Strategy Mechanics

### Step 1: Calculate Order Book Imbalance

The strategy continuously monitors the order book and calculates OBI at multiple levels:

```python
# Level 1 (best bid/ask)
obi_l1 = (best_bid_vol - best_ask_vol) / (best_bid_vol + best_ask_vol)

# Depth-weighted (levels 1-3)
obi_depth = 0.5*obi_l1 + 0.3*obi_l2 + 0.2*obi_l3
```

### Step 2: Calculate Order Flow Imbalance (OFI)

OBI is a **static snapshot**. To add a dynamic component, we calculate OFI which measures recent changes:

```
OFI tracks how the order book changes over time:
- Did the best bid price increase? → Bullish flow
- Did the best ask price decrease? → Bearish flow
- Did bid volume increase at the same price? → Bullish
- Did ask volume increase at the same price? → Bearish
```

### Step 3: Apply Filters

Raw OBI signals are noisy. The strategy applies multiple filters:

| Filter | Purpose | Threshold |
|--------|---------|-----------|
| **Persistence** | Avoid fleeting/spoofed orders | OBI > 0.3 for 3+ ticks |
| **Spread** | Ensure executable prices | Spread < 5 bps |
| **Volume** | Confirm active market | Volume > average |
| **Trend** | Avoid counter-trend trades | Price vs micro-EMA |

### Step 4: Generate Entry Signals

**Long Entry (Buy) Conditions:**
1. OBI > +0.3 (more bids than asks)
2. OFI momentum is positive (buying pressure increasing)
3. Imbalance persists for > 2 seconds
4. Price is above micro-trend EMA (uptrend)
5. Spread < 5 basis points

**Short Entry (Sell) Conditions:**
1. OBI < -0.3 (more asks than bids)
2. OFI momentum is negative
3. Imbalance persists for > 2 seconds
4. Price is below micro-trend EMA (downtrend)
5. Spread < 5 basis points

### Step 5: Execute and Manage Risk

**Position Sizing:**
- Base: 1% of portfolio per trade
- Increase to 1.5% when |OBI| > 0.6 (strong signal)

**Exit Triggers:**
| Trigger | Condition | Rationale |
|---------|-----------|-----------|
| Time Stop | 30 seconds max | Edge decays rapidly |
| OBI Reversal | OBI crosses zero | Imbalance flipped |
| Take Profit | +0.05% (5 bps) | Scalp target |
| Stop Loss | -0.03% (3 bps) | Tight risk control |

---

## Why This Works (Market Microstructure)

### 1. Inventory Control by Market Makers

Market makers provide liquidity by resting orders on both sides. When they face one-sided flow:
- Heavy buying → They accumulate short inventory
- To hedge, they raise ask prices
- This pushes the mid-price higher

### 2. Latent Demand Revealed

The order book represents **committed but unexecuted** interest. Large resting orders indicate:
- Institutional accumulation
- Support/resistance levels
- Future execution pressure

### 3. Execution Cascades

When one side of the book is thinner:
- Large market orders consume the thin side quickly
- This forces price to move to the next level
- The imbalance accelerates the move

### 4. Information Content

Persistent imbalances may signal:
- Informed trading (insider knowledge)
- Large pending orders (iceberg orders)
- Market sentiment shifts

---

## Edge Decay: Why Speed Matters

OBI predictive power **decays rapidly** with time:

| Time Horizon | Accuracy | Usable? |
|--------------|----------|---------|
| 1-5 seconds | 65-75% | ✅ Yes |
| 10-30 seconds | 55-65% | ⚠️ Marginal |
| 60+ seconds | ~52% | ❌ No edge |

**Key Insight:** This is a **high-frequency** strategy. The edge exists only at very short time horizons.

---

## Real-World Challenges

### 1. Adverse Selection

Large imbalances sometimes attract **informed traders** who:
- Know something you don't
- Are betting against the imbalance
- Cause price to move opposite to OBI signal

### 2. Spoofing and Quote Stuffing

Traders may place fake orders to manipulate OBI:
- Place large bid to signal buying pressure
- Cancel before execution
- Trick others into buying

**Defense:** The persistence filter (requires 3+ ticks of imbalance) helps filter spoofing.

### 3. Latency Sensitivity

To capture the OBI edge:
- Need <50ms from signal to execution
- WebSocket feeds (not REST polling)
- Co-location beneficial but not required

### 4. Data Quality

Requires:
- Level 2 order book (5-10 levels minimum)
- Sub-second timestamps
- Full market depth (not just top-of-book)

---

## Strategy Classification

| Attribute | Value |
|-----------|-------|
| **Style** | High-Frequency Momentum |
| **Frequency** | 50-100+ trades/day |
| **Holding Period** | 10-60 seconds |
| **Data Requirements** | L2 order book, sub-100ms |
| **Infrastructure** | Low latency, WebSocket |
| **Capacity** | Low ($1-5M) |
| **Complexity** | High |

---

## Key Takeaways

1. **OBI predicts short-term price direction** by measuring supply/demand asymmetry in the order book

2. **Speed is critical** - edge decays within seconds

3. **Filters are essential** - raw OBI is too noisy; need persistence, spread, and volume filters

4. **Risk management is tight** - small stops, time-based exits, and position limits

5. **Requires quality data** - L2 order book with sufficient depth and low latency

---

## References

- Cont, R., Kukanov, A., & Stoikov, S. (2014). "The Price Impact of Order Book Events."
- Cartea, Á., Jaimungal, S., & Ricci, R. (2014). "Buy Low, Sell High: A High Frequency Trading Perspective."
- Gould, M.D., et al. (2013). "Limit order books." *Quantitative Finance*.
