# Polymarket 5-Minute BTC Signal Arbitrage

**Strategy Type:** Short-duration binary options trading on Polymarket
**Market:** Polymarket BTC Up/Down 5-minute binary options
**Edge Source:** Multi-timeframe momentum + trend filtering + LLM-augmented filtering
**Research Source:** Jung-Hua Liu, "AI-Augmented Arbitrage in Short-Duration Prediction Markets" (March 2026)

---

## Executive Summary

This strategy trades Polymarket's 5-minute BTC binary options, exploiting mispricing between BTC spot price movements and Polymarket token prices. The core innovation is the **v3 signal engine** with 10-minute trend filtering that eliminated the directional bias causing 80% of v2 trades to bet UP during DOWN-trending markets.

**Key Findings from Live Trading:**
- v2 engine: 522× paper returns → **-49.5% live** (gap from slippage/fees)
- v3 engine: **7× better capital preservation** through trend filtering
- Win rates: **25-27%** (below 53% breakeven - random walk confirmed)
- Fee-adjusted minimum edge: **~3%** required for profitability

---

## Architecture

```
polymarket_5min_signal_arb/
├── README.md                    # This file
├── research.md                  # Full strategy research
├── config/
│   └── params.yaml             # Tunable parameters
├── src/
│   ├── __init__.py
│   ├── strategy.py             # Main orchestrator (600+ lines)
│   ├── signal_engine.py        # Multi-timeframe momentum signals (450+ lines)
│   ├── position_sizer.py       # Fractional Kelly sizing (350+ lines)
│   └── risk_manager.py         # Circuit breakers, limits (400+ lines)
├── backtest/
│   └── backtest.py             # Historical simulation engine
├── tests/
│   └── test_signal_engine.py   # Unit + integration tests
└── requirements.txt
```

---

## Signal Generation

### Composite Momentum Score (v3 Weights)

```
slope_tf = β₁ / mean(price) for tf ∈ {30s, 60s, 120s, 240s}
weighted_slope = Σ(slope_tf × weight_tf)
direction = UP if weighted_slope > 0, else DOWN
```

**v3 Weights (favor longer lookbacks to reduce noise):**
| Timeframe | Weight |
|-----------|--------|
| 30s | 0.20 |
| 60s | 0.30 |
| 120s | 0.35 |
| 240s | 0.15 |

### 10-Minute Trend Filter

Hard rule: **DISLOCATION signals opposing 10-minute trend are blocked unconditionally.**

```python
def get_medium_term_trend(self):
    ticks = get_prices_in_window(600)
    slope = compute_slope(ticks)
    return ("UP" if slope > 0 else "DOWN"), abs(slope)
```

### Signal Types

| Signal | Trigger | Min Edge |
|--------|---------|----------|
| **DISLOCATION** | BTC moved >0.05%, token lagging, trend agrees | 2% fee-adj |
| **DIRECTIONAL** | Final 30s, confidence ≥0.45, BTC confirms | 3% |
| **MAKER** | Earn 20% maker rebate, confidence ≥0.45 | N/A |

### Fair Probability Estimation

```
fair_prob = 0.5 + (|Δ_btc| / time_decay) × 5.0, capped at 0.80
```

---

## Position Sizing

### Fractional Kelly Criterion

```
edge = confidence - token_price
kelly = edge / (1 - token_price)
size = budget × min(kelly, 0.25) × size_factor
```

- **Quarter-Kelly cap** (max 25% of full Kelly)
- **Size factor** adjusted by conviction and loss streak
- **Minimum edge:** 3% (covers Polymarket fees)

### Risk Rules

1. No duplicate bets on same 5-minute window
2. Reject signals opposing 15-minute trend (unless BTC move >0.10%)
3. After 3+ consecutive losses, require edge >5%
4. BTC move <0.03% with >90s remaining = noise → reject
5. Don't bet against side priced >60% without strong evidence
6. Cash <30% starting → only high-conviction trades

---

## Backtest Results

### Regime Analysis

| Regime | Return | Sharpe | Max DD | Win Rate | Trades |
|--------|--------|--------|--------|----------|--------|
| Bull Trend | TBD | TBD | TBD | TBD | TBD |
| Bear Trend | TBD | TBD | TBD | TBD | TBD |
| Ranging | TBD | TBD | TBD | TBD | TBD |
| High Vol | TBD | TBD | TBD | TBD | TBD |
| Low Vol | TBD | TBD | TBD | TBD | TBD |

### Live Trading Results (From Paper)

**Session 1 (v2 engine):**
- Starting: $17 USDC.e
- Duration: ~2 hours
- Win Rate: 27% (4W/11L)
- ROI: **-49.5%**
- Problem: 80% bet UP during DOWN-trending market

**Session 2 (v3 engine):**
- Starting: $31.19 USDC.e
- Duration: 1 hour
- Win Rate: 25%
- Loss: $4.18 (**13% of capital**)
- Improvement: **7× better** vs v2

---

## Key Insights

1. **5-minute binaries ≈ random walk** - Win rates 25-27% vs 53% breakeven confirm EMH at ultra-short horizons

2. **Paper-to-live gap is massive** - 522× paper vs -49.5% live due to:
   - Slippage: 2-4 cents per token (~4% worse)
   - Fees: 1.56% at $0.50 entry
   - Thin order books in DeFi

3. **Trend filtering is critical** - The v3 trend filter was the single biggest improvement, reducing capital loss by 7×

4. **LLM filtering adds marginal value** - Cannot compensate for fundamentally biased signals; mechanical rules (trend filter) more valuable

5. **Capital preservation > returns** - With negative expected edge, survival is the game

---

## Installation

```bash
cd strategies/polymarket_5min_signal_arb
pip install -r requirements.txt
```

## Running Backtest

```bash
cd backtest
python backtest.py
```

## Running Tests

```bash
pytest tests/ -v
```

---

## Risks and Limitations

1. **Random Walk Risk:** 5-min binaries appear efficiently priced
2. **Execution Risk:** Slippage 2-4 cents per token in live trading
3. **Fee Drag:** 1.56% fee requires ~3% edge just to break even
4. **Oracle Risk:** Resolution depends on Polymarket's infrastructure
5. **Regulatory Risk:** Prediction markets operate in grey area
6. **Limited Sample:** Only 19 live trades in paper study

---

## References

1. Kelly Jr., J.L. "A new interpretation of information rate" (1956)
2. Fama, E.F. "Efficient capital markets" (1970)
3. Almgren, R. & Chriss, N. "Optimal execution of portfolio transactions" (2000)
4. Jegadeesh, N. & Titman, S. "Returns to buying winners and selling losers" (1993)
5. Bailey et al. "Pseudo-mathematics and financial charlatanism" (2014)
6. Liu, J.H. "AI-Augmented Arbitrage in Short-Duration Prediction Markets" (March 2026)

---

**Author:** ATLAS Research - Siew's Capital
**Date:** March 26, 2026
**Status:** Research Complete - Backtesting In Progress
