# Alpha Research Update: March 21, 2026 (Evening Session)

**Researcher:** ATLAS  
**Date:** March 21, 2026 — 4:39 PM (Asia/Shanghai)  
**Status:** Research Tools Development Complete

---

## Summary

Completed development of two new research monitoring tools to advance the alpha research agenda:

1. **Volatility Arbitrage Monitor** — ETH-BTC IV spread tracker
2. **Liquidation Cascade Sniping (LCS) Monitor** — Liquidation-driven price dislocation detector

---

## 1. Volatility Arbitrage Monitor ✅ COMPLETE

**File:** `research/volatility_arbitrage_monitor.py`

### Features
- Real-time monitoring of ETH-BTC implied volatility spreads
- Multi-exchange support (Deribit, Binance)
- Automatic regime detection (6 volatility states)
- Trading signal generation with confidence scoring
- Delta-hedged strategy recommendations

### Regime Detection
| Regime | Spread | Action |
|--------|--------|--------|
| EXTREME_HIGH | ETH IV 20%+ above BTC | SELL_ETH_VOL |
| HIGH | ETH IV 10%+ above BTC | CONSIDER_SELL_ETH_VOL |
| NORMAL_HIGH | ETH IV 5%+ above BTC | MONITOR |
| NORMAL | Within ±5% | NO_TRADE |
| NORMAL_LOW | ETH IV 5% below BTC | MONITOR |
| LOW | ETH IV 10% below BTC | CONSIDER_BUY_ETH_VOL |
| EXTREME_LOW | ETH IV 20% below BTC | BUY_ETH_VOL |

### Usage
```bash
cd research
python volatility_arbitrage_monitor.py --exchanges deribit --threshold 5
```

---

## 2. Liquidation Cascade Sniping Monitor ✅ COMPLETE

**File:** `research/liquidation_cascade_monitor.py`

### Features
- Tracks liquidation volume across multiple exchanges
- Detects abnormal liquidation spikes (>3x average)
- Identifies price over-extension from liquidation cascades
- Generates mean-reversion trading signals
- Cooldown management to prevent over-trading

### Strategy Logic
1. Monitor liquidation volume and price velocity
2. Detect cascade events (high liquidations + price spike)
3. Identify exhaustion signals (capitulation/short squeeze)
4. Generate counter-trend mean-reversion signals
5. Target 2% mean reversion within 45 minutes

### Signal Components
- **Action:** LONG_MEAN_REVERSION or SHORT_MEAN_REVERSION
- **Confidence:** 0-100% based on liquidation magnitude, price velocity, exhaustion signals
- **Entry Zone:** Specific price range for entry
- **Target:** 2% mean reversion target
- **Stop Loss:** 5% protective stop
- **Position Size:** Scaled by confidence (0.5%, 1%, 2% risk)

### Usage
```bash
cd research
python liquidation_cascade_monitor.py --symbols BTC ETH SOL --threshold 3.0
```

---

## Current Market Snapshot (Mar 21, 2026)

### Fear & Greed Index: 12 (Extreme Fear)

| Asset | Price | 24h Change | Key Level |
|-------|-------|------------|-----------|
| BTC | $70,743 | -0.8% | $70k support holding |
| ETH | $2,158 | -1.2% | $2,100 critical support |
| SOL | $90.30 | -2.1% | $89 support tested |

### Basis Trade Update (Strategy 9)
- **Status:** Paper trading Day 2 of 7
- **Current Market:** Backwardation (futures < spot)
  - BTC: -0.077% basis (annualized)
  - ETH: -0.078% basis
  - SOL: -0.073% basis
- **Implication:** Market in strong contango, normal basis trades not viable currently
- **Action:** Monitor for basis normalization

### Research Priorities (Next 24h)
1. **Test Vol Arb Monitor** — Run against live Deribit data
2. **Test LCS Monitor** — Run during high volatility periods
3. **Basis Trade** — Continue paper trading, watch for opportunities
4. **Delta-Neutral DeFi** — Monitor Toros vaults vs manual execution

---

## Files Added

```
research/
├── volatility_arbitrage_monitor.py    # NEW - ETH-BTC IV spread tracker
├── liquidation_cascade_monitor.py     # NEW - Liquidation sniping tool
└── ALPHA_RESEARCH_UPDATE_MAR21_2026.md # UPDATED - This document
```

---

## Next Steps

1. **Immediate (Today)**
   - Test both monitors with live data
   - Validate signal accuracy
   - Document initial findings

2. **Short-term (This Week)**
   - Run 48-hour backtest on historical liquidation data
   - Correlate LCS signals with actual price recovery
   - Optimize thresholds based on market conditions

3. **Medium-term**
   - Integrate with OBI microstructure data pipeline
   - Build unified dashboard for all alpha monitors
   - Deploy paper trading for LCS strategy

---

*Research by ATLAS | Siew's Capital Research Division | March 2026*
