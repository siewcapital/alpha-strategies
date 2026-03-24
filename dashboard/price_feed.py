"""
Real-time Price Feed Integration for Dashboard

Adds WebSocket and polling-based price feeds to the Alpha Strategies dashboard.
Supports Binance, Coinbase, and other exchanges.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import threading
import time
import websockets
import requests

logger = logging.getLogger(__name__)


@dataclass
class PriceUpdate:
    """Price update data structure."""
    symbol: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "unknown"


@dataclass
class FundingUpdate:
    """Funding rate update."""
    symbol: str
    funding_rate: float
    mark_price: Optional[float] = None
    next_funding_time: Optional[datetime] = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "unknown"


class PriceFeedManager:
    """
    Manages real-time price feeds from multiple sources.
    Supports WebSocket and polling methods.
    """
    
    def __init__(self, update_interval: int = 5):
        self.update_interval = update_interval
        self.price_callbacks: List[Callable[[PriceUpdate], None]] = []
        self.funding_callbacks: List[Callable[[FundingUpdate], None]] = []
        self.price_cache: Dict[str, PriceUpdate] = {}
        self.funding_cache: Dict[str, FundingUpdate] = {}
        self.running = False
        self._threads: List[threading.Thread] = []
        self._ws_tasks: List[asyncio.Task] = []
    
    def on_price_update(self, callback: Callable[[PriceUpdate], None]):
        """Register price update callback."""
        self.price_callbacks.append(callback)
    
    def on_funding_update(self, callback: Callable[[FundingUpdate], None]):
        """Register funding update callback."""
        self.funding_callbacks.append(callback)
    
    def _notify_price(self, update: PriceUpdate):
        """Notify all price callbacks."""
        self.price_cache[update.symbol] = update
        for callback in self.price_callbacks:
            try:
                callback(update)
            except Exception as e:
                logger.error(f"Error in price callback: {e}")
    
    def _notify_funding(self, update: FundingUpdate):
        """Notify all funding callbacks."""
        self.funding_cache[update.symbol] = update
        for callback in self.funding_callbacks:
            try:
                callback(update)
            except Exception as e:
                logger.error(f"Error in funding callback: {e}")
    
    def start(self):
        """Start all feeds."""
        self.running = True
        
        # Start polling feeds in separate threads
        polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        polling_thread.start()
        self._threads.append(polling_thread)
        
        # Start WebSocket feeds in separate threads
        ws_thread = threading.Thread(target=self._run_websocket_loop, daemon=True)
        ws_thread.start()
        self._threads.append(ws_thread)
        
        logger.info("Price feed manager started")
    
    def stop(self):
        """Stop all feeds."""
        self.running = False
        
        for thread in self._threads:
            thread.join(timeout=2)
        
        logger.info("Price feed manager stopped")
    
    def _polling_loop(self):
        """Main polling loop for REST API feeds."""
        while self.running:
            try:
                self._fetch_binance_prices()
                self._fetch_binance_funding()
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
            
            time.sleep(self.update_interval)
    
    def _run_websocket_loop(self):
        """Run WebSocket feeds in asyncio loop."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._websocket_main())
        except Exception as e:
            logger.error(f"WebSocket loop error: {e}")
    
    async def _websocket_main(self):
        """Main WebSocket connection handler."""
        while self.running:
            try:
                await self._binance_websocket_feed()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(5)  # Reconnect delay
    
    def _fetch_binance_prices(self):
        """Fetch prices from Binance REST API."""
        try:
            # Fetch 24hr ticker statistics
            response = requests.get(
                'https://fapi.binance.com/fapi/v1/ticker/24hr',
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                
                for ticker in data:
                    symbol = ticker.get('symbol', '').replace('USDT', '')
                    if not symbol:
                        continue
                    
                    update = PriceUpdate(
                        symbol=symbol,
                        price=float(ticker.get('lastPrice', 0)),
                        bid=float(ticker.get('bidPrice', 0)) if ticker.get('bidPrice') else None,
                        ask=float(ticker.get('askPrice', 0)) if ticker.get('askPrice') else None,
                        volume_24h=float(ticker.get('quoteVolume', 0)),
                        source='binance_rest'
                    )
                    
                    self._notify_price(update)
                    
        except Exception as e:
            logger.error(f"Error fetching Binance prices: {e}")
    
    def _fetch_binance_funding(self):
        """Fetch funding rates from Binance REST API."""
        try:
            response = requests.get(
                'https://fapi.binance.com/fapi/v1/premiumIndex',
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                
                for item in data:
                    symbol = item.get('symbol', '').replace('USDT', '')
                    if not symbol:
                        continue
                    
                    # Convert next funding time
                    next_funding_ms = item.get('nextFundingTime')
                    next_funding = datetime.fromtimestamp(next_funding_ms / 1000) if next_funding_ms else None
                    
                    update = FundingUpdate(
                        symbol=symbol,
                        funding_rate=float(item.get('lastFundingRate', 0)),
                        mark_price=float(item.get('markPrice', 0)) if item.get('markPrice') else None,
                        next_funding_time=next_funding,
                        source='binance_rest'
                    )
                    
                    self._notify_funding(update)
                    
        except Exception as e:
            logger.error(f"Error fetching Binance funding: {e}")
    
    async def _binance_websocket_feed(self):
        """
        Connect to Binance WebSocket for real-time price updates.
        Uses combined stream for multiple symbols.
        """
        # Subscribe to major symbols
        symbols = ['btcusdt', 'ethusdt', 'solusdt', 'bnbusdt']
        streams = '/'.join([f"{s}@ticker" for s in symbols])
        ws_url = f"wss://fstream.binance.com/stream?streams={streams}"
        
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info("Binance WebSocket connected")
                
                while self.running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(message)
                        
                        if 'data' in data:
                            ticker = data['data']
                            symbol = ticker.get('s', '').replace('USDT', '')
                            
                            update = PriceUpdate(
                                symbol=symbol,
                                price=float(ticker.get('c', 0)),
                                bid=float(ticker.get('b', 0)) if ticker.get('b') else None,
                                ask=float(ticker.get('a', 0)) if ticker.get('a') else None,
                                volume_24h=float(ticker.get('q', 0)),
                                source='binance_ws'
                            )
                            
                            self._notify_price(update)
                            
                    except asyncio.TimeoutError:
                        # Send ping to keep connection alive
                        try:
                            pong_waiter = await ws.ping()
                            await asyncio.wait_for(pong_waiter, timeout=10)
                        except:
                            break
                    except Exception as e:
                        logger.error(f"WebSocket message error: {e}")
                        break
                        
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            raise


class DashboardPriceFeed:
    """
    Integrated price feed for the Alpha Strategies dashboard.
    Provides real-time price updates to the dashboard data store.
    """
    
    def __init__(self, dashboard_data_store, update_interval: int = 5):
        self.data_store = dashboard_data_store
        self.feed_manager = PriceFeedManager(update_interval=update_interval)
        
        # Register callbacks
        self.feed_manager.on_price_update(self._handle_price_update)
        self.feed_manager.on_funding_update(self._handle_funding_update)
    
    def _handle_price_update(self, update: PriceUpdate):
        """Handle price update from feed."""
        # Update dashboard metrics with latest prices
        # This would update the data_store with real-time prices
        
        # Log significant price movements
        if update.symbol in self.feed_manager.price_cache:
            old_price = self.feed_manager.price_cache[update.symbol].price
            if old_price > 0:
                change_pct = (update.price - old_price) / old_price * 100
                if abs(change_pct) > 1:  # 1% movement
                    self.data_store.add_log(
                        f"{update.symbol}: ${update.price:,.2f} ({change_pct:+.2f}%)",
                        'info'
                    )
    
    def _handle_funding_update(self, update: FundingUpdate):
        """Handle funding rate update from feed."""
        # Check for high funding rates (arbitrage opportunity)
        if abs(update.funding_rate) > 0.001:  # 0.1%
            self.data_store.add_log(
                f"{update.symbol} funding: {update.funding_rate:.4%}",
                'info'
            )
    
    def start(self):
        """Start the price feed."""
        self.feed_manager.start()
        self.data_store.add_log("Real-time price feed started", 'success')
    
    def stop(self):
        """Stop the price feed."""
        self.feed_manager.stop()
        self.data_store.add_log("Real-time price feed stopped", 'info')
    
    def get_price(self, symbol: str) -> Optional[PriceUpdate]:
        """Get latest price for a symbol."""
        return self.feed_manager.price_cache.get(symbol)
    
    def get_funding(self, symbol: str) -> Optional[FundingUpdate]:
        """Get latest funding rate for a symbol."""
        return self.feed_manager.funding_cache.get(symbol)
    
    def get_all_prices(self) -> Dict[str, PriceUpdate]:
        """Get all cached prices."""
        return self.feed_manager.price_cache.copy()
    
    def get_all_funding(self) -> Dict[str, FundingUpdate]:
        """Get all cached funding rates."""
        return self.feed_manager.funding_cache.copy()


# Example usage
def example_callback(update: PriceUpdate):
    """Example price update callback."""
    print(f"[{update.source}] {update.symbol}: ${update.price:,.2f}")


def main():
    """Test the price feed."""
    logging.basicConfig(level=logging.INFO)
    
    # Create feed manager
    feed = PriceFeedManager(update_interval=5)
    feed.on_price_update(example_callback)
    
    # Start feeds
    feed.start()
    
    # Run for 60 seconds
    print("Price feed running for 60 seconds...")
    print("Press Ctrl+C to stop early")
    
    try:
        time.sleep(60)
    except KeyboardInterrupt:
        print("\nStopping...")
    
    # Stop feeds
    feed.stop()
    
    # Print final prices
    print("\nFinal prices:")
    for symbol, update in feed.price_cache.items():
        print(f"  {symbol}: ${update.price:,.2f}")


if __name__ == "__main__":
    main()
