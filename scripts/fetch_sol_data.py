"""
Simple Binance Data Fetcher
Fetches SOL historical data using synchronous requests.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_sol_data(
    symbol: str = "SOLUSDT",
    timeframe: str = "1h", 
    days: int = 90,
    output_dir: Path = None
) -> Path:
    """
    Fetch SOL historical data from Binance Futures API.
    
    Args:
        symbol: Trading pair (default: SOLUSDT)
        timeframe: Candle interval (1h, 4h, 1d)
        days: Number of days to fetch
        output_dir: Output directory
    
    Returns:
        Path to saved CSV file
    """
    output_dir = output_dir or Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True, parents=True)
    
    base_url = "https://fapi.binance.com/fapi/v1/klines"
    
    # Calculate time range
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    
    logger.info(f"Fetching {symbol} {timeframe} data for last {days} days...")
    logger.info(f"From: {start_time.date()} To: {end_time.date()}")
    
    all_data = []
    current_start = start_time
    
    while current_start < end_time:
        # Calculate chunk end (max 1000 candles per request)
        chunk_hours = 1000 if timeframe == '1h' else (4000 if timeframe == '4h' else 24000)
        chunk_end = current_start + timedelta(hours=chunk_hours)
        
        if chunk_end > end_time:
            chunk_end = end_time
        
        params = {
            'symbol': symbol.upper(),
            'interval': timeframe,
            'startTime': int(current_start.timestamp() * 1000),
            'endTime': int(chunk_end.timestamp() * 1000),
            'limit': 1000
        }
        
        try:
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                logger.warning(f"No data returned for {current_start}")
                break
            
            all_data.extend(data)
            
            # Update current_start to last candle + 1 hour
            last_open_time = data[-1][0]
            current_start = datetime.fromtimestamp(last_open_time / 1000) + timedelta(hours=1)
            
            logger.info(f"Fetched {len(data)} candles ({current_start.date()})")
            
            # Rate limiting
            time.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            break
    
    if not all_data:
        logger.error("No data fetched")
        return None
    
    # Parse data
    df = pd.DataFrame(all_data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    
    # Convert types
    numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df.set_index('open_time', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades']]
    
    # Save to CSV
    filename = f"{symbol}_{timeframe}_{days}d.csv"
    filepath = output_dir / filename
    df.to_csv(filepath)
    
    # Also save as pickle
    df.to_pickle(filepath.with_suffix('.pkl'))
    
    logger.info(f"\nSaved {len(df)} rows to {filepath}")
    logger.info(f"Date range: {df.index[0]} to {df.index[-1]}")
    logger.info(f"Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
    
    return filepath


def fetch_funding_rates(
    symbol: str = "SOLUSDT",
    days: int = 90,
    output_dir: Path = None
) -> Path:
    """Fetch funding rate history."""
    output_dir = output_dir or Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True, parents=True)
    
    base_url = "https://fapi.binance.com/fapi/v1/fundingRate"
    
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    
    logger.info(f"\nFetching {symbol} funding rates for last {days} days...")
    
    all_data = []
    current_start = start_time
    
    while current_start < end_time:
        params = {
            'symbol': symbol.upper(),
            'startTime': int(current_start.timestamp() * 1000),
            'endTime': int(min(current_start + timedelta(days=60), end_time).timestamp() * 1000),
            'limit': 1000
        }
        
        try:
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                break
            
            all_data.extend(data)
            
            # Update start time
            last_time = data[-1]['fundingTime']
            current_start = datetime.fromtimestamp(last_time / 1000) + timedelta(hours=8)
            
            logger.info(f"Fetched {len(data)} funding records")
            time.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Error fetching funding rates: {e}")
            break
    
    if not all_data:
        return None
    
    df = pd.DataFrame(all_data)
    df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
    df['fundingRate'] = pd.to_numeric(df['fundingRate'])
    df.set_index('fundingTime', inplace=True)
    
    filepath = output_dir / f"{symbol}_funding_{days}d.csv"
    df.to_csv(filepath)
    df.to_pickle(filepath.with_suffix('.pkl'))
    
    logger.info(f"Saved {len(df)} funding records")
    logger.info(f"Mean rate: {df['fundingRate'].mean():.6%}")
    logger.info(f"Max rate: {df['fundingRate'].max():.6%}")
    logger.info(f"Min rate: {df['fundingRate'].min():.6%}")
    
    return filepath


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='SOLUSDT')
    parser.add_argument('--timeframes', nargs='+', default=['1h', '4h'])
    parser.add_argument('--days', type=int, default=90)
    parser.add_argument('--funding', action='store_true')
    
    args = parser.parse_args()
    
    # Fetch OHLCV data
    for tf in args.timeframes:
        fetch_sol_data(args.symbol, tf, args.days)
    
    # Fetch funding rates
    if args.funding:
        fetch_funding_rates(args.symbol, min(args.days, 365))
    
    print("\n" + "="*50)
    print("DATA FETCH COMPLETE")
    print("="*50)
