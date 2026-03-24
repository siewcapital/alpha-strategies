"""
SOL RSI Mean Reversion Strategy - Real Data Backtest

Re-evaluates the SOL RSI mean reversion strategy using real Binance data.
This script loads the 90 days of 1h/4h candles and runs the backtest.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import the strategy class from backtest.py
from backtest import SOLRSIMeanReversion, BacktestConfig, Trade


def load_real_data(data_path: str) -> pd.DataFrame:
    """
    Load real SOL/USDT data from Binance.
    
    Args:
        data_path: Path to CSV file with OHLCV data
    
    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    df = pd.read_csv(data_path)
    
    # Convert timestamp to datetime
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    elif 'open_time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
    
    # Ensure required columns exist
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    print(f"Loaded {len(df)} rows of real data")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    
    return df


def run_backtest_with_real_data(
    data_path: str,
    output_dir: str,
    timeframe: str = "1h"
) -> Dict:
    """
    Run backtest using real Binance data.
    
    Args:
        data_path: Path to CSV data file
        output_dir: Directory to save results
        timeframe: Data timeframe (1h or 4h)
    
    Returns:
        Backtest results dictionary
    """
    print("=" * 70)
    print(f"SOL RSI MEAN REVERSION - REAL DATA BACKTEST ({timeframe})")
    print("=" * 70)
    print()
    
    # Load real data
    print(f"Loading real Binance data from {data_path}...")
    df = load_real_data(data_path)
    print()
    
    # Configure strategy with optimized parameters for SOL
    config = BacktestConfig(
        symbol="SOLUSDT",
        timeframe=timeframe,
        initial_capital=10000.0,
        leverage=1.0,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        rsi_exit=50.0,
        ema_period=50,
        atr_period=14,
        stop_atr_mult=2.0,
        take_profit_atr_mult=3.0,
        risk_per_trade=0.02,
        max_positions=3,
        commission_rate=0.0005,
        slippage=0.0002
    )
    
    # Run backtest
    print("Running backtest on real data...")
    strategy = SOLRSIMeanReversion(config)
    results = strategy.run_backtest(df)
    
    # Display results
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS (REAL DATA)")
    print("=" * 70)
    print(f"\nInitial Capital:       ${results['initial_capital']:,.2f}")
    print(f"Final Capital:         ${results['final_capital']:,.2f}")
    print(f"Total Return:          {results['total_return_pct']:+.2f}%")
    print()
    print(f"Total Trades:          {results['total_trades']}")
    print(f"Win Rate:              {results['win_rate']:.1f}%")
    print(f"Profit Factor:         {results['profit_factor']:.2f}")
    print()
    print(f"Long Trades:           {results.get('long_trades', 'N/A')}")
    print(f"Short Trades:          {results.get('short_trades', 'N/A')}")
    print()
    print(f"Avg Trade Return:      {results['avg_trade_return']:+.2f}%")
    print(f"Avg Win:               {results['avg_win']:+.2f}%")
    print(f"Avg Loss:              {results['avg_loss']:+.2f}%")
    print()
    print(f"Max Drawdown:          {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:          {results['sharpe_ratio']:.2f}")
    print(f"Sortino Ratio:         {results.get('sortino_ratio', 0):.2f}")
    print(f"Calmar Ratio:          {results.get('calmar_ratio', 0):.2f}")
    print()
    
    # Save results
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save summary results
    results_file = output_path / f'results_real_data_{timeframe}.json'
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Save trade history
    trades_data = [{
        'entry_time': str(t.entry_time),
        'exit_time': str(t.exit_time),
        'direction': t.direction,
        'entry_price': t.entry_price,
        'exit_price': t.exit_price,
        'size_usd': t.size_usd,
        'pnl': t.pnl,
        'pnl_pct': t.pnl_pct,
        'exit_reason': t.exit_reason,
        'duration_hours': t.duration_hours
    } for t in strategy.trades]
    
    trades_file = output_path / f'trades_real_data_{timeframe}.json'
    with open(trades_file, 'w') as f:
        json.dump(trades_data, f, indent=2, default=str)
    
    # Save equity curve
    equity_data = [{'timestamp': str(ts), 'equity': eq} for ts, eq in strategy.equity_curve]
    equity_file = output_path / f'equity_curve_real_data_{timeframe}.json'
    with open(equity_file, 'w') as f:
        json.dump(equity_data, f, indent=2, default=str)
    
    # Save CSV versions
    equity_df = pd.DataFrame(strategy.equity_curve, columns=['timestamp', 'equity'])
    equity_df.to_csv(output_path / f'equity_curve_real_data_{timeframe}.csv', index=False)
    
    if trades_data:
        trades_df = pd.DataFrame(trades_data)
        trades_df.to_csv(output_path / f'trades_real_data_{timeframe}.csv', index=False)
    
    print(f"Results saved to:")
    print(f"  - {results_file}")
    print(f"  - {trades_file}")
    print(f"  - {equity_file}")
    
    return results


def compare_timeframes(data_dir: str, output_dir: str):
    """
    Compare strategy performance across 1h and 4h timeframes.
    """
    print("\n" + "=" * 70)
    print("COMPARING TIMEFRAMES")
    print("=" * 70)
    print()
    
    results_comparison = {}
    
    # Test 1h data
    data_1h = Path(data_dir) / 'SOLUSDT_1h_90d.csv'
    if data_1h.exists():
        results_1h = run_backtest_with_real_data(
            str(data_1h),
            output_dir,
            timeframe='1h'
        )
        results_comparison['1h'] = results_1h
    else:
        print(f"Warning: 1h data not found at {data_1h}")
    
    print("\n" + "=" * 70)
    print()
    
    # Test 4h data
    data_4h = Path(data_dir) / 'SOLUSDT_4h_90d.csv'
    if data_4h.exists():
        results_4h = run_backtest_with_real_data(
            str(data_4h),
            output_dir,
            timeframe='4h'
        )
        results_comparison['4h'] = results_4h
    else:
        print(f"Warning: 4h data not found at {data_4h}")
    
    # Save comparison
    if results_comparison:
        comparison_file = Path(output_dir) / 'timeframe_comparison.json'
        with open(comparison_file, 'w') as f:
            json.dump(results_comparison, f, indent=2, default=str)
        print(f"\nComparison saved to: {comparison_file}")
        
        # Print comparison table
        print("\n" + "=" * 70)
        print("TIMEFRAME COMPARISON")
        print("=" * 70)
        print(f"\n{'Metric':<25} {'1h':>15} {'4h':>15}")
        print("-" * 70)
        
        metrics = [
            ('Total Return (%)', 'total_return_pct'),
            ('Total Trades', 'total_trades'),
            ('Win Rate (%)', 'win_rate'),
            ('Profit Factor', 'profit_factor'),
            ('Max Drawdown (%)', 'max_drawdown_pct'),
            ('Sharpe Ratio', 'sharpe_ratio'),
            ('Sortino Ratio', 'sortino_ratio'),
            ('Calmar Ratio', 'calmar_ratio')
        ]
        
        for label, key in metrics:
            val_1h = results_comparison.get('1h', {}).get(key, 0)
            val_4h = results_comparison.get('4h', {}).get(key, 0)
            print(f"{label:<25} {val_1h:>15.2f} {val_4h:>15.2f}")
    
    return results_comparison


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='SOL RSI Mean Reversion - Real Data Backtest'
    )
    parser.add_argument(
        '--data-dir',
        type=str,
        default='/Users/siewbrayden/.openclaw/workspace/alpha-strategies/data',
        help='Directory containing Binance data files'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='/Users/siewbrayden/.openclaw/workspace/alpha-strategies/strategies/sol-rsi-mean-reversion/results',
        help='Directory to save results'
    )
    parser.add_argument(
        '--timeframe',
        type=str,
        choices=['1h', '4h', 'both'],
        default='both',
        help='Timeframe to test'
    )
    
    args = parser.parse_args()
    
    # Ensure output directory exists
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    
    if args.timeframe == 'both':
        compare_timeframes(args.data_dir, args.output_dir)
    else:
        data_file = Path(args.data_dir) / f'SOLUSDT_{args.timeframe}_90d.csv'
        if data_file.exists():
            run_backtest_with_real_data(
                str(data_file),
                args.output_dir,
                timeframe=args.timeframe
            )
        else:
            print(f"Error: Data file not found: {data_file}")
            print("Please run fetch_binance_data.py first to download the data.")


if __name__ == "__main__":
    main()
