import requests
import pandas as pd
import numpy as np
import ta

def get_binance_data(symbol="SOLUSDT", interval="1h", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df

df = get_binance_data()
df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
df.dropna(inplace=True)

df['signal'] = 0
df.loc[df['rsi'] < 30, 'signal'] = 1
df.loc[df['rsi'] > 70, 'signal'] = -1
df['position'] = df['signal'].replace(0, np.nan).ffill().fillna(0)
df['returns'] = df['close'].pct_change()
df['strategy_returns'] = df['position'].shift(1) * df['returns']

total_return = df['strategy_returns'].sum()
sharpe = np.sqrt(24*365) * df['strategy_returns'].mean() / df['strategy_returns'].std()

with open('results.md', 'w') as f:
    f.write(f"# SOL/USDT RSI Mean Reversion\n\n- **Total Return**: {total_return:.2%}\n- **Sharpe Ratio**: {sharpe:.2f}\n")
    
print(f"Sharpe: {sharpe:.2f}")
