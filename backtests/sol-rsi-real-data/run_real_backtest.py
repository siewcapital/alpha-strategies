"""
SOL RSI Mean Reversion - Real Data Backtest
Fetches SOL/USDT 1h candles from Binance and runs backtest.
Compares results to synthetic data baseline.
"""

import asyncio
import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Add strategy path
sys.path.insert(0, os.path.expanduser('~/.openclaw/agents/atlas/workspace/alpha-strategies/strategies/sol-rsi-mean-reversion'))
sys.path.insert(0, os.path.expanduser('~/.openclaw/agents/atlas/workspace/alpha-strategies'))

import ccxt
from backtest import SOLRSIMeanReversion, BacktestConfig


class BinanceDataFetcher:
    """Fetch historical OHLCV data from Binance."""
    
    def __init__(self, testnet=False):
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'  # Use spot for more historical data
            }
        })
        
    def fetch_ohlcv(self, symbol='SOL/USDT', timeframe='1h', limit=1000, since=None):
        """
        Fetch OHLCV candles from Binance.
        
        Args:
            symbol: Trading pair (e.g., 'SOL/USDT')
            timeframe: Candle timeframe
            limit: Number of candles per request (max 1000)
            since: Start timestamp in milliseconds
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df
        except Exception as e:
            print(f"Error fetching data: {e}")
            return pd.DataFrame()
    
    def fetch_max_history(self, symbol='SOL/USDT', timeframe='1h', max_candles=5000):
        """
        Fetch maximum available historical data.
        Uses pagination to get as much data as possible.
        """
        all_data = []
        
        # SOL started trading around August 2020
        # Start from 2021 to ensure liquidity
        start_date = datetime(2021, 1, 1)
        since = int(start_date.timestamp() * 1000)
        
        print(f"Fetching {symbol} {timeframe} data from {start_date.date()}...")
        
        while len(all_data) < max_candles:
            df = self.fetch_ohlcv(symbol, timeframe, limit=1000, since=since)
            
            if df.empty:
                break
                
            all_data.append(df)
            
            # Update since to last timestamp + 1 hour
            last_ts = df['timestamp'].iloc[-1]
            since = int(last_ts.timestamp() * 1000) + 3600000  # +1 hour in ms
            
            print(f"  Fetched {len(df)} candles, total: {sum(len(d) for d in all_data)}")
            
            # Rate limit
            import time
            time.sleep(0.1)
            
            # Check if we've reached current time
            if last_ts > datetime.now() - timedelta(hours=2):
                break
        
        if not all_data:
            return pd.DataFrame()
            
        # Combine all data
        combined = pd.concat(all_data, ignore_index=True)
        combined = combined.drop_duplicates(subset=['timestamp'])
        combined = combined.sort_values('timestamp').reset_index(drop=True)
        
        return combined


def run_real_data_backtest():
    """Main function to fetch real data and run backtest."""
    
    output_dir = Path(os.path.expanduser('~/.openclaw/agents/atlas/workspace/alpha-strategies/backtests/sol-rsi-real-data'))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("SOL RSI MEAN REVERSION - REAL DATA BACKTEST")
    print("=" * 70)
    print()
    
    # Fetch real data
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_max_history(symbol='SOL/USDT', timeframe='1h')
    
    if df.empty:
        print("ERROR: Could not fetch data from Binance")
        return None
    
    print(f"\n{'='*70}")
    print("DATA SUMMARY")
    print(f"{'='*70}")
    print(f"Total candles: {len(df):,}")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    print(f"Average daily volume: ${df['volume'].mean() * df['close'].mean():,.0f}")
    
    # Save raw data
    data_file = output_dir / 'sol_usdt_1h_real.csv'
    df.to_csv(data_file, index=False)
    print(f"\nRaw data saved to: {data_file}")
    
    # Run backtest
    print(f"\n{'='*70}")
    print("RUNNING BACKTEST")
    print(f"{'='*70}")
    
    strategy = SOLRSIMeanReversion()
    results = strategy.run_backtest(df)
    
    # Display results
    print(f"\n{'='*70}")
    print("REAL DATA BACKTEST RESULTS")
    print(f"{'='*70}")
    print(f"\nInitial Capital:       ${results['initial_capital']:,.2f}")
    print(f"Final Capital:         ${results['final_capital']:,.2f}")
    print(f"Total Return:          {results['total_return_pct']:+.2f}%")
    print()
    print(f"Total Trades:          {results['total_trades']}")
    print(f"Win Rate:              {results['win_rate']:.1f}%")
    print(f"Profit Factor:         {results['profit_factor']:.2f}")
    print()
    print(f"Avg Trade Return:      {results['avg_trade_return']:+.2f}%")
    print(f"Avg Win:               {results['avg_win']:+.2f}%")
    print(f"Avg Loss:              {results['avg_loss']:+.2f}%")
    print()
    print(f"Max Drawdown:          {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:          {results['sharpe_ratio']:.2f}")
    
    # Load synthetic results for comparison
    synthetic_path = Path(os.path.expanduser('~/.openclaw/agents/atlas/workspace/alpha-strategies/strategies/sol-rsi-mean-reversion/results.json'))
    
    comparison = {
        'real_data': results,
        'synthetic_data': None,
        'divergence': {}
    }
    
    if synthetic_path.exists():
        with open(synthetic_path, 'r') as f:
            synthetic = json.load(f)
        comparison['synthetic_data'] = synthetic
        
        print(f"\n{'='*70}")
        print("COMPARISON: REAL vs SYNTHETIC DATA")
        print(f"{'='*70}")
        print(f"{'Metric':<25} {'Synthetic':>15} {'Real':>15} {'Diff':>12}")
        print("-" * 70)
        
        metrics = [
            ('Total Return %', 'total_return_pct', '%+.2f%%'),
            ('Win Rate %', 'win_rate', '%.1f%%'),
            ('Profit Factor', 'profit_factor', '%.2f'),
            ('Max Drawdown %', 'max_drawdown_pct', '%.2f%%'),
            ('Sharpe Ratio', 'sharpe_ratio', '%.2f'),
            ('Total Trades', 'total_trades', '%d'),
        ]
        
        for label, key, fmt in metrics:
            syn_val = synthetic.get(key, 0)
            real_val = results.get(key, 0)
            diff = real_val - syn_val
            
            print(f"{label:<25} {fmt % syn_val:>15} {fmt % real_val:>15} {diff:+.2f}")
            comparison['divergence'][key] = {
                'synthetic': syn_val,
                'real': real_val,
                'difference': diff,
                'pct_change': ((real_val - syn_val) / abs(syn_val) * 100) if syn_val != 0 else 0
            }
        
        # Analysis
        print(f"\n{'='*70}")
        print("DIVERGENCE ANALYSIS")
        print(f"{'='*70}")
        
        return_diff = results['total_return_pct'] - synthetic['total_return_pct']
        winrate_diff = results['win_rate'] - synthetic['win_rate']
        
        if abs(return_diff) > 10:
            print("⚠️  SIGNIFICANT RETURN DIVERGENCE DETECTED")
            print(f"   Real data shows {return_diff:+.2f}% different return")
        elif abs(return_diff) > 5:
            print("⚡ MODERATE RETURN DIVERGENCE")
            print(f"   Real data shows {return_diff:+.2f}% different return")
        else:
            print("✅ RETURN IS CONSISTENT WITH SYNTHETIC DATA")
        
        if abs(winrate_diff) > 10:
            print(f"⚠️  Win rate differs by {winrate_diff:+.1f}%")
        
        if results['total_return_pct'] < -20:
            print("❌ Strategy shows significant losses on real data")
        elif results['total_return_pct'] > 10:
            print("✅ Strategy shows positive returns on real data")
        else:
            print("⚡ Strategy is near breakeven on real data")
    
    # Save detailed results
    results_file = output_dir / 'backtest_results.json'
    with open(results_file, 'w') as f:
        json.dump(comparison, f, indent=2, default=str)
    print(f"\nDetailed results saved to: {results_file}")
    
    # Save trade list
    if strategy.trades:
        trades_data = []
        for t in strategy.trades:
            trades_data.append({
                'entry_time': str(t.entry_time),
                'exit_time': str(t.exit_time),
                'direction': t.direction,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'size_usd': t.size_usd,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'exit_reason': t.exit_reason
            })
        
        trades_file = output_dir / 'trades.csv'
        pd.DataFrame(trades_data).to_csv(trades_file, index=False)
        print(f"Trade list saved to: {trades_file}")
    
    # Save equity curve
    if strategy.equity_curve:
        equity_df = pd.DataFrame(strategy.equity_curve, columns=['timestamp', 'equity'])
        equity_file = output_dir / 'equity_curve.csv'
        equity_df.to_csv(equity_file, index=False)
        print(f"Equity curve saved to: {equity_file}")
    
    print(f"\n{'='*70}")
    print("BACKTEST COMPLETE")
    print(f"{'='*70}")
    
    return comparison


if __name__ == "__main__":
    results = run_real_data_backtest()
