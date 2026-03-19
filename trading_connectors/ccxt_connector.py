"""
CCXT Exchange Connector for Cross-Exchange Funding Arbitrage
Provides live connectivity to Binance, Bybit, OKX, and other exchanges.
"""

import ccxt
import asyncio
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from pathlib import Path
import json

logger = logging.getLogger(__name__)


@dataclass
class ExchangeCredentials:
    """Exchange API credentials."""
    api_key: str
    api_secret: str
    passphrase: Optional[str] = None  # Required for OKX
    testnet: bool = True
    
    @classmethod
    def from_env(cls, exchange: str, testnet: bool = True) -> 'ExchangeCredentials':
        """Load credentials from environment variables."""
        import os
        prefix = f"{exchange.upper()}_"
        return cls(
            api_key=os.getenv(f"{prefix}API_KEY", ""),
            api_secret=os.getenv(f"{prefix}API_SECRET", ""),
            passphrase=os.getenv(f"{prefix}PASSPHRASE"),
            testnet=testnet
        )


@dataclass
class FundingRateData:
    """Funding rate data structure."""
    exchange: str
    symbol: str
    funding_rate: float
    timestamp: datetime
    next_funding_time: Optional[datetime] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return {
            'exchange': self.exchange,
            'symbol': self.symbol,
            'funding_rate': self.funding_rate,
            'timestamp': self.timestamp.isoformat(),
            'next_funding_time': self.next_funding_time.isoformat() if self.next_funding_time else None,
            'mark_price': self.mark_price,
            'index_price': self.index_price
        }


@dataclass
class TickerData:
    """Ticker/mark price data."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    last: float
    mark_price: float
    timestamp: datetime
    volume_24h: Optional[float] = None
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class CCXTExchangeConnector:
    """
    CCXT-based exchange connector for funding rate arbitrage.
    Supports Binance, Bybit, OKX, Gate.io, and others.
    """
    
    SUPPORTED_EXCHANGES = ['binance', 'bybit', 'okx', 'gateio', 'bitget', 'mexc']
    
    def __init__(
        self,
        exchange_id: str,
        credentials: Optional[ExchangeCredentials] = None,
        testnet: bool = True,
        rate_limit: bool = True
    ):
        self.exchange_id = exchange_id.lower()
        self.testnet = testnet
        self.credentials = credentials
        
        if self.exchange_id not in self.SUPPORTED_EXCHANGES:
            raise ValueError(f"Exchange {exchange_id} not supported. Use: {self.SUPPORTED_EXCHANGES}")
        
        # Initialize exchange
        self.exchange = self._init_exchange(rate_limit)
        self._markets: Optional[Dict] = None
        
        logger.info(f"Initialized {exchange_id} connector (testnet={testnet})")
    
    def _init_exchange(self, rate_limit: bool) -> ccxt.Exchange:
        """Initialize CCXT exchange instance."""
        exchange_class = getattr(ccxt, self.exchange_id)
        
        config = {
            'enableRateLimit': rate_limit,
            'options': {}
        }
        
        # Add credentials if provided
        if self.credentials:
            config['apiKey'] = self.credentials.api_key
            config['secret'] = self.credentials.api_secret
            
            if self.credentials.passphrase:
                config['password'] = self.credentials.passphrase
        
        # Configure testnet
        if self.testnet:
            if self.exchange_id == 'binance':
                config['options']['defaultType'] = 'future'
                # Use Binance testnet URLs
                config['urls'] = {
                    'api': {
                        'public': 'https://testnet.binancefuture.com/fapi/v1',
                        'private': 'https://testnet.binancefuture.com/fapi/v1'
                    }
                }
            elif self.exchange_id == 'bybit':
                config['options']['testnet'] = True
            elif self.exchange_id == 'okx':
                config['options']['defaultNetwork'] = 'test'
        
        exchange = exchange_class(config)
        
        # Load markets
        exchange.load_markets()
        
        return exchange
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to CCXT unified format."""
        # If already in unified format, return as-is
        if ':' in symbol and '/' in symbol:
            return symbol
        
        # Handle 'BTCUSDT' format
        if '/' not in symbol and 'USDT' in symbol:
            base = symbol.replace('USDT', '')
            return f"{base}/USDT:USDT"
        
        # Handle 'BTC/USDT' format
        if '/' in symbol and ':' not in symbol:
            return f"{symbol}:USDT"
        
        return symbol
    
    async def get_funding_rate(self, symbol: str) -> Optional[FundingRateData]:
        """
        Fetch current funding rate for a symbol.
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT', 'BTC/USDT:USDT')
        
        Returns:
            FundingRateData or None if error
        """
        try:
            symbol = self._normalize_symbol(symbol)
            
            # fetch_funding_rate is synchronous in CCXT
            funding = self.exchange.fetch_funding_rate(symbol)
            
            return FundingRateData(
                exchange=self.exchange_id,
                symbol=symbol,
                funding_rate=funding.get('fundingRate', 0.0),
                timestamp=datetime.fromtimestamp(funding['timestamp'] / 1000),
                next_funding_time=datetime.fromtimestamp(
                    funding.get('fundingTimestamp', 0) / 1000
                ) if funding.get('fundingTimestamp') else None,
                mark_price=funding.get('markPrice'),
                index_price=funding.get('indexPrice')
            )
        except Exception as e:
            logger.error(f"Error fetching funding rate for {symbol}: {e}")
            return None
    
    async def get_all_funding_rates(self) -> List[FundingRateData]:
        """Fetch funding rates for all perpetual futures."""
        try:
            # fetch_funding_rates is synchronous in CCXT
            funding_rates = self.exchange.fetch_funding_rates()
            
            results = []
            for symbol, data in funding_rates.items():
                # Filter for USDT perpetuals only
                if ':USDT' in symbol or 'USDT' in symbol:
                    results.append(FundingRateData(
                        exchange=self.exchange_id,
                        symbol=symbol,
                        funding_rate=data.get('fundingRate', 0.0),
                        timestamp=datetime.fromtimestamp(data['timestamp'] / 1000),
                        next_funding_time=datetime.fromtimestamp(
                            data.get('fundingTimestamp', 0) / 1000
                        ) if data.get('fundingTimestamp') else None,
                        mark_price=data.get('markPrice'),
                        index_price=data.get('indexPrice')
                    ))
            
            return results
        except Exception as e:
            logger.error(f"Error fetching all funding rates: {e}")
            return []
    
    async def get_ticker(self, symbol: str) -> Optional[TickerData]:
        """Fetch current ticker data."""
        try:
            symbol = self._normalize_symbol(symbol)
            
            # fetch_ticker is synchronous in CCXT
            ticker = self.exchange.fetch_ticker(symbol)
            
            return TickerData(
                exchange=self.exchange_id,
                symbol=symbol,
                bid=ticker.get('bid', 0.0),
                ask=ticker.get('ask', 0.0),
                last=ticker.get('last', 0.0),
                mark_price=ticker.get('vwap', ticker.get('last', 0.0)),
                timestamp=datetime.fromtimestamp(ticker['timestamp'] / 1000),
                volume_24h=ticker.get('quoteVolume')
            )
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None
    
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1h',
        since: Optional[int] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data.
        
        Args:
            symbol: Trading pair
            timeframe: Candle timeframe (1m, 5m, 1h, 4h, 1d)
            since: Start timestamp in milliseconds
            limit: Number of candles
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            symbol = self._normalize_symbol(symbol)
            
            # fetch_ohlcv is synchronous in CCXT
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol}: {e}")
            return pd.DataFrame()
    
    async def create_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Create a limit order.
        
        Args:
            symbol: Trading pair
            side: 'buy' or 'sell'
            amount: Order size
            price: Limit price
            params: Additional order parameters
        
        Returns:
            Order dict or None
        """
        try:
            symbol = self._normalize_symbol(symbol)
            
            params = params or {}
            order = await self.exchange.create_limit_order(
                symbol, side, amount, price, params
            )
            
            logger.info(f"Created {side} limit order: {order['id']}")
            return order
        except Exception as e:
            logger.error(f"Error creating order: {e}")
            return None
    
    async def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Create a market order."""
        try:
            symbol = self._normalize_symbol(symbol)
            
            params = params or {}
            order = await self.exchange.create_market_order(
                symbol, side, amount, params
            )
            
            logger.info(f"Created {side} market order: {order['id']}")
            return order
        except Exception as e:
            logger.error(f"Error creating market order: {e}")
            return None
    
    async def get_balance(self) -> Dict[str, Any]:
        """Fetch account balance."""
        try:
            balance = await self.exchange.fetch_balance()
            return {
                'total': balance.get('total', {}),
                'free': balance.get('free', {}),
                'used': balance.get('used', {}),
                'timestamp': datetime.now()
            }
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return {}
    
    async def get_positions(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        """Fetch open positions."""
        try:
            positions = await self.exchange.fetch_positions(symbols)
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    async def close(self):
        """Close exchange connection."""
        # CCXT doesn't have an async close method
        # Just clean up the exchange reference
        self.exchange = None


class MultiExchangeConnector:
    """
    Manages connections to multiple exchanges.
    Provides unified interface for funding arbitrage.
    """
    
    def __init__(self, testnet: bool = True):
        self.connectors: Dict[str, CCXTExchangeConnector] = {}
        self.testnet = testnet
    
    def add_exchange(
        self,
        exchange_id: str,
        credentials: Optional[ExchangeCredentials] = None
    ):
        """Add an exchange connection."""
        connector = CCXTExchangeConnector(
            exchange_id=exchange_id,
            credentials=credentials,
            testnet=self.testnet
        )
        self.connectors[exchange_id] = connector
        logger.info(f"Added {exchange_id} to multi-exchange connector")
    
    async def get_all_funding_rates(self) -> Dict[str, List[FundingRateData]]:
        """Fetch funding rates from all connected exchanges."""
        results = {}
        
        for exchange_id, connector in self.connectors.items():
            rates = await connector.get_all_funding_rates()
            results[exchange_id] = rates
        
        return results
    
    async def get_funding_differentials(
        self,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Calculate funding rate differentials across exchanges.
        
        Returns:
            DataFrame with funding rates and differentials
        """
        all_rates = await self.get_all_funding_rates()
        
        # Build DataFrame
        rows = []
        for exchange_id, rates in all_rates.items():
            for rate in rates:
                symbol_clean = rate.symbol.replace('/USDT:USDT', '')
                if symbols and symbol_clean not in symbols:
                    continue
                
                rows.append({
                    'exchange': exchange_id,
                    'symbol': symbol_clean,
                    'funding_rate': rate.funding_rate,
                    'funding_rate_pct': rate.funding_rate * 100,
                    'mark_price': rate.mark_price,
                    'next_funding': rate.next_funding_time,
                    'timestamp': rate.timestamp
                })
        
        df = pd.DataFrame(rows)
        
        if df.empty:
            return df
        
        # Calculate differentials
        differentials = []
        for symbol in df['symbol'].unique():
            symbol_df = df[df['symbol'] == symbol]
            if len(symbol_df) < 2:
                continue
            
            max_rate = symbol_df['funding_rate'].max()
            min_rate = symbol_df['funding_rate'].min()
            diff = max_rate - min_rate
            
            max_exchange = symbol_df.loc[symbol_df['funding_rate'].idxmax(), 'exchange']
            min_exchange = symbol_df.loc[symbol_df['funding_rate'].idxmin(), 'exchange']
            
            differentials.append({
                'symbol': symbol,
                'differential': diff,
                'differential_bps': diff * 10000,  # basis points
                'long_exchange': min_exchange,
                'short_exchange': max_exchange,
                'long_rate': min_rate,
                'short_rate': max_rate
            })
        
        return pd.DataFrame(differentials)
    
    async def close_all(self):
        """Close all exchange connections."""
        for connector in self.connectors.values():
            await connector.close()


# Example usage
async def main():
    """Example: Fetch funding rates from Binance testnet."""
    # Initialize connector (testnet - no real credentials needed for public data)
    connector = CCXTExchangeConnector('binance', testnet=True)
    
    # Fetch BTC funding rate
    funding = await connector.get_funding_rate('BTCUSDT')
    if funding:
        print(f"BTC Funding Rate: {funding.funding_rate:.6%}")
        print(f"Next Funding: {funding.next_funding_time}")
    
    # Fetch all funding rates
    all_rates = await connector.get_all_funding_rates()
    print(f"\nFetched {len(all_rates)} funding rates")
    
    # Get OHLCV data
    ohlcv = await connector.get_ohlcv('BTCUSDT', timeframe='1h', limit=24)
    print(f"\nFetched {len(ohlcv)} candles")
    print(ohlcv.head())
    
    await connector.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
