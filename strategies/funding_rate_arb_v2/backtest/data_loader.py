"""
Historical Data Loader

Fetches and caches historical funding rates from cryptocurrency exchanges.
Supports Binance, Bybit, OKX, and dYdX.

Author: ATLAS
Date: March 30, 2026
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import os

import pandas as pd
import numpy as np

# Optional CCXT import
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    logging.warning("CCXT not available. Install with: pip install ccxt")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FundingDataLoader:
    """
    Loads historical funding rate data from exchanges.
    Caches data locally to minimize API calls.
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize exchange connections
        self.exchanges: Dict[str, any] = {}
        if CCXT_AVAILABLE:
            self._init_exchanges()
    
    def _init_exchanges(self):
        """Initialize CCXT exchange connections."""
        # Binance
        self.exchanges['binance'] = ccxt.binance({
            'options': {'defaultType': 'future'},
            'enableRateLimit': True
        })
        
        # Bybit
        self.exchanges['bybit'] = ccxt.bybit({
            'options': {'defaultType': 'linear'},
            'enableRateLimit': True
        })
        
        # OKX
        self.exchanges['okx'] = ccxt.okx({
            'options': {'defaultType': 'swap'},
            'enableRateLimit': True
        })
        
        logger.info(f"Initialized {len(self.exchanges)} exchange connections")
    
    def _get_cache_path(self, exchange: str, symbol: str, year: int) -> Path:
        """Get cache file path for exchange-symbol-year."""
        cache_dir = self.data_dir / "raw"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{exchange}_{symbol}_{year}.parquet"
    
    def _load_cached(self, exchange: str, symbol: str, year: int) -> Optional[pd.DataFrame]:
        """Load cached data if available."""
        cache_path = self._get_cache_path(exchange, symbol, year)
        if cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                logger.debug(f"Loaded cached data: {cache_path}")
                return df
            except Exception as e:
                logger.warning(f"Failed to load cache {cache_path}: {e}")
        return None
    
    def _save_cache(self, df: pd.DataFrame, exchange: str, symbol: str, year: int):
        """Save data to cache."""
        cache_path = self._get_cache_path(exchange, symbol, year)
        try:
            df.to_parquet(cache_path, compression='zstd')
            logger.debug(f"Saved cache: {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to save cache {cache_path}: {e}")
    
    def fetch_binance_funding(self, symbol: str, start_time: datetime, 
                             end_time: datetime) -> pd.DataFrame:
        """
        Fetch funding rate history from Binance.
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            start_time: Start datetime
            end_time: End datetime
            
        Returns:
            DataFrame with columns [timestamp, funding_rate]
        """
        if not CCXT_AVAILABLE or 'binance' not in self.exchanges:
            raise RuntimeError("CCXT Binance not available")
        
        exchange = self.exchanges['binance']
        all_data = []
        
        # Convert to milliseconds
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        
        # Binance returns max 1000 records per request
        # Funding rates are every 8 hours = 3 per day
        # 1000 records ≈ 333 days
        current_start = start_ms
        
        while current_start < end_ms:
            try:
                params = {
                    'symbol': symbol,
                    'startTime': current_start,
                    'limit': 1000
                }
                
                response = exchange.fapiPublic_get_fundingrate(params)
                
                if not response:
                    break
                
                for item in response:
                    all_data.append({
                        'timestamp': pd.to_datetime(item['fundingTime'], unit='ms'),
                        'exchange': 'binance',
                        'symbol': symbol,
                        'funding_rate': float(item['fundingRate'])
                    })
                
                # Move to next batch
                last_time = response[-1]['fundingTime']
                current_start = last_time + 1
                
                # Rate limiting
                time.sleep(exchange.rateLimit / 1000)
                
            except Exception as e:
                logger.error(f"Error fetching Binance funding: {e}")
                break
        
        df = pd.DataFrame(all_data)
        if not df.empty:
            df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
    
    def fetch_bybit_funding(self, symbol: str, start_time: datetime,
                           end_time: datetime) -> pd.DataFrame:
        """
        Fetch funding rate history from Bybit.
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            start_time: Start datetime
            end_time: End datetime
            
        Returns:
            DataFrame with columns [timestamp, funding_rate]
        """
        if not CCXT_AVAILABLE or 'bybit' not in self.exchanges:
            raise RuntimeError("CCXT Bybit not available")
        
        exchange = self.exchanges['bybit']
        all_data = []
        
        # Bybit V5 API
        category = 'linear'  # USDT perpetuals
        
        current_start = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        
        while current_start < end_ms:
            try:
                params = {
                    'category': category,
                    'symbol': symbol,
                    'startTime': current_start,
                    'limit': 200
                }
                
                response = exchange.publicGetV5MarketFundingHistory(params)
                
                if not response or 'result' not in response or 'list' not in response['result']:
                    break
                
                items = response['result']['list']
                if not items:
                    break
                
                for item in items:
                    all_data.append({
                        'timestamp': pd.to_datetime(item['fundingRateTimestamp'], unit='ms'),
                        'exchange': 'bybit',
                        'symbol': symbol,
                        'funding_rate': float(item['fundingRate'])
                    })
                
                # Move to next batch
                last_time = int(items[-1]['fundingRateTimestamp'])
                current_start = last_time + 1
                
                # Rate limiting
                time.sleep(exchange.rateLimit / 1000)
                
            except Exception as e:
                logger.error(f"Error fetching Bybit funding: {e}")
                break
        
        df = pd.DataFrame(all_data)
        if not df.empty:
            df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
    
    def fetch_okx_funding(self, symbol: str, start_time: datetime,
                         end_time: datetime) -> pd.DataFrame:
        """
        Fetch funding rate history from OKX.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USDT-SWAP')
            start_time: Start datetime
            end_time: End datetime
            
        Returns:
            DataFrame with columns [timestamp, funding_rate]
        """
        if not CCXT_AVAILABLE or 'okx' not in self.exchanges:
            raise RuntimeError("CCXT OKX not available")
        
        exchange = self.exchanges['okx']
        all_data = []
        
        # OKX uses different symbol format
        okx_symbol = symbol.replace('USDT', '-USDT-SWAP')
        
        current_start = start_time
        
        while current_start < end_time:
            try:
                params = {
                    'instId': okx_symbol,
                    'before': '',
                    'after': str(int(current_start.timestamp() * 1000)),
                    'limit': '100'
                }
                
                response = exchange.publicGetPublicFundingRateHistory(params)
                
                if not response or 'data' not in response:
                    break
                
                items = response['data']
                if not items:
                    break
                
                for item in items:
                    all_data.append({
                        'timestamp': pd.to_datetime(item['fundingTime'], unit='ms'),
                        'exchange': 'okx',
                        'symbol': symbol,
                        'funding_rate': float(item['fundingRate'])
                    })
                
                # Move to next batch
                last_time = pd.to_datetime(items[-1]['fundingTime'], unit='ms')
                current_start = last_time + timedelta(hours=8)
                
                # Rate limiting
                time.sleep(exchange.rateLimit / 1000)
                
            except Exception as e:
                logger.error(f"Error fetching OKX funding: {e}")
                break
        
        df = pd.DataFrame(all_data)
        if not df.empty:
            df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
    
    def fetch_funding_history(self, exchange: str, symbol: str,
                             start_time: datetime, end_time: datetime,
                             use_cache: bool = True) -> pd.DataFrame:
        """
        Fetch funding history for any supported exchange.
        
        Args:
            exchange: Exchange name ('binance', 'bybit', 'okx')
            symbol: Trading pair symbol
            start_time: Start datetime
            end_time: End datetime
            use_cache: Whether to use local cache
            
        Returns:
            DataFrame with funding rate history
        """
        # Check cache for each year in range
        if use_cache:
            years = range(start_time.year, end_time.year + 1)
            cached_data = []
            
            for year in years:
                cached = self._load_cached(exchange, symbol, year)
                if cached is not None:
                    cached_data.append(cached)
            
            if cached_data:
                df = pd.concat(cached_data, ignore_index=True)
                df = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]
                if not df.empty:
                    logger.info(f"Loaded {len(df)} cached records for {exchange} {symbol}")
                    return df
        
        # Fetch from API
        logger.info(f"Fetching funding history for {exchange} {symbol}...")
        
        if exchange == 'binance':
            df = self.fetch_binance_funding(symbol, start_time, end_time)
        elif exchange == 'bybit':
            df = self.fetch_bybit_funding(symbol, start_time, end_time)
        elif exchange == 'okx':
            df = self.fetch_okx_funding(symbol, start_time, end_time)
        else:
            raise ValueError(f"Unsupported exchange: {exchange}")
        
        # Cache by year
        if use_cache and not df.empty:
            for year, year_df in df.groupby(df['timestamp'].dt.year):
                self._save_cache(year_df, exchange, symbol, year)
        
        return df
    
    def fetch_all_exchanges(self, exchanges: List[str], symbols: List[str],
                           start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """
        Fetch funding data for multiple exchanges and symbols.
        
        Returns:
            Combined DataFrame with all funding rates
        """
        all_data = []
        
        for exchange in exchanges:
            for symbol in symbols:
                try:
                    df = self.fetch_funding_history(exchange, symbol, start_time, end_time)
                    if not df.empty:
                        all_data.append(df)
                        logger.info(f"Fetched {len(df)} records for {exchange} {symbol}")
                except Exception as e:
                    logger.error(f"Failed to fetch {exchange} {symbol}: {e}")
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            combined = combined.sort_values(['timestamp', 'exchange', 'symbol'])
            return combined
        
        return pd.DataFrame()
    
    def load_local_csv(self, filepath: str) -> pd.DataFrame:
        """
        Load funding data from local CSV file.
        
        Expected columns: timestamp, exchange, symbol, funding_rate
        """
        df = pd.read_csv(filepath)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    
    def get_funding_statistics(self, df: pd.DataFrame) -> Dict:
        """
        Calculate funding rate statistics by exchange-symbol pair.
        """
        stats = {}
        
        for (exchange, symbol), group in df.groupby(['exchange', 'symbol']):
            rates = group['funding_rate']
            
            stats[f"{exchange}_{symbol}"] = {
                'mean': rates.mean(),
                'std': rates.std(),
                'min': rates.min(),
                'max': rates.max(),
                'annualized_mean': rates.mean() * 3 * 365,
                'annualized_std': rates.std() * np.sqrt(3 * 365),
                'positive_pct': (rates > 0).mean(),
                'negative_pct': (rates < 0).mean(),
                'count': len(rates)
            }
        
        return stats


def download_historical_data():
    """
    Download historical funding data for backtesting.
    Run this to populate the data cache.
    """
    loader = FundingDataLoader(data_dir="../data")
    
    # Define parameters
    exchanges = ['binance', 'bybit', 'okx']
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    start_time = datetime(2021, 1, 1)
    end_time = datetime(2024, 12, 31)
    
    logger.info(f"Downloading funding data from {start_time} to {end_time}")
    
    # Fetch all data
    df = loader.fetch_all_exchanges(exchanges, symbols, start_time, end_time)
    
    if not df.empty:
        # Save combined data
        output_path = loader.data_dir / "funding_rates_all.parquet"
        df.to_parquet(output_path, compression='zstd')
        logger.info(f"Saved combined data to {output_path}")
        
        # Print statistics
        stats = loader.get_funding_statistics(df)
        print("\nFunding Rate Statistics:")
        print("=" * 60)
        for key, values in stats.items():
            print(f"\n{key}:")
            print(f"  Mean (8h): {values['mean']:.6f}")
            print(f"  Annualized: {values['annualized_mean']:.2%}")
            print(f"  Std Dev: {values['std']:.6f}")
            print(f"  Positive: {values['positive_pct']:.1%}")
    else:
        logger.error("No data downloaded")


if __name__ == "__main__":
    download_historical_data()
