
import asyncio
import pandas as pd
from trading_connectors.ccxt_connector import CCXTExchangeConnector
import os
import json
from datetime import datetime

async def fetch_sol_data():
    print("Connecting to Binance...")
    # Use real Binance (testnet=False) for data evaluation
    # No credentials needed for public OHLCV data
    connector = CCXTExchangeConnector('binance', testnet=False)
    
    symbol = 'SOL/USDT:USDT'
    timeframe = '1h'
    limit = 500 # Get last 500 hours (~20 days)
    
    print(f"Fetching {limit} candles for {symbol} ({timeframe})...")
    df = await connector.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
    
    if df.empty:
        print("Failed to fetch data.")
        return
    
    print(f"Fetched {len(df)} candles.")
    print(f"Latest candle: {df.index[-1]}")
    print(f"Latest close: {df['close'].iloc[-1]}")
    
    # Save to CSV for backtest
    os.makedirs('data', exist_ok=True)
    data_path = 'data/SOLUSDT_1h_latest.csv'
    df.to_csv(data_path)
    print(f"Data saved to {data_path}")
    
    await connector.close()
    return data_path

if __name__ == "__main__":
    asyncio.run(fetch_sol_data())
