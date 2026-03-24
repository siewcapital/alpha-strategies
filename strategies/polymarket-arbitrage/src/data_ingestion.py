"""
Polymarket CLOB Data Ingestion Module
Real-time market data feed from Polymarket's Central Limit Order Book
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import aiohttp
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class MarketData:
    """Standardized market data structure"""
    market_id: str
    event_name: str
    yes_price: float
    no_price: float
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    volume_24h: float
    liquidity: float
    timestamp: datetime
    source: str = "polymarket"


@dataclass
class Trade:
    """Trade execution data"""
    market_id: str
    side: str  # 'yes' or 'no'
    price: float
    size: float
    timestamp: datetime
    trader_address: Optional[str] = None


class PolymarketCLOBClient:
    """
    Client for Polymarket's CLOB API
    
    API Docs: https://docs.polymarket.com/
    """
    
    REST_API = "https://clob.polymarket.com"
    WS_API = "wss://ws-subscriber.clob.polymarket.com/ws"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_connection = None
        self.subscribers: List[Callable] = []
        self.is_running = False
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if self.ws_connection:
            await self.ws_connection.close()
    
    async def get_markets(self, active_only: bool = True) -> List[Dict]:
        """
        Fetch all available markets
        
        Returns:
            List of market dictionaries with metadata
        """
        endpoint = f"{self.REST_API}/markets"
        params = {"active": active_only}
        
        async with self.session.get(endpoint, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("markets", [])
            else:
                logger.error(f"Failed to fetch markets: {resp.status}")
                return []
    
    async def get_order_book(self, market_id: str) -> Dict:
        """
        Fetch L2 order book for a specific market
        
        Args:
            market_id: Polymarket market identifier
            
        Returns:
            Order book with bids and asks for YES/NO tokens
        """
        endpoint = f"{self.REST_API}/book"
        params = {"market": market_id}
        
        async with self.session.get(endpoint, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                logger.error(f"Failed to fetch order book: {resp.status}")
                return {}
    
    async def get_market_data(self, market_id: str) -> Optional[MarketData]:
        """
        Fetch complete market data for a single market
        
        Args:
            market_id: Polymarket market identifier
            
        Returns:
            MarketData object or None if fetch fails
        """
        try:
            # Fetch market metadata
            markets = await self.get_markets()
            market_meta = next((m for m in markets if m.get("id") == market_id), None)
            
            if not market_meta:
                logger.warning(f"Market {market_id} not found")
                return None
            
            # Fetch order book
            ob = await self.get_order_book(market_id)
            
            yes_bids = ob.get("bids", [])
            yes_asks = ob.get("asks", [])
            
            # Calculate best prices
            yes_bid = float(yes_bids[0]["price"]) if yes_bids else 0.0
            yes_ask = float(yes_asks[0]["price"]) if yes_asks else 1.0
            
            # NO price is inverse of YES
            no_bid = 1.0 - yes_ask if yes_ask else 0.0
            no_ask = 1.0 - yes_bid if yes_bid else 1.0
            
            # Mid prices
            yes_price = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else 0.5
            no_price = 1.0 - yes_price
            
            return MarketData(
                market_id=market_id,
                event_name=market_meta.get("description", "Unknown"),
                yes_price=yes_price,
                no_price=no_price,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
                volume_24h=market_meta.get("volume", 0),
                liquidity=market_meta.get("liquidity", 0),
                timestamp=datetime.utcnow()
            )
            
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            return None
    
    async def subscribe_trades(self, market_ids: List[str]):
        """
        WebSocket subscription to real-time trades
        
        Args:
            market_ids: List of market IDs to subscribe to
        """
        self.is_running = True
        
        try:
            async with websockets.connect(self.WS_API) as ws:
                self.ws_connection = ws
                
                # Subscribe to markets
                subscribe_msg = {
                    "type": "subscribe",
                    "markets": market_ids
                }
                await ws.send(json.dumps(subscribe_msg))
                
                logger.info(f"Subscribed to {len(market_ids)} markets")
                
                async for message in ws:
                    if not self.is_running:
                        break
                    
                    try:
                        data = json.loads(message)
                        await self._handle_trade_update(data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON received: {message}")
                        
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            
    async def _handle_trade_update(self, data: Dict):
        """Process incoming trade data and notify subscribers"""
        trade = Trade(
            market_id=data.get("market", ""),
            side=data.get("side", "").lower(),
            price=float(data.get("price", 0)),
            size=float(data.get("size", 0)),
            timestamp=datetime.utcnow(),
            trader_address=data.get("trader")
        )
        
        # Notify all subscribers
        for callback in self.subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(trade)
                else:
                    callback(trade)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")
    
    def on_trade(self, callback: Callable):
        """Register a callback for trade updates"""
        self.subscribers.append(callback)
        
    def stop(self):
        """Stop the WebSocket connection"""
        self.is_running = False


class KalshiClient:
    """
    Client for Kalshi API (event contracts exchange)
    
    API Docs: https://trading-api.readme.io/
    """
    
    REST_API = "https://trading-api.kalshi.com/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_markets(self) -> List[Dict]:
        """Fetch all available markets from Kalshi"""
        endpoint = f"{self.REST_API}/markets"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        
        async with self.session.get(endpoint, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("markets", [])
            return []
    
    async def get_orderbook(self, market_id: str) -> Dict:
        """Fetch order book for a specific market"""
        endpoint = f"{self.REST_API}/markets/{market_id}/orderbook"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        
        async with self.session.get(endpoint, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return {}


class DataAggregator:
    """
    Aggregates data from multiple prediction market platforms
    """
    
    def __init__(self):
        self.polymarket = PolymarketCLOBClient()
        self.kalshi = KalshiClient()
        self.cache: Dict[str, MarketData] = {}
        
    async def get_all_platforms_data(self, event_name: str) -> Dict[str, MarketData]:
        """
        Fetch market data for the same event across all platforms
        
        Args:
            event_name: Event to search for (e.g., "Bitcoin above 100k 2026")
            
        Returns:
            Dict mapping platform name to MarketData
        """
        results = {}
        
        async with self.polymarket, self.kalshi:
            # Fetch Polymarket data
            pm_markets = await self.polymarket.get_markets()
            pm_market = next(
                (m for m in pm_markets if event_name.lower() in m.get("description", "").lower()),
                None
            )
            if pm_market:
                pm_data = await self.polymarket.get_market_data(pm_market["id"])
                if pm_data:
                    results["polymarket"] = pm_data
            
            # Fetch Kalshi data
            kalshi_markets = await self.kalshi.get_markets()
            kalshi_market = next(
                (m for m in kalshi_markets if event_name.lower() in m.get("title", "").lower()),
                None
            )
            if kalshi_market:
                # Convert Kalshi format to MarketData
                results["kalshi"] = MarketData(
                    market_id=kalshi_market.get("id"),
                    event_name=kalshi_market.get("title"),
                    yes_price=kalshi_market.get("yes_price", 0.5),
                    no_price=kalshi_market.get("no_price", 0.5),
                    yes_bid=kalshi_market.get("yes_bid", 0),
                    yes_ask=kalshi_market.get("yes_ask", 1.0),
                    no_bid=kalshi_market.get("no_bid", 0),
                    no_ask=kalshi_market.get("no_ask", 1.0),
                    volume_24h=kalshi_market.get("volume", 0),
                    liquidity=kalshi_market.get("open_interest", 0),
                    timestamp=datetime.utcnow(),
                    source="kalshi"
                )
        
        return results


# Example usage
async def main():
    """Example of fetching market data"""
    async with PolymarketCLOBClient() as client:
        markets = await client.get_markets()
        print(f"Found {len(markets)} active markets")
        
        if markets:
            # Get data for first market
            market_id = markets[0]["id"]
            data = await client.get_market_data(market_id)
            if data:
                print(f"\nMarket: {data.event_name}")
                print(f"YES Price: {data.yes_price:.4f} (Bid: {data.yes_bid:.4f}, Ask: {data.yes_ask:.4f})")
                print(f"NO Price:  {data.no_price:.4f} (Bid: {data.no_bid:.4f}, Ask: {data.no_ask:.4f})")
                print(f"Volume 24h: ${data.volume_24h:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
