"""
Whale Tracking System
Monitors successful traders on Polymarket for alpha signals
"""

import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WhalePosition:
    """Represents a whale's position in a market"""
    trader_address: str
    market_id: str
    market_name: str
    side: str  # 'YES' or 'NO'
    size: float
    entry_price: float
    current_price: float
    pnl: float
    timestamp: datetime


@dataclass
class WhaleProfile:
    """Profile of a tracked whale trader"""
    address: str
    nickname: str
    total_volume: float
    profit_loss: float
    win_rate: float
    avg_trade_size: float
    markets_traded: int
    last_trade: datetime
    risk_score: float  # 0-1, based on volatility of returns


class WhaleTracker:
    """
    Tracks and analyzes whale activity on Polymarket
    
    Features:
    - Monitor top trader addresses
    - Detect position changes
    - Calculate performance metrics
    - Generate mirror signals
    """
    
    # Known high-performing addresses (would be updated from on-chain analysis)
    DEFAULT_WHALE_ADDRESSES = [
        # These are example addresses - real ones would be discovered through analysis
        "0x1234...abcd",  # Example whale 1
        "0x5678...efgh",  # Example whale 2
    ]
    
    def __init__(self, min_trade_size: float = 10000):
        """
        Args:
            min_trade_size: Minimum trade size to consider ($)
        """
        self.min_trade_size = min_trade_size
        self.whales: Dict[str, WhaleProfile] = {}
        self.positions: Dict[str, List[WhalePosition]] = defaultdict(list)
        self.trade_history: List[Dict] = []
        
        # Initialize with known whales
        for addr in self.DEFAULT_WHALE_ADDRESSES:
            self.whales[addr] = WhaleProfile(
                address=addr,
                nickname=f"Whale_{addr[:6]}",
                total_volume=0,
                profit_loss=0,
                win_rate=0,
                avg_trade_size=0,
                markets_traded=0,
                last_trade=datetime.utcnow(),
                risk_score=0.5
            )
    
    def process_trade(self, trade_data: Dict) -> Optional[Dict]:
        """
        Process a new trade and detect whale activity
        
        Args:
            trade_data: Trade information including trader, size, market
            
        Returns:
            Signal dict if whale activity detected, None otherwise
        """
        trader = trade_data.get("trader_address")
        size = trade_data.get("size", 0)
        
        # Check if this is a whale-sized trade
        if size < self.min_trade_size:
            return None
        
        # Check if we track this trader
        if trader not in self.whales:
            # New potential whale - add to tracking
            self.whales[trader] = WhaleProfile(
                address=trader,
                nickname=f"Whale_{trader[:6]}",
                total_volume=size,
                profit_loss=0,
                win_rate=0.5,
                avg_trade_size=size,
                markets_traded=1,
                last_trade=datetime.utcnow(),
                risk_score=0.5
            )
            logger.info(f"New whale detected: {trader}")
        
        whale = self.whales[trader]
        
        # Update whale stats
        whale.total_volume += size
        whale.last_trade = datetime.utcnow()
        whale.markets_traded = len(self.positions[trader])
        
        # Record position
        position = WhalePosition(
            trader_address=trader,
            market_id=trade_data.get("market_id"),
            market_name=trade_data.get("market_name", "Unknown"),
            side=trade_data.get("side", "YES"),
            size=size,
            entry_price=trade_data.get("price", 0),
            current_price=trade_data.get("price", 0),
            pnl=0,
            timestamp=datetime.utcnow()
        )
        
        self.positions[trader].append(position)
        
        # Generate signal
        signal = {
            "type": "whale_trade",
            "timestamp": datetime.utcnow().isoformat(),
            "whale_address": trader,
            "whale_nickname": whale.nickname,
            "market_id": position.market_id,
            "market_name": position.market_name,
            "side": position.side,
            "size_usd": size,
            "price": position.entry_price,
            "confidence": self._calculate_signal_confidence(whale),
            "whale_stats": {
                "total_volume": whale.total_volume,
                "win_rate": whale.win_rate,
                "risk_score": whale.risk_score
            }
        }
        
        self.trade_history.append(signal)
        logger.info(f"Whale signal: {whale.nickname} bought {position.side} in {position.market_name} (${size:,.0f})")
        
        return signal
    
    def _calculate_signal_confidence(self, whale: WhaleProfile) -> float:
        """
        Calculate confidence score for a whale's signal
        
        Factors:
        - Historical win rate (40%)
        - Volume/track record (30%)
        - Risk-adjusted returns (30%)
        """
        win_rate_score = whale.win_rate * 0.4
        
        # Volume score (logarithmic scale)
        volume_score = min(0.3, (whale.total_volume / 1000000) * 0.3)
        
        # Risk score (inverse of risk - lower risk = higher confidence)
        risk_score = (1 - whale.risk_score) * 0.3
        
        return win_rate_score + volume_score + risk_score
    
    def get_active_signals(self, min_confidence: float = 0.6) -> List[Dict]:
        """
        Get current whale trading signals
        
        Args:
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of active signals
        """
        cutoff = datetime.utcnow() - timedelta(hours=24)
        
        signals = [
            s for s in self.trade_history
            if datetime.fromisoformat(s["timestamp"]) > cutoff
            and s["confidence"] >= min_confidence
        ]
        
        # Sort by confidence
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        
        return signals
    
    def get_whale_leaderboard(self, n: int = 10) -> List[WhaleProfile]:
        """
        Get top performing whales
        
        Args:
            n: Number of whales to return
            
        Returns:
            List of whale profiles sorted by performance
        """
        # Sort by profit/loss (would be calculated from actual PnL in production)
        sorted_whales = sorted(
            self.whales.values(),
            key=lambda w: w.total_volume * w.win_rate,
            reverse=True
        )
        
        return sorted_whales[:n]
    
    def calculate_mirror_position(self, signal: Dict, 
                                   capital: float,
                                   max_exposure: float = 0.1) -> Dict:
        """
        Calculate position size for mirroring a whale
        
        Args:
            signal: The whale signal
            capital: Available capital
            max_exposure: Max % of capital per trade
            
        Returns:
            Position sizing recommendation
        """
        confidence = signal["confidence"]
        whale_size = signal["size_usd"]
        
        # Scale our position based on confidence
        base_exposure = capital * max_exposure
        confidence_multiplier = confidence  # 0.6-1.0 range
        
        # Don't exceed whale's position size (respect their sizing)
        max_position = min(whale_size * 0.1, base_exposure * confidence_multiplier)
        
        return {
            "action": "mirror",
            "market_id": signal["market_id"],
            "side": signal["side"],
            "recommended_size_usd": round(max_position, 2),
            "confidence": round(confidence, 2),
            "whale_ref": signal["whale_nickname"],
            "rationale": f"High-confidence whale signal ({confidence*100:.0f}%)"
        }
    
    def export_data(self, filepath: str):
        """Export tracking data to JSON"""
        data = {
            "whales": [
                {
                    "address": w.address,
                    "nickname": w.nickname,
                    "total_volume": w.total_volume,
                    "win_rate": w.win_rate,
                    "markets_traded": w.markets_traded
                }
                for w in self.whales.values()
            ],
            "recent_signals": self.trade_history[-100:],  # Last 100 signals
            "exported_at": datetime.utcnow().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Whale data exported to {filepath}")


class WhaleScanner:
    """
    Scans blockchain data to discover new whale addresses
    """
    
    def __init__(self):
        self.candidates = []
    
    def analyze_transactions(self, transactions: List[Dict]) -> List[str]:
        """
        Analyze transaction history to find whale candidates
        
        Returns:
            List of addresses meeting whale criteria
        """
        address_stats = defaultdict(lambda: {"volume": 0, "trades": 0, "profit": 0})
        
        for tx in transactions:
            addr = tx.get("from")
            size = tx.get("value", 0)
            
            address_stats[addr]["volume"] += size
            address_stats[addr]["trades"] += 1
        
        # Filter for whales (high volume, multiple trades)
        whales = []
        for addr, stats in address_stats.items():
            if stats["volume"] > 100000 and stats["trades"] > 10:
                whales.append(addr)
        
        return whales


# Example usage
def main():
    """Example whale tracking"""
    tracker = WhaleTracker(min_trade_size=5000)
    
    # Simulate some trades
    example_trades = [
        {
            "trader_address": "0x1234...abcd",
            "market_id": "0xabc",
            "market_name": "BTC above $100k",
            "side": "YES",
            "size": 50000,
            "price": 0.65
        },
        {
            "trader_address": "0x5678...efgh",
            "market_id": "0xdef",
            "market_name": "ETH ETF approved",
            "side": "NO",
            "size": 25000,
            "price": 0.30
        }
    ]
    
    for trade in example_trades:
        signal = tracker.process_trade(trade)
        if signal:
            print(f"\nSignal generated:")
            print(f"  Whale: {signal['whale_nickname']}")
            print(f"  Market: {signal['market_name']}")
            print(f"  Side: {signal['side']}")
            print(f"  Size: ${signal['size_usd']:,.0f}")
            print(f"  Confidence: {signal['confidence']*100:.0f}%")
    
    # Get active signals
    print("\n\nActive Signals (24h):")
    active = tracker.get_active_signals()
    for sig in active:
        mirror = tracker.calculate_mirror_position(sig, capital=100000)
        print(f"  {sig['market_name']}: {sig['side']} ${mirror['recommended_size_usd']:,.0f}")


if __name__ == "__main__":
    main()
