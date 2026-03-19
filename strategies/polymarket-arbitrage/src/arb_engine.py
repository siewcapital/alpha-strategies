"""
Arbitrage Detection Engine
Identifies and validates arbitrage opportunities across prediction markets
"""

import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from data_ingestion import MarketData, DataAggregator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ArbType(Enum):
    CROSS_PLATFORM = "cross_platform"
    COMBINATORIAL = "combinatorial"
    SELF_CONSISTENCY = "self_consistency"


@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage opportunity"""
    arb_type: ArbType
    event_name: str
    profit_percent: float
    confidence: float  # 0-1 scale
    legs: List[Dict]  # Execution details for each leg
    hold_time_estimate: str
    risk_factors: List[str]
    timestamp: datetime
    
    def is_executable(self, min_profit: float = 0.01) -> bool:
        """Check if opportunity meets execution threshold"""
        return self.profit_percent >= min_profit and self.confidence >= 0.7


class ArbitrageEngine:
    """
    Core engine for detecting arbitrage opportunities
    
    Supports:
    - Cross-platform arbitrage (Polymarket vs Kalshi vs others)
    - Combinatorial arbitrage (related markets)
    - Self-consistency arbitrage (YES + NO < 1.0 on same platform)
    """
    
    def __init__(self, min_profit_threshold: float = 0.015):
        """
        Args:
            min_profit_threshold: Minimum profit % to flag as opportunity (after fees)
        """
        self.min_profit = min_profit_threshold
        self.fees = {
            "polymarket": 0.002,  # 0.2% taker fee
            "kalshi": 0.000,      # No trading fees
            "betonline": 0.000    # Built into spread
        }
        self.data_aggregator = DataAggregator()
        
    async def scan_cross_platform(self, event_name: str) -> List[ArbitrageOpportunity]:
        """
        Scan for price discrepancies across platforms for the same event
        
        Args:
            event_name: Event to scan (e.g., "BTC above $100k Dec 2026")
            
        Returns:
            List of arbitrage opportunities
        """
        opportunities = []
        
        # Get data from all platforms
        platform_data = await self.data_aggregator.get_all_platforms_data(event_name)
        
        if len(platform_data) < 2:
            logger.info(f"Need at least 2 platforms for {event_name}, found {len(platform_data)}")
            return opportunities
        
        platforms = list(platform_data.keys())
        
        # Compare all platform pairs
        for i, p1 in enumerate(platforms):
            for p2 in platforms[i+1:]:
                data1 = platform_data[p1]
                data2 = platform_data[p2]
                
                # Check YES on P1, NO on P2
                profit1 = self._calculate_arb_profit(
                    data1.yes_ask, data2.no_ask,
                    self.fees.get(p1, 0.002), self.fees.get(p2, 0.002)
                )
                
                if profit1 > self.min_profit:
                    opportunities.append(ArbitrageOpportunity(
                        arb_type=ArbType.CROSS_PLATFORM,
                        event_name=event_name,
                        profit_percent=profit1,
                        confidence=0.85,
                        legs=[
                            {"platform": p1, "side": "YES", "price": data1.yes_ask, "fee": self.fees.get(p1, 0.002)},
                            {"platform": p2, "side": "NO", "price": data2.no_ask, "fee": self.fees.get(p2, 0.002)}
                        ],
                        hold_time_estimate="Minutes to hours",
                        risk_factors=["Execution timing", "Platform withdrawal delays"],
                        timestamp=datetime.utcnow()
                    ))
                
                # Check NO on P1, YES on P2
                profit2 = self._calculate_arb_profit(
                    data1.no_ask, data2.yes_ask,
                    self.fees.get(p1, 0.002), self.fees.get(p2, 0.002)
                )
                
                if profit2 > self.min_profit:
                    opportunities.append(ArbitrageOpportunity(
                        arb_type=ArbType.CROSS_PLATFORM,
                        event_name=event_name,
                        profit_percent=profit2,
                        confidence=0.85,
                        legs=[
                            {"platform": p1, "side": "NO", "price": data1.no_ask, "fee": self.fees.get(p1, 0.002)},
                            {"platform": p2, "side": "YES", "price": data2.yes_ask, "fee": self.fees.get(p2, 0.002)}
                        ],
                        hold_time_estimate="Minutes to hours",
                        risk_factors=["Execution timing", "Platform withdrawal delays"],
                        timestamp=datetime.utcnow()
                    ))
        
        return opportunities
    
    def _calculate_arb_profit(self, price1: float, price2: float, 
                               fee1: float, fee2: float) -> float:
        """
        Calculate net profit percentage for a two-leg arbitrage
        
        Args:
            price1: Price to buy first leg
            price2: Price to buy second leg
            fee1, fee2: Trading fees for each platform
            
        Returns:
            Net profit percentage (0.02 = 2%)
        """
        total_cost = price1 + price2
        fees = (price1 * fee1) + (price2 * fee2)
        gross_profit = 1.0 - total_cost
        net_profit = gross_profit - fees
        return max(0, net_profit)
    
    def scan_self_consistency(self, market_data: MarketData) -> Optional[ArbitrageOpportunity]:
        """
        Check if YES + NO < 1.0 on a single platform (guaranteed profit)
        
        This is rare but can occur during high volatility
        """
        total = market_data.yes_ask + market_data.no_ask
        
        if total < 0.99:  # 1% profit threshold
            profit = 1.0 - total
            fee = self.fees.get(market_data.source, 0.002)
            net_profit = profit - (2 * fee)
            
            if net_profit > self.min_profit:
                return ArbitrageOpportunity(
                    arb_type=ArbType.SELF_CONSISTENCY,
                    event_name=market_data.event_name,
                    profit_percent=net_profit,
                    confidence=0.99,  # Near-certain
                    legs=[
                        {"platform": market_data.source, "side": "YES", "price": market_data.yes_ask, "fee": fee},
                        {"platform": market_data.source, "side": "NO", "price": market_data.no_ask, "fee": fee}
                    ],
                    hold_time_estimate="Immediate",
                    risk_factors=["Platform may cancel erroneous orders"],
                    timestamp=datetime.utcnow()
                )
        return None
    
    def scan_combinatorial(self, markets: List[MarketData]) -> List[ArbitrageOpportunity]:
        """
        Find logical inconsistencies between related markets
        
        Examples:
        - Primary winner probabilities should sum to ~1.0
        - Conditional markets should respect probability bounds
        - Election slates should be internally consistent
        """
        opportunities = []
        
        # Group markets by category
        categories = self._categorize_markets(markets)
        
        for category, cat_markets in categories.items():
            if "election" in category.lower() or "primary" in category.lower():
                # Check if candidate probabilities sum to > 1.0
                total_prob = sum(m.yes_price for m in cat_markets)
                
                if total_prob > 1.05:  # 5% overround
                    # Opportunity: Sell all YES or buy all NO
                    avg_profit = (total_prob - 1.0) / len(cat_markets)
                    
                    opportunities.append(ArbitrageOpportunity(
                        arb_type=ArbType.COMBINATORIAL,
                        event_name=f"{category} - Overround",
                        profit_percent=avg_profit,
                        confidence=0.90,
                        legs=[
                            {"market": m.event_name, "side": "YES", "price": m.yes_bid}
                            for m in cat_markets
                        ],
                        hold_time_estimate="Hours to days",
                        risk_factors=["Markets may not settle simultaneously", "New candidate entry"],
                        timestamp=datetime.utcnow()
                    ))
        
        return opportunities
    
    def _categorize_markets(self, markets: List[MarketData]) -> Dict[str, List[MarketData]]:
        """Group markets by category for combinatorial analysis"""
        categories = {}
        
        for market in markets:
            # Extract category from event name
            # This is simplified - real implementation would use market metadata
            category = "general"
            
            if any(word in market.event_name.lower() for word in ["election", "primary", "vote"]):
                category = "election"
            elif any(word in market.event_name.lower() for word in ["btc", "bitcoin", "eth", "crypto"]):
                category = "crypto"
            elif any(word in market.event_name.lower() for word in ["cpi", "fed", "rate", "inflation"]):
                category = "macro"
            
            if category not in categories:
                categories[category] = []
            categories[category].append(market)
        
        return categories
    
    def calculate_position_sizing(self, opportunity: ArbitrageOpportunity, 
                                   capital: float) -> Dict:
        """
        Calculate optimal position sizes for an arbitrage
        
        Args:
            opportunity: The arbitrage opportunity
            capital: Available capital
            
        Returns:
            Position sizing for each leg
        """
        # Conservative sizing - 10% of capital per trade
        trade_capital = capital * 0.10
        
        # Split equally between legs
        num_legs = len(opportunity.legs)
        capital_per_leg = trade_capital / num_legs
        
        positions = []
        for leg in opportunity.legs:
            price = leg.get("price", 0.5)
            if price > 0:
                size = capital_per_leg / price
                positions.append({
                    "platform": leg.get("platform", "unknown"),
                    "side": leg.get("side", "unknown"),
                    "price": price,
                    "size": round(size, 4),
                    "capital": capital_per_leg
                })
        
        return {
            "total_capital": trade_capital,
            "expected_profit": trade_capital * opportunity.profit_percent,
            "positions": positions
        }
    
    async def run_full_scan(self, event_list: List[str]) -> Dict:
        """
        Run a complete arbitrage scan across all strategies
        
        Args:
            event_list: List of event names to scan
            
        Returns:
            Scan results summary
        """
        all_opportunities = []
        
        for event in event_list:
            logger.info(f"Scanning {event}...")
            
            # Cross-platform scan
            cross_plat = await self.scan_cross_platform(event)
            all_opportunities.extend(cross_plat)
            
        # Sort by profit
        all_opportunities.sort(key=lambda x: x.profit_percent, reverse=True)
        
        return {
            "total_scanned": len(event_list),
            "opportunities_found": len(all_opportunities),
            "executable": len([o for o in all_opportunities if o.is_executable()]),
            "by_type": self._summarize_by_type(all_opportunities),
            "top_opportunities": all_opportunities[:5]
        }
    
    def _summarize_by_type(self, opportunities: List[ArbitrageOpportunity]) -> Dict:
        """Summarize opportunities by type"""
        summary = {}
        for arb_type in ArbType:
            type_ops = [o for o in opportunities if o.arb_type == arb_type]
            if type_ops:
                summary[arb_type.value] = {
                    "count": len(type_ops),
                    "avg_profit": sum(o.profit_percent for o in type_ops) / len(type_ops),
                    "max_profit": max(o.profit_percent for o in type_ops)
                }
        return summary


# Example usage
async def main():
    """Example arbitrage scan"""
    engine = ArbitrageEngine(min_profit_threshold=0.01)
    
    # List of events to monitor
    events = [
        "Bitcoin above 100k 2026",
        "Ethereum above 10k 2026",
        "Fed rate cut June 2026",
    ]
    
    results = await engine.run_full_scan(events)
    
    print(f"\nScan complete!")
    print(f"Events scanned: {results['total_scanned']}")
    print(f"Opportunities found: {results['opportunities_found']}")
    print(f"Executable: {results['executable']}")
    
    if results['top_opportunities']:
        print("\nTop Opportunities:")
        for i, opp in enumerate(results['top_opportunities'][:3], 1):
            print(f"{i}. {opp.event_name}")
            print(f"   Type: {opp.arb_type.value}")
            print(f"   Profit: {opp.profit_percent*100:.2f}%")
            print(f"   Confidence: {opp.confidence*100:.0f}%")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
