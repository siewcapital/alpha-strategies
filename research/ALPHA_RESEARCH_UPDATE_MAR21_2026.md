# Alpha Research Update: March 21, 2026

**Researcher:** ATLAS  
**Date:** March 21, 2026  
**Status:** Ongoing Research — Market Condition Analysis (Extreme Fear)

---

## Current Market Context (Mar 21, 2026)

*   **Fear & Greed Index:** 12 (Extreme Fear)
*   **Macro Environment:** US-Iran conflict (Brent ~$108) + New 15% global US tariff.
*   **Price Action:** BTC ~$70,415 (stabilizing but under pressure); ETH ~$2,150.
*   **Volatility:** High realized volatility; Implied Volatility (IV) falling for BTC but rising for ETH (expansion of ETH-BTC vol spread).

---

## Research Progress & New Opportunities

### 1. Volatility Arbitrage (Status: ACTIVE)
*   **Finding:** "Carry has turned positive" on Deribit as of Mar 18-21. Short gamma strategies (selling volatility) are starting to perform better as price action approaches key resistance levels.
*   **BTC vs ETH:** ETH IV premium is expanding, indicating higher expected volatility for ETH relative to BTC.
*   **Actionable Alpha:** Delta-hedged short volatility on BTC (capturing rich IV) vs. Long volatility on ETH if the price breakout continues.

### 2. Delta-Neutral DeFi (Status: ACTIVE)
*   **Toros Finance Benchmark:** USDmny and USDpy vaults showing ~3.98% APY. 
*   **Extreme Fear Impact:** High risk-off sentiment increases borrowing costs for volatile assets (hedging leg), potentially compressing margins for delta-neutral yield strategies.
*   **Execution Pivot:** Manual selection of high-incentive Uniswap V3 pairs during high-volume volatility spikes may outperform automated vaults like Toros in the current regime.

### 3. NEW: Liquidation Cascade Sniping (LCS)
*   **Overview:** Profiting from the "over-extension" of price during liquidation cascades (forced liquidations on Bybit/Binance).
*   **Mechanics:** Use the OBI Data Pipeline (Strategy 4) to detect liquidation-driven price spikes. Execute mean reversion trades immediately following the exhaustion of liquidation volume.
*   **Relevance:** Highly relevant in the current "Extreme Fear" (12) environment where leverage flushes are frequent.

### 4. Strategy 9 (Basis Trade) Progress
*   **Status:** Paper trading (Day 2 of 7).
*   **Observation:** SOL +6.89% annualized basis on Bybit. Returns remain stable despite macro volatility, confirming "Basis Trade" as the primary low-risk/safe-haven strategy for the current portfolio.

---

## Strategy Comparison Matrix (Updated)

| Strategy | Yield (Est) | Risk Level | Market Fit |
|----------|-------------|------------|------------|
| Basis Trade | 6-15% | Low | Excellent (Stable in Fear) |
| Volatility Arb | 10-25% | Medium-High | Good (High IV capture) |
| DeFi Delta-Neutral | 4-12% | Medium | Neutral (Margin compression) |
| Liquidation Sniping| Variable | High | Excellent (High Vol focus) |

---

## Next Steps

1.  **Monitor Basis Trade:** Continue 1-week paper trading for Strategy 9.
2.  **Vol Arb Script:** Develop a monitor for the ETH-BTC IV spread to identify "mean-reverting" vol opportunities.
3.  **Liquidation Bot:** Prototype a "Liquidation Monitor" using the existing OBI infrastructure to quantify LCS opportunity size.

---

*Research by ATLAS | Siew's Capital Research Division | March 2026*
