# Token Unlock Arbitrage Strategy

## Research Summary

**Source:** Animoca Brands Research via Smartkarma  
**Study:** 35,000 unlock events across 89 tokens (Jan 2022 - Sept 2024)  
**Key Paper:** "The Impact of Token Unlock Events on Cryptocurrency Prices: An Empirical Analysis"

---

## Key Findings

### 1. Price Impact Magnitude
- **1% unlock → 0.3% price drop** (week before unlock)
- **1% unlock → 0.3% price drop** (week after unlock)
- **Total predictable impact: ~0.6% per 1% of supply unlocked**

### 2. Timing Pattern (Critical for Trading)
| Timeframe | Price Action |
|-----------|-------------|
| Days -7 to -2 | Gradual decline (anticipation selling) |
| **Day -2** | **Strongest pre-unlock impact** |
| Days 0 to +1 | Little impact (unlock day itself) |
| **Days +3 to +4** | **Strongest post-unlock selling** |

### 3. Market Efficiency Insight
- Market **anticipates** unlocks just as much as actual selling pressure
- Similar magnitude of drops before and after = semi-efficient pricing
- Daily unlocks (small, recurring) show **no significant impact**

### 4. Statistical Edge
- Large unlocks (≥1% of supply) are the only tradeable events
- Predictable drift pattern allows for systematic shorting
- Win rate estimated at 60-70% with proper timing

---

## Strategy Design

### Entry Rules
1. Identify unlocks ≥1% of circulating supply
2. Enter **SHORT 2 days before** unlock date (optimal anticipation capture)
3. Position size scales with unlock magnitude (Kelly-based)
4. Max 10% portfolio per trade, 3 concurrent positions

### Exit Rules
1. **Time-based:** Exit day 4 after unlock (selling pressure subsides)
2. **Stop loss:** 2% (tight - this is an event trade)
3. **Profit target:** 3x expected move (captures outliers)

### Risk Management
- Quarter-Kelly position sizing
- Drawdown circuit breaker at 20%
- Daily loss limit at 3%
- Liquidity filters ($1M+ daily volume)

---

## Architecture

```
token_unlock_arbitrage/
├── src/
│   ├── strategy.py          # Core strategy logic
│   ├── risk_manager.py      # Risk controls & circuit breakers
│   ├── data_fetcher.py      # Unlock schedule data sources
│   └── indicators.py        # Technical indicators (if needed)
├── backtest/
│   └── backtest.py          # Event-driven backtest engine
├── tests/
│   └── test_strategy.py     # Unit tests
├── config/
│   └── params.yaml          # Strategy parameters
├── data/
│   └── sample_unlocks.csv   # Sample data
├── research.md              # This file
└── README.md                # Usage guide
```

---

## Expected Performance

Based on research-backed assumptions:

| Metric | Estimate |
|--------|----------|
| Win Rate | 60-70% |
| Avg Win | 1.5-2.0% |
| Avg Loss | 1.0-1.5% |
| Frequency | 2-4 trades/month |
| Annual Return | 15-30% |
| Max Drawdown | 15-25% |
| Sharpe Ratio | 1.0-1.5 |

**Note:** Real performance depends on:
- Quality of unlock data
- Execution latency
- Market regime (works best in sideways/bear markets)
- Competition (edge decays as more participants discover)

---

## Data Sources

### Tier 1: TokenUnlocks.app (Premium)
- Most accurate unlock schedules
- API access required
- Real-time updates

### Tier 2: CoinGecko API (Free)
- Circulating supply data
- Market cap and volume
- Rate limited

### Tier 3: Manual CSV
- Project announcements
- GitHub tokenomics docs
- Community tracking

---

## Limitations & Risks

1. **Data Quality:** Unlock schedules can change (delayed, accelerated)
2. **Market Regime:** Less effective in strong bull markets
3. **Competition:** Edge may decay as strategy becomes known
4. **Execution:** Requires reliable data feeds and fast execution
5. **Correlation:** Unlock events may cluster (market-wide stress)

---

## Future Enhancements

- [ ] Machine learning for impact prediction (unlock size + market conditions)
- [ ] Options overlay (buy puts instead of shorting)
- [ ] Multi-token baskets (diversify unlock exposure)
- [ ] Real-time monitoring dashboard
- [ ] Integration with Polymarket (bet on unlock outcomes)

---

## References

1. Animoca Brands Research (2025). "The Impact of Token Unlock Events on Cryptocurrency Prices: An Empirical Analysis." Smartkarma.
2. CoinGecko API Documentation
3. TokenUnlocks.app API

---

**Strategy Status:** ✅ ARCHITECTURE COMPLETE  
**Last Updated:** April 2, 2026  
**Author:** ATLAS (Siew's Capital Research)
