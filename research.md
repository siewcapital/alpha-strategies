# Strategy Research: Polymarket 5-Minute BTC Signal Arbitrage

## Source Analysis
- **Primary Source:** "AI-Augmented Arbitrage in Short-Duration Prediction Markets: Live Trading Analysis of Polymarket's 5-Minute Bitcoin Binary Options" by Jung-Hua Liu
- **Author:** Jung-Hua Liu (@gwrx2005), researcher and practitioner
- **Date Published:** March 18, 2026
- **Your Analysis Date:** March 26, 2026
- **Source URL:** https://medium.com/@gwrx2005/ai-augmented-arbitrage-in-short-duration-prediction-markets-live-trading-analysis-of-polymarkets-8ce1b8c5f362

## Core Strategy Logic

### Overview
This strategy trades Polymarket's 5-minute BTC Up/Down binary options - contracts that resolve to $1.00 (correct) or $0.00 (incorrect) based on whether BTC/USD moves up or down within each 5-minute window. The edge comes from exploiting mispricing between BTC spot price movements and Polymarket token prices.

### Why It Should Work (Edge Analysis)

1. **Directional Lag**: When BTC price moves significantly within a 5-minute window, the Polymarket token price adjusts with a lag. Our DISLOCATION signal exploits this lag by comparing the observed BTC move to the current token price.

2. **Fee-Adjusted Edge Threshold**: Polymarket charges ~1.56% fee at $0.50 entry. Minimum edge required: ~3%. The strategy only trades when edge exceeds this threshold.

3. **Composite Momentum**: Multi-timeframe momentum analysis captures both short-term reversals and medium-term trends, filtering noise from directional bets.

4. **Trend Filter**: The 10-minute trend filter eliminates counter-trend signals that caused 80% directional bias in v2 (which lost 49.5% ROI).

### Entry Rules

1. **DISLOCATION Signal** (Primary):
   - BTC has moved >0.05% in current window AND Polymarket token price hasn't adjusted
   - Fair probability estimated as: `fair_prob = 0.5 + (|Δ_btc| / time_decay) × 5.0`, capped at 0.80
   - Requires fee-adjusted edge >2% AND 10-min trend agreement

2. **DIRECTIONAL Signal** (Secondary):
   - Fires in final 30 seconds of window
   - Composite confidence ≥0.45
   - BTC price confirms direction by >0.03%
   - 10-min trend agrees

3. **MAKER Signal** (Tertiary):
   - Posts limit orders 2 cents below ask to earn 20% maker rebate
   - Requires confidence ≥0.45 and trend agreement

### Exit Rules

1. **Time Stop**: Position auto-resolves at 5-minute window close
2. **Take Profit**: Automatic - token pays $1.00 if direction correct
3. **Stop Loss**: Automatic - token pays $0.00 if direction incorrect
4. **Early Exit**: Not applicable - positions must hold to resolution

### Risk Management

- **Position Size**: Fractional Kelly criterion
  - `edge = confidence - token_price`
  - `kelly = edge / (1 - token_price)`
  - `size = budget × min(kelly, 0.25) × size_factor`
  - Maximum position: 25% of Kelly (quarter-Kelly cap)

- **Hard Rules** (LLM Filter):
  1. No duplicate bets on same 5-minute window
  2. Reject signals opposing 15-minute trend (unless BTC move >0.10%)
  3. After 3+ consecutive losses, require edge >0.05
  4. BTC move <0.03% with >90s remaining = noise, reject
  5. Don't bet against side priced >60% without strong evidence
  6. Cash <30% of starting → only approve high-conviction trades

- **Circuit Breakers**:
  - Daily loss limit: configurable % of starting balance
  - Max trades per session: configurable
  - LLM failure defaults to REJECT

## Why It Should NOT Work (Risk Factors)

1. **Random Walk at Short Horizons**: Live win rates of 25-27% observed (below 53% breakeven)
2. **Paper-to-Live Gap**: Paper trading showed 522× returns; live trading lost 49.5%
3. **Fee Structure**: 1.56% at $0.50 entry creates significant drag
4. **Slippage**: 2-4 cents per token (~4% worse than quoted in live trading)
5. **Execution Risk**: Thin order books in decentralized markets
6. **Oracle Risk**: Resolution depends on Polymarket's oracle infrastructure

## Signal Generation Details

### Composite Momentum Score (v3 Weights)
```
slope_tf = β₁ / mean(price) for tf ∈ {30s, 60s, 120s, 240s}
weighted_slope = Σ(slope_tf × weight_tf)
direction = UP if weighted_slope > 0, else DOWN
```

**v3 Weights** (favors longer lookbacks to reduce noise):
- 30s: 0.20
- 60s: 0.30
- 120s: 0.35
- 240s: 0.15

### 10-Minute Trend Filter
```python
def _get_medium_term_trend(self) -> tuple[str, float]:
    ticks = self._get_prices_in_window(600)
    slope = self._compute_slope(ticks)
    return ("UP" if slope > 0 else "DOWN"), abs(slope)
```
**Hard Rule**: DISLOCATION signals opposing 10-minute trend are blocked unconditionally.

### Fee Calculation
```
fee_per_share = price × 0.25 × (price × (1 — price))²
```
At $0.50 entry: ~$0.0156 per share (1.56%)

## Backtest Results (From Paper)

### Session 1 (v2 engine - FAILURE)
- Starting balance: ~$17 USDC.e
- Duration: ~2 hours
- Trades: 15
- Win Rate: 27% (4W/11L)
- ROI: -49.5%
- Problem: 80% of trades bet UP during DOWN-trending market

### Session 2 (v3 engine - PARTIAL SUCCESS)
- Starting balance: $31.19 USDC.e
- Duration: 1 hour
- Trades: 4
- Win Rate: 25%
- Loss: $4.18 (13% of capital)
- Improvement: 7× better capital preservation vs v2

### Key Insight
The v3 engine's improvements:
1. 10-minute trend filter eliminated directional bias
2. Raised thresholds reduced trade frequency by 73%
3. Corrected resolver provided accurate outcome data

## Similar Strategies Already Built

- **polymarket_combinatorial_arbitrage**: Targets spread inefficiency across multiple related markets
- **polymarket-arbitrage**: Basic Polymarket arbitrage
- **defi_liquidation_arb**: On-chain event-driven strategy

**This strategy is DISTINCT because**:
- Focuses on 5-min BTC binary options (not combinatorial spreads)
- Uses multi-timeframe momentum signals (not just spread arbitrage)
- Implements LLM-augmented filtering
- Uses fractional Kelly position sizing

## Implementation Architecture

```
polymarket_5min_signal_arb/
├── README.md                    # Strategy overview
├── research.md                  # This research document
├── config/
│   ├── params.yaml             # Tunable parameters
│   └── assets.yaml             # Asset universe (BTC 5-min markets)
├── src/
│   ├── __init__.py
│   ├── strategy.py             # Core orchestrator (300+ lines)
│   ├── signal_engine.py        # Composite momentum + trend filter
│   ├── position_sizer.py       # Fractional Kelly implementation
│   ├── llm_filter.py           # LLM trade filter with structured prompts
│   ├── execution.py            # Polymarket CLOB execution
│   └── risk_manager.py         # Circuit breakers, limits
├── backtest/
│   ├── backtest.py             # Historical simulation
│   ├── data_loader.py         # BTC price + Polymarket data
│   └── optimizer.py            # Parameter optimization
├── results/
│   ├── equity_curve.png
│   ├── metrics.json
│   └── trades.csv
└── requirements.txt
```

## Key References

1. Kelly Jr., J.L. "A new interpretation of information rate" (1956)
2. Fama, E.F. "Efficient capital markets" (1970)
3. Almgren, R. & Chriss, N. "Optimal execution of portfolio transactions" (2000)
4. Jegadeesh, N. & Titman, S. "Returns to buying winners and selling losers" (1993)
5. Bailey et al. "Pseudo-mathematics and financial charlatanism" (2014)
