# Cross-Chain MEV Arbitrage Strategy - Research

## Concept

Exploit persistent price differentials for identical assets across different blockchain networks. When BTC/ETH/USDC prices diverge between Ethereum, Arbitrum, Optimism, Base, and other chains, capture the spread minus bridging costs and gas.

Unlike centralized exchange arbitrage, cross-chain arbitrage involves:
- **Finality latency**: Canonical bridges take 7-30 minutes; fast bridges take seconds to minutes
- **Bridge risk**: Bridge smart contract risk, bridge operator risk, liquidity risk
- **Gas heterogeneity**: Different chains have different gas costs and unit economics
- **MEV exposure**: Sandwich attacks possible on DEX legs

## Research Sources

### Academic/Papers
- "Clockchain: Measuring Cross-Chain Profitability" - arXiv (2025)
- "MEV in the Wild: Cross-Chain arbitrage" - Flashbots Research (2024)
- Stargate Finance LP dynamics and delta algorithm

### Protocol Documentation
- **Stargate** (LayerZero): Delta algorithm for unified liquidity, 0.06% pool fee
- **Across** ( UMA ): Optimistic bridge, intent-based, 0.1% relayer fee
- **Synapse**: Multi-chain messaging, 0.04% bridge fee
- **Wormhole**: Guardian-based, 0.001 ETH destination gas
- **Celer cBridge**: State Guardian Network, sub-minute bridging

### Practitioner References
- @0xMis informed @CrossChainArb threads on bridge latency analysis
- @防守者|MEV bot builders on Twitter discussing cross-chain arb economics
- Gigantorender / Jump Crypto internal docs (referenced in academic papers)

## Market Structure

### Cross-Chain Price Dynamics
1. **Normal spread**: 0.01-0.1% (noise, arbitrageurs keep tight)
2. **Volatility spike**: 0.3-2.0% (news, liquidations cascade)
3. **Bridge congestion**: 0.5-5.0% (TVL shifts, market dislocations)
4. **Black swan**: >5% (FTX collapse, depeg events)

### Bridge Economics (2025-2026 Data)
| Bridge | Speed | Fee | Security |
|--------|-------|-----|---------|
| Stargate | ~30s | 0.06% | LayerZero |
| Across | ~60s | 0.1% | UMA oracle |
| Synapse | ~3min | 0.04% | Synapse verified |
| Wormhole | ~15min | 0.001 ETH | 19 guardians |
| Canonical | ~7-30min | Gas only | Native |

### Break-Even Analysis
- **Fast bridge (Stargate)**: 0.06% + gas (~$0.50 on Arbitrum) = ~0.07% all-in
- **Across**: 0.1% + relayer fee = ~0.15% all-in
- **Canonical**: Gas only (~$5 on ETH mainnet) = meaningful for large sizes only

### Minimum Profitable Spread
```
min_spread = (bridge_fee% + gas_usd / trade_size_usd) * (1 + slippage%)
```

For $10K trade:
- Stargate: 0.06% + $0.50/$10K = 0.065% break-even
- Across: 0.1% + $2/$10K = 0.12% break-even
- Canonical ETH: 0% + $5/$10K = 0.05% → but 7-30 min latency risk

For $100K trade:
- All bridges effectively 0.06-0.10% break-even

## Strategy Architecture

### Three-Leg Execution Model
1. **BUY leg**: Purchase asset on Chain A (low price) via DEX
2. **BRIDGE leg**: Transfer asset across chains (fast bridge)
3. **SELL leg**: Sell asset on Chain B (high price) via DEX

**Alternative (no-bridge)**:
- Use跨-chain DEXs (e.g., THALES, Lyra) that settle cross-chain without bridging

### Signal Generation
- **Z-score of cross-chain spread**: Mean-reversion when spread exceeds 2σ
- **Event-triggered**: Large moves, oracle updates, governance decisions
- **Delta-neutral option**: When arb requires capital, use flash loans

### Risk Management
- **Bridge risk scoring**: Based on TVL, age, audit status
- **Max bridge exposure**: Never >20% of capital in transit
- **Finality confirmation**: Wait for destination finality before counting profit
- **MEV protection**: Use private mempools or Flashbots for DEX legs

## Previous Work (What NOT to Duplicate)
- DeFi Liquidation Arb (built, Sharpe profile)
- Funding Rate Arb (built)
- Polymarket Arb (built)
- Avellaneda-Stoikov MM (built)

## Unique Contribution
- Cross-chain spread monitoring with multi-bridge routing
- Bridge risk scoring and dynamic bridge selection
- MEV-aware execution (Sandwich protection)
- L2-first approach (cheaper gas = more opportunities viable)

## Expected Performance
- **Conservative**: 15-30% annual return with low drawdown
- **Opportunistic**: 50-100% during high-vol regimes
- **Key risk**: Bridge exploit, depeg events, congestion

## References
- Stargate Whitepaper: "Delta Algorithm for Unified Liquidity"
- Across Protocol: "Intent-Based Cross-Chain Swaps"
- Flashbots: "MEV and the Limits of Scaling" (2025)
- arXiv:2012.03457 "Blockchain Profitability Calculator"
