#!/usr/bin/env python3
"""
Fetch 90 days of SOL/USDT data from Binance for Phase 5 re-evaluation
"""
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime, timedelta
import json
from pathlib import Path

async def fetch_sol_data():
    """Fetch SOL/USDT 1h and 4h candles for 90 days."""
    print("=" * 60)
    print("FETCHING SOL/USDT DATA FROM BINANCE")
    print("=" * 60)
    
    exchange = ccxt.binance({'enableRateLimit': True})
    
    # Calculate timestamps
    end_time = datetime.now()
    start_time = end_time - timedelta(days=90)
    
    print(f"\nData Range: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}")
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'data_range': {
            'start': start_time.isoformat(),
            'end': end_time.isoformat()
        },
        'files': []
    }
    
    # Fetch 1h data
    print("\n[1/3] Fetching 1h candles...")
    ohlcv_1h = await exchange.fetch_ohlcv('SOL/USDT', timeframe='1h', since=int(start_time.timestamp() * 1000))
    
    df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='ms')
    
    print(f"  ✓ Fetched {len(df_1h)} candles")
    print(f"  ✓ Date range: {df_1h['timestamp'].min()} to {df_1h['timestamp'].max()}")
    print(f"  ✓ Price range: ${df_1h['low'].min():.2f} - ${df_1h['high'].max():.2f}")
    
    # Save 1h data
    output_dir = Path(__file__).parent.parent / 'data'
    output_dir.mkdir(exist_ok=True)
    
    csv_path_1h = output_dir / 'SOLUSDT_1h_90d_fresh.csv'
    df_1h.to_csv(csv_path_1h, index=False)
    print(f"  ✓ Saved to: {csv_path_1h}")
    results['files'].append(str(csv_path_1h))
    
    # Fetch 4h data
    print("\n[2/3] Fetching 4h candles...")
    ohlcv_4h = await exchange.fetch_ohlcv('SOL/USDT', timeframe='4h', since=int(start_time.timestamp() * 1000))
    
    df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_4h['timestamp'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
    
    print(f"  ✓ Fetched {len(df_4h)} candles")
    print(f"  ✓ Date range: {df_4h['timestamp'].min()} to {df_4h['timestamp'].max()}")
    
    csv_path_4h = output_dir / 'SOLUSDT_4h_90d_fresh.csv'
    df_4h.to_csv(csv_path_4h, index=False)
    print(f"  ✓ Saved to: {csv_path_4h}")
    results['files'].append(str(csv_path_4h))
    
    # Fetch funding rates
    print("\n[3/3] Fetching funding rates...")
    try:
        funding_rates = await exchange.fetchFundingRateHistory('SOL/USDT', since=int(start_time.timestamp() * 1000))
        
        if funding_rates:
            df_funding = pd.DataFrame(funding_rates)
            if not df_funding.empty:
                df_funding['datetime'] = pd.to_datetime(df_funding['fundingTimestamp'], unit='ms')
                print(f"  ✓ Fetched {len(df_funding)} funding rate records")
                
                csv_path_funding = output_dir / 'SOLUSDT_funding_90d_fresh.csv'
                df_funding.to_csv(csv_path_funding, index=False)
                print(f"  ✓ Saved to: {csv_path_funding}")
                results['files'].append(str(csv_path_funding))
                
                # Calculate average funding
                avg_funding = df_funding['fundingRate'].mean()
                print(f"  ✓ Average funding rate: {avg_funding:.6%}")
        else:
            print("  ⚠ No funding rate data available")
    except Exception as e:
        print(f"  ⚠ Funding rates not available: {e}")
    
    await exchange.close()
    
    # Save metadata
    meta_path = output_dir / 'data_fetch_metadata.json'
    with open(meta_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("DATA FETCH COMPLETE")
    print("=" * 60)
    
    return results

if __name__ == '__main__':
    results = asyncio.run(fetch_sol_data())
    print(f"\nFiles saved: {len(results['files'])}")
