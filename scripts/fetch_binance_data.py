"""
Binance Historical Data Fetcher
Fetches real SOL (and other) OHLCV data from Binance API.
"""

import asyncio
import aiohttp
import pandas as pd
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import logging
import json

logger = logging.getLogger(__name__)


class BinanceDataFetcher:
    """
    Fetches historical OHLCV data from Binance API.
    Supports spot and futures markets.
    """
    
    BASE_URL = "https://api.binance.com"
    FUTURES_URL = "https://fapi.binance.com"
    
    TIMEFRAME_INTERVALS = {
        '1m': 60,
        '3m': 180,
        '5m': 300,
        '15m': 900,
        '30m': 1800,
        '1h': 3600,
        '2h': 7200,
        '4h': 14400,
        '6h': 21600,
        '8h': 28800,
        '12h': 43200,
        '1d': 86400,
        '3d': 259200,
        '1w': 604800,
        '1M': 2592000
    }
    
    def __init__(self, use_futures: bool = True, rate_limit_delay: float = 0.1):
        self.use_futures = use_futures
        self.base_url = self.FUTURES_URL if use_futures else self.BASE_URL
        self.rate_limit_delay = rate_limit_delay
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make API request with rate limiting."""
        url = f"{self.base_url}{endpoint}"
        
        await asyncio.sleep(self.rate_limit_delay)
        
        async with self.session.get(url, params=params) as response:
            if response.status == 429:
                logger.warning("Rate limited, waiting 60 seconds...")
                await asyncio.sleep(60)
                return await self._make_request(endpoint, params)
            
            response.raise_for_status()
            return await response.json()
    
    async def fetch_klines(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """
        Fetch kline/candlestick data.
        
        Args:
            symbol: Trading pair (e.g., 'SOLUSDT')
            timeframe: Candle interval (1m, 5m, 1h, 4h, 1d, etc.)
            start_time: Start datetime
            end_time: End datetime
            limit: Max candles per request (max 1000)
        
        Returns:
            DataFrame with OHLCV data
        """
        endpoint = "/fapi/v1/klines" if self.use_futures else "/api/v3/klines"
        
        params = {
            'symbol': symbol.upper(),
            'interval': timeframe,
            'limit': min(limit, 1000)
        }
        
        if start_time:
            params['startTime'] = int(start_time.timestamp() * 1000)
        if end_time:
            params['endTime'] = int(end_time.timestamp() * 1000)
        
        data = await self._make_request(endpoint, params)
        
        if not data:
            return pd.DataFrame()
        
        # Parse kline data
        # Format: [open_time, open, high, low, close, volume, close_time, ...]
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        # Convert types
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 
                       'quote_volume', 'taker_buy_base', 'taker_buy_quote']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
        
        df.set_index('open_time', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades']]
        
        return df
    
    async def fetch_historical_data(
        self,
        symbol: str,
        timeframe: str,
        days: int = 365,
        end_date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Fetch extended historical data by paginating through API.
        
        Args:
            symbol: Trading pair
            timeframe: Candle interval
            days: Number of days to fetch
            end_date: End date (defaults to now)
        
        Returns:
            DataFrame with full OHLCV history
        """
        end_date = end_date or datetime.now()
        start_date = end_date - timedelta(days=days)
        
        logger.info(f"Fetching {days} days of {symbol} {timeframe} data...")
        
        all_data = []
        current_start = start_date
        
        while current_start < end_date:
            chunk_end = current_start + timedelta(days=30)  # Fetch 30 days at a time
            if chunk_end > end_date:
                chunk_end = end_date
            
            df = await self.fetch_klines(
                symbol=symbol,
                timeframe=timeframe,
                start_time=current_start,
                end_time=chunk_end,
                limit=1000
            )
            
            if df.empty:
                logger.warning(f"No data for {current_start} to {chunk_end}")
                break
            
            all_data.append(df)
            
            # Move to next chunk
            last_timestamp = df.index[-1]
            current_start = last_timestamp + timedelta(hours=1)
            
            logger.info(f"Fetched {len(df)} rows ({last_timestamp.date()})")
            
            # Check if we've reached the end
            if current_start >= end_date or len(df) < 100:
                break
        
        if not all_data:
            return pd.DataFrame()
        
        combined = pd.concat(all_data)
        combined = combined[~combined.index.duplicated(keep='first')]
        combined.sort_index(inplace=True)
        
        logger.info(f"Total rows fetched: {len(combined)}")
        logger.info(f"Date range: {combined.index[0]} to {combined.index[-1]}")
        
        return combined
    
    async def fetch_funding_rates(
        self,
        symbol: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """
        Fetch historical funding rates.
        
        Args:
            symbol: Trading pair (futures only)
            start_time: Start datetime
            end_time: End datetime
            limit: Max records
        
        Returns:
            DataFrame with funding rate history
        """
        if not self.use_futures:
            raise ValueError("Funding rates only available for futures")
        
        params = {
            'symbol': symbol.upper(),
            'limit': min(limit, 1000)
        }
        
        if start_time:
            params['startTime'] = int(start_time.timestamp() * 1000)
        if end_time:
            params['endTime'] = int(end_time.timestamp() * 1000)
        
        data = await self._make_request("/fapi/v1/fundingRate", params)
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
        df['fundingRate'] = pd.to_numeric(df['fundingRate'])
        df.set_index('fundingTime', inplace=True)
        
        return df
    
    async def get_exchange_info(self) -> Dict:
        """Get exchange info including available symbols."""
        endpoint = "/fapi/v1/exchangeInfo" if self.use_futures else "/api/v3/exchangeInfo"
        return await self._make_request(endpoint)
    
    async def get_available_symbols(self) -> List[str]:
        """Get list of available trading symbols."""
        info = await self.get_exchange_info()
        symbols = [s['symbol'] for s in info.get('symbols', []) if s.get('status') == 'TRADING']
        return symbols


async def fetch_and_save_sol_data(
    output_dir: Path = None,
    days: int = 730,
    timeframes: List[str] = ['1h', '4h', '1d']
) -> Dict[str, Path]:
    """
    Fetch and save SOL historical data from Binance.
    
    Args:
        output_dir: Directory to save data (defaults to ./data)
        days: Number of days of history
        timeframes: List of timeframes to fetch
    
    Returns:
        Dict mapping timeframe to file path
    """
    output_dir = output_dir or Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    
    results = {}
    
    async with BinanceDataFetcher(use_futures=True) as fetcher:
        for tf in timeframes:
            logger.info(f"\nFetching SOLUSDT {tf} data ({days} days)...")
            
            df = await fetcher.fetch_historical_data(
                symbol='SOLUSDT',
                timeframe=tf,
                days=days
            )
            
            if not df.empty:
                # Save to CSV
                filename = f"SOLUSDT_{tf}_{days}d.csv"
                filepath = output_dir / filename
                df.to_csv(filepath)
                logger.info(f"Saved to {filepath} ({len(df)} rows)")
                results[tf] = filepath
                
                # Print statistics
                print(f"\n{tf} Data Summary:")
                print(f"  Rows: {len(df)}")
                print(f"  Date Range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
                print(f"  Price Range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
                print(f"  Avg Volume: {df['volume'].mean():,.0f} SOL")
                
                # Also save as pickle for faster loading
                pickle_path = filepath.with_suffix('.pkl')
                df.to_pickle(pickle_path)
    
    return results


async def fetch_funding_rate_history(
    output_dir: Path = None,
    days: int = 365
) -> Path:
    """Fetch and save SOL funding rate history."""
    output_dir = output_dir or Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    
    async with BinanceDataFetcher(use_futures=True) as fetcher:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        logger.info(f"\nFetching SOL funding rate history ({days} days)...")
        
        df = await fetcher.fetch_funding_rates(
            symbol='SOLUSDT',
            start_time=start_date,
            end_time=end_date,
            limit=1000
        )
        
        if not df.empty:
            filename = f"SOLUSDT_funding_{days}d.csv"
            filepath = output_dir / filename
            df.to_csv(filepath)
            
            logger.info(f"Saved to {filepath} ({len(df)} records)")
            print(f"\nFunding Rate Summary:")
            print(f"  Records: {len(df)}")
            print(f"  Mean Rate: {df['fundingRate'].mean():.6%}")
            print(f"  Max Rate: {df['fundingRate'].max():.6%}")
            print(f"  Min Rate: {df['fundingRate'].min():.6%}")
            
            return filepath
        
    return None


# CLI Interface
if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description='Fetch Binance historical data')
    parser.add_argument('--symbol', default='SOLUSDT', help='Trading pair symbol')
    parser.add_argument('--timeframes', nargs='+', default=['1h', '4h', '1d'], help='Timeframes to fetch')
    parser.add_argument('--days', type=int, default=730, help='Days of history')
    parser.add_argument('--output', default='../data', help='Output directory')
    parser.add_argument('--funding', action='store_true', help='Also fetch funding rates')
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True, parents=True)
    
    async def main():
        # Fetch OHLCV data
        results = await fetch_and_save_sol_data(
            output_dir=output_dir,
            days=args.days,
            timeframes=args.timeframes
        )
        
        # Fetch funding rates if requested
        if args.funding:
            await fetch_funding_rate_history(output_dir, days=min(args.days, 365))
        
        print("\n" + "="*50)
        print("DATA FETCH COMPLETE")
        print("="*50)
        print(f"\nFiles saved to: {output_dir}")
        for tf, path in results.items():
            print(f"  - {path.name}")
    
    asyncio.run(main())
