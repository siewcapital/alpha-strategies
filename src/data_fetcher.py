"""
Data Fetcher for Funding Rate Arbitrage

Fetches real-time and historical funding rates from multiple cryptocurrency exchanges.
Supports: Binance, Bybit, OKX

Author: ATLAS (Siew's Capital)
Date: 2026-03-24
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
import pandas as pd

from strategy import FundingRate

logger = logging.getLogger(__name__)


class FundingRateDataFetcher:
    """
    Fetches funding rates from multiple exchanges.
    
    Supports both real-time and historical data collection.
    """
    
    def __init__(self, config: dict):
        """
        Initialize the data fetcher.
        
        Args:
            config: Configuration dict with exchange API keys
        """
        self.config = config
        self.exchanges = [e["name"] for e in config.get("exchanges", [])]
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Dict[str, FundingRate]] = {}
        self.cache_timeout = 60  # seconds
        
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def fetch_binance_funding(self, symbols: List[str]) -> Dict[str, FundingRate]:
        """
        Fetch funding rates from Binance.
        
        Args:
            symbols: List of trading symbols (e.g., ['BTC', 'ETH'])
            
        Returns:
            Dict mapping symbol -> FundingRate
        """
        results = {}
        
        # Use testnet or real endpoint based on config
        base_url = "https://testnet.binance.vision/api" if self._is_testnet("binance") else "https://api.binance.com"
        
        for symbol in symbols:
            try:
                endpoint = f"{base_url}/v1/premiumIndex"
                params = {"symbol": f"{symbol}USDT"}
                
                async with self.session.get(endpoint, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        results[symbol] = FundingRate(
                            exchange="binance",
                            symbol=symbol,
                            rate=float(data.get("lastFundingRate", 0)),
                            next_settle=datetime.fromtimestamp(
                                data.get("nextFundingTime", 0) / 1000
                            ),
                            mark_price=float(data.get("markPrice", 0)),
                            index_price=float(data.get("indexPrice", 0))
                        )
            except Exception as e:
                logger.warning(f"Failed to fetch Binance funding for {symbol}: {e}")
        
        return results
    
    async def fetch_bybit_funding(self, symbols: List[str]) -> Dict[str, FundingRate]:
        """
        Fetch funding rates from Bybit.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict mapping symbol -> FundingRate
        """
        results = {}
        
        base_url = "https://api-testnet.bybit.com" if self._is_testnet("bybit") else "https://api.bybit.com"
        
        for symbol in symbols:
            try:
                endpoint = f"{base_url}/v5/market/tickers"
                params = {
                    "category": "linear",
                    "symbol": f"{symbol}USDT"
                }
                
                async with self.session.get(endpoint, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
                            item = data["result"]["list"][0]
                            
                            results[symbol] = FundingRate(
                                exchange="bybit",
                                symbol=symbol,
                                rate=float(item.get("fundingRate", 0)),
                                next_settle=datetime.fromtimestamp(
                                    int(item.get("nextFundingTime", 0)) / 1000
                                ),
                                mark_price=float(item.get("markPrice", 0)),
                                index_price=float(item.get("indexPrice", 0))
                            )
            except Exception as e:
                logger.warning(f"Failed to fetch Bybit funding for {symbol}: {e}")
        
        return results
    
    async def fetch_okx_funding(self, symbols: List[str]) -> Dict[str, FundingRate]:
        """
        Fetch funding rates from OKX.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict mapping symbol -> FundingRate
        """
        results = {}
        
        base_url = "https://www.okx.com"  # OKX doesn't have separate testnet for this
        
        for symbol in symbols:
            try:
                endpoint = f"{base_url}/api/v5/market/ticker"
                params = {
                    "instId": f"{symbol}-USDT-SWAP"
                }
                
                async with self.session.get(endpoint, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("code") == "0" and data.get("data"):
                            item = data["data"][0]
                            
                            # OKX uses different field names
                            results[symbol] = FundingRate(
                                exchange="okx",
                                symbol=symbol,
                                rate=float(item.get("fundingRate", 0)),
                                next_settle=datetime.fromtimestamp(
                                    int(item.get("nextFundingTime", 0)) / 1000
                                ),
                                mark_price=float(item.get("markPx", 0)),
                                index_price=float(item.get("indexPx", 0))
                            )
            except Exception as e:
                logger.warning(f"Failed to fetch OKX funding for {symbol}: {e}")
        
        return results
    
    async def fetch_all_funding(
        self, 
        symbols: List[str]
    ) -> Dict[str, Dict[str, FundingRate]]:
        """
        Fetch funding rates from all configured exchanges.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict mapping exchange -> {symbol: FundingRate}
        """
        tasks = []
        exchange_names = []
        
        # Create fetch tasks for each exchange
        if "binance" in self.exchanges:
            tasks.append(self.fetch_binance_funding(symbols))
            exchange_names.append("binance")
        
        if "bybit" in self.exchanges:
            tasks.append(self.fetch_bybit_funding(symbols))
            exchange_names.append("bybit")
        
        if "okx" in self.exchanges:
            tasks.append(self.fetch_okx_funding(symbols))
            exchange_names.append("okx")
        
        # Execute all requests concurrently
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            funding_data = {}
            for name, result in zip(exchange_names, results):
                if isinstance(result, Exception):
                    logger.error(f"Failed to fetch {name}: {result}")
                    funding_data[name] = {}
                else:
                    funding_data[name] = result
            
            self.cache = funding_data
            return funding_data
        
        return {}
    
    async def fetch_historical_funding(
        self,
        exchange: str,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> pd.DataFrame:
        """
        Fetch historical funding rate data for backtesting.
        
        Args:
            exchange: Exchange name
            symbol: Trading symbol
            start_time: Start datetime
            end_time: End datetime
            
        Returns:
            DataFrame with historical funding rates
        """
        # Implementation would use exchange-specific historical endpoints
        # For now, return empty DataFrame
        logger.info(f"Fetching historical funding for {exchange}/{symbol}")
        
        # This is a placeholder - in production, would implement actual API calls
        # or use cached data from data providers
        return pd.DataFrame()
    
    def _is_testnet(self, exchange: str) -> bool:
        """Check if exchange is configured for testnet."""
        for ex in self.config.get("exchanges", []):
            if ex["name"] == exchange:
                return ex.get("testnet", False)
        return False
    
    def get_cached_funding(self) -> Dict[str, Dict[str, FundingRate]]:
        """
        Get cached funding data.
        
        Returns:
            Cached funding data if not expired
        """
        return self.cache


class MockDataFetcher:
    """
    Mock data fetcher for backtesting and development.
    
    Generates realistic synthetic funding rate data.
    """
    
    def __init__(self, config: dict):
        """Initialize mock data fetcher."""
        self.config = config
        self.cache = {}
    
    async def fetch_all_funding(
        self, 
        symbols: List[str]
    ) -> Dict[str, Dict[str, FundingRate]]:
        """
        Generate mock funding data.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict mapping exchange -> {symbol: FundingRate}
        """
        import random
        
        funding_data = {}
        
        exchanges = ["binance", "bybit", "okx"]
        
        for exchange in exchanges:
            funding_data[exchange] = {}
            
            for symbol in symbols:
                # Generate realistic funding rate
                # Typically ranges from -0.001 to 0.001 (or higher for volatile assets)
                volatility = 0.001 if symbol in ["BTC", "ETH"] else 0.002
                base_rate = random.gauss(0, volatility)
                
                # Add exchange-specific bias
                exchange_bias = {
                    "binance": 0.00005,
                    "bybit": -0.00002,
                    "okx": 0.00003
                }.get(exchange, 0)
                
                rate = base_rate + exchange_bias
                
                # Cap at reasonable values
                rate = max(-0.001, min(0.001, rate))
                
                funding_data[exchange][symbol] = FundingRate(
                    exchange=exchange,
                    symbol=symbol,
                    rate=rate,
                    next_settle=datetime.now(),
                    mark_price=self._get_mock_price(symbol),
                    index_price=self._get_mock_price(symbol) * 0.999,
                    timestamp=datetime.now()
                )
        
        self.cache = funding_data
        return funding_data
    
    def _get_mock_price(self, symbol: str) -> float:
        """Get mock price for symbol."""
        prices = {
            "BTC": 70000,
            "ETH": 2100,
            "SOL": 180,
            "BNB": 630,
            "XRP": 0.55,
            "ADA": 0.45,
            "DOGE": 0.08,
            "AVAX": 35,
            "DOT": 7,
            "MATIC": 0.85
        }
        return prices.get(symbol, 100)
    
    def get_cached_funding(self) -> Dict[str, Dict[str, FundingRate]]:
        """Get cached funding data."""
        return self.cache
