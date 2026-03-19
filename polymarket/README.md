# Polymarket Strategies

This folder contains strategies for trading on [Polymarket](https://polymarket.com), a decentralized prediction market platform built on Polygon.

---

## Overview

Polymarket allows users to trade on the outcome of real-world events using binary (YES/NO) markets. The platform offers unique alpha opportunities through:

- **Market Inefficiencies**: Prediction markets are less efficient than traditional financial markets
- **Information Asymmetry**: Traders with superior information can profit from price discrepancies
- **Low Competition**: Fewer sophisticated market makers compared to crypto exchanges
- **Combinatorial Opportunities**: Related markets can have logical inconsistencies

---

## Strategy Inventory

### 1. Polymarket HFT (High-Frequency Trading)

**Location**: `../strategies/polymarket-hft/`

**Strategy Type**: High-frequency market making/arbitrage

**Core Concept**: 
Capture the bid-ask spread on 5-minute BTC prediction markets using limit orders. By placing limit orders on both sides and hedging directional exposure, the strategy extracts small but frequent profits.

**Key Metrics**:
| Metric | Value |
|--------|-------|
| Trade Frequency | 273 trades/hour |
| Average Edge | 0.3% per trade |
| Reported Return | ~8,500% (1 month) |
| Backtest Return | ~2,645% (median) |

**Why It Works**:
- BTC volatility creates wide bid-ask spreads
- 5-minute markets have high volume ($37M+)
- Limit orders capture maker rebates
- Directional hedging neutralizes market risk

**Risk Factors**:
- Requires sub-second execution
- Competing bots may erode edge
- API rate limits
- Binary settlement risk

**Files**:
- `backtest.py` - Monte Carlo simulation
- `results.md` - Performance analysis
- `requirements.txt` - Dependencies

---

### 2. Polymarket Arbitrage

**Location**: `../strategies/polymarket-arbitrage/`

**Strategy Type**: Cross-platform and combinatorial arbitrage

**Core Concept**:
Exploit pricing inefficiencies through four vectors:

1. **Cross-Platform Arbitrage**
   - Compare YES/NO prices across Polymarket, Kalshi, BetOnline
   - Buy underpriced side on one platform, sell on another
   - Requires: Multiple exchange accounts, fast price discovery

2. **Combinatorial Arbitrage**
   - Find logical inconsistencies between related markets
   - Example: "Party Wins Presidential Election" vs "Candidate Wins Primary"
   - Sum of probabilities should equal 1; deviations = opportunity

3. **Whale Mirroring**
   - Track successful large traders ("whales")
   - These traders often have non-public information
   - Mirror their positions with smaller size

4. **Tail-End Liquidity**
   - Capture premium in niche markets nearing settlement
   - Less competition in low-liquidity markets
   - Higher spreads = higher profit potential

**Key Metrics**:
| Metric | Target |
|--------|--------|
| APR | 15-40% |
| Max Drawdown | < 10% |
| Success Rate | > 65% per arb |

**Why It Works**:
- Prediction markets are fragmented across platforms
- Logical constraints create deterministic arbitrage
- Information asymmetry creates price drift
- Low liquidity in niche markets creates wide spreads

**Risk Factors**:
- Execution speed critical (millisecond windows)
- Settlement risk ( oracle failures)
- Platform counterparty risk
- Regulatory uncertainty

**Files**:
- `backtest.py` - Synthetic arbitrage detection
- `README.md` - Strategy documentation
- `results.json` - Backtest results

---

## Shared Infrastructure

This folder (`polymarket/`) is designated for shared infrastructure:

### Planned Components

1. **Unified API Client**
   - Polymarket CLOB (Central Limit Order Book) integration
   - WebSocket connection management
   - Authentication handling

2. **Data Pipeline**
   - Historical market data ingestion
   - Real-time price feeds
   - Event metadata tracking

3. **Risk Management**
   - Position tracking across strategies
   - Exposure monitoring
   - Circuit breakers

4. **Utilities**
   - Probability calculations
   - Combinatorial market analysis
   - PnL tracking

---

## Getting Started

### Prerequisites

- Python 3.8+
- Polygon wallet with USDC.e
- Polymarket account
- (For arbitrage) Accounts on Kalshi, BetOnline, etc.

### Installation

```bash
# Clone the repository
git clone https://github.com/siewcapital/alpha-strategies.git
cd alpha-strategies

# Install dependencies for HFT strategy
pip install -r strategies/polymarket-hft/requirements.txt

# Run HFT backtest
cd strategies/polymarket-hft
python backtest.py
```

---

## Comparison: HFT vs Arbitrage

| Factor | HFT Strategy | Arbitrage Strategy |
|--------|--------------|-------------------|
| **Frequency** | 273 trades/hour | 1-10 trades/day |
| **Hold Time** | Seconds to minutes | Hours to days |
| **Edge Source** | Bid-ask spread | Price discrepancies |
| **Capital** | $2K - $50K | $10K - $100K |
| **Risk Level** | Low (hedged) | Very Low (deterministic) |
| **Complexity** | Medium | High |
| **Latency Req** | Very High | High |

---

## Risk Considerations

### Common Risks

1. **Smart Contract Risk**
   - Polymarket uses smart contracts for settlement
   - Bugs or exploits could lock funds

2. **Oracle Risk**
   - Market outcomes depend on UMA optimistic oracle
   - Disputed resolutions can delay settlement

3. **Liquidity Risk**
   - Niche markets may have wide spreads
   - Large positions may move the market

4. **Regulatory Risk**
   - Prediction markets face regulatory uncertainty
   - Platform may restrict access in certain jurisdictions

### Mitigation Strategies

- Diversify across many small positions
- Use only risk capital
- Monitor oracle dispute periods
- Stay informed on regulatory developments

---

## Resources

### Official Documentation
- [Polymarket Docs](https://docs.polymarket.com/)
- [UMA Oracle Docs](https://docs.umaproject.org/)
- [Polygon PoS Docs](https://wiki.polygon.technology/)

### Community Tools
- [PolyCop Bot](https://t.me/PolyCop_BOT) - Whale tracking
- [Polymarket API](https://api.polymarket.com/) - Market data

### Research
- "Prediction Markets: A Review" - Wolfers & Zitzewitz
- "The Wisdom of Crowds" - Surowiecki

---

## Performance Tracking

| Strategy | Status | Last Updated | Return |
|----------|--------|--------------|--------|
| Polymarket HFT | ✅ Validated | 2026-03-19 | +2,645% (backtest) |
| Polymarket Arbitrage | 🔄 In Development | 2026-03-19 | TBD |

---

## Contributing

To add a new Polymarket strategy:

1. Create a new folder in `strategies/polymarket-{strategy-name}/`
2. Include `backtest.py`, `README.md`, and `requirements.txt`
3. Document the edge and risk factors
4. Add to this README's inventory

---

## Disclaimer

Prediction markets involve risk of loss. These strategies are for educational purposes. Past performance does not guarantee future results. Ensure compliance with local regulations before trading.
