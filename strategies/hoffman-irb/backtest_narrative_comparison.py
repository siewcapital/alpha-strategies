"""
Narrative-Enhanced Hoffman IRB Backtest Comparison

Compares base Hoffman IRB strategy vs. narrative-enhanced version.

Expected improvements based on research:
- Win rate: 61% → 70-75%
- Reduced false breakouts in weak narrative environments
- Better risk-adjusted returns

Usage:
    python backtest_narrative_comparison.py --symbol BTC-USD --period 2y
    
Requirements:
    - NarrativeAlpha API running on localhost:8000 (or --mock-narrative)
    - yfinance for data download
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from typing import Dict, Tuple
import json
import argparse

from strategy import HoffmanIRBStrategy, TradeDirection
from narrative_enhanced import NarrativeEnhancedHoffmanIRB


def download_data(symbol: str = "BTC-USD", period: str = "2y", interval: str = "1h") -> pd.DataFrame:
    """Download historical price data from Yahoo Finance."""
    print(f"📥 Downloading {symbol} data ({period}, {interval})...")
    
    data = yf.download(symbol, period=period, interval=interval, progress=False)
    
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    
    data.columns = [c.lower() for c in data.columns]
    
    column_mapping = {'adj close': 'close', 'adj_close': 'close'}
    data.rename(columns=column_mapping, inplace=True)
    
    print(f"   Downloaded {len(data)} rows from {data.index[0]} to {data.index[-1]}")
    return data


def calculate_returns(equity_curve: pd.DataFrame) -> pd.Series:
    """Calculate returns series from equity curve."""
    return equity_curve['equity'].pct_change().dropna()


def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Calculate annualized Sharpe Ratio."""
    if len(returns) == 0 or returns.std() == 0:
        return 0.0
    
    periods_per_year = 8760  # Hourly data
    excess_returns = returns - risk_free_rate / periods_per_year
    
    sharpe = (excess_returns.mean() * periods_per_year) / (returns.std() * np.sqrt(periods_per_year))
    return sharpe


def calculate_sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Calculate annualized Sortino Ratio."""
    if len(returns) == 0:
        return 0.0
    
    periods_per_year = 8760
    excess_returns = returns - risk_free_rate / periods_per_year
    
    downside_returns = returns[returns < 0]
    if len(downside_returns) == 0:
        return float('inf')
    
    downside_std = downside_returns.std() * np.sqrt(periods_per_year)
    if downside_std == 0:
        return float('inf')
    
    sortino = (excess_returns.mean() * periods_per_year) / downside_std
    return sortino


def calculate_max_drawdown(equity_curve: pd.DataFrame) -> Tuple[float, datetime, datetime]:
    """Calculate maximum drawdown and its period."""
    equity = equity_curve['equity']
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    
    max_dd_idx = drawdown.idxmin()
    max_dd = drawdown.min()
    
    peak_mask = equity.index <= max_dd_idx
    peak_idx = equity[peak_mask].idxmax()
    
    return max_dd, peak_idx, max_dd_idx


def calculate_calmar_ratio(returns: pd.Series, max_drawdown: float) -> float:
    """Calculate Calmar Ratio."""
    if max_drawdown == 0:
        return 0.0
    
    periods_per_year = 8760
    annualized_return = returns.mean() * periods_per_year
    
    calmar = annualized_return / abs(max_drawdown)
    return calmar


def run_strategy_backtest(
    strategy,
    data: pd.DataFrame,
    initial_capital: float = 10000.0,
    transaction_cost: float = 0.001,
    symbol: str = "BTC-USD"
) -> Dict:
    """Run backtest and return comprehensive results."""
    
    # Generate signals
    if isinstance(strategy, NarrativeEnhancedHoffmanIRB):
        signals, equity_curve = strategy.run_backtest(
            data, initial_capital, transaction_cost, symbol
        )
    else:
        signals, equity_curve = strategy.run_backtest(
            data, initial_capital, transaction_cost
        )
    
    returns = calculate_returns(equity_curve)
    
    # Basic trade statistics
    trade_stats = strategy.get_trade_statistics()
    
    # Advanced metrics
    sharpe = calculate_sharpe_ratio(returns)
    sortino = calculate_sortino_ratio(returns)
    max_dd, peak_date, trough_date = calculate_max_drawdown(equity_curve)
    calmar = calculate_calmar_ratio(returns, max_dd)
    
    # Total return
    total_return = (equity_curve['equity'].iloc[-1] / initial_capital) - 1
    
    # Annualized return
    days = (equity_curve.index[-1] - equity_curve.index[0]).days
    annualized_return = ((equity_curve['equity'].iloc[-1] / initial_capital) ** (365 / max(days, 1))) - 1
    
    return {
        'initial_capital': initial_capital,
        'final_equity': equity_curve['equity'].iloc[-1],
        'total_return': total_return,
        'annualized_return': annualized_return,
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'calmar_ratio': calmar,
        'max_drawdown': max_dd,
        'max_drawdown_peak': peak_date,
        'max_drawdown_trough': trough_date,
        'trade_stats': trade_stats,
        'signals': signals,
        'equity_curve': equity_curve,
        'trades': strategy.trades
    }


def print_comparison(base_results: Dict, narrative_results: Dict):
    """Print formatted comparison between strategies."""
    
    print("\n" + "=" * 80)
    print("NARRATIVE-ENHANCED HOFFMAN IRB - BACKTEST COMPARISON")
    print("=" * 80)
    
    base_stats = base_results['trade_stats']
    narrative_stats = narrative_results['trade_stats']
    
    print(f"\n{'Metric':<30} {'Base IRB':>15} {'Narrative IRB':>15} {'Improvement':>15}")
    print("-" * 80)
    
    # Total Return
    base_ret = base_results['total_return'] * 100
    nar_ret = narrative_results['total_return'] * 100
    diff = nar_ret - base_ret
    print(f"{'Total Return':<30} {base_ret:>14.2f}% {nar_ret:>14.2f}% {diff:>+14.2f}%")
    
    # Annualized Return
    base_ann = base_results['annualized_return'] * 100
    nar_ann = narrative_results['annualized_return'] * 100
    diff = nar_ann - base_ann
    print(f"{'Annualized Return':<30} {base_ann:>14.2f}% {nar_ann:>14.2f}% {diff:>+14.2f}%")
    
    # Win Rate
    if base_stats and narrative_stats:
        base_wr = base_stats['win_rate'] * 100
        nar_wr = narrative_stats['win_rate'] * 100
        diff = nar_wr - base_wr
        print(f"{'Win Rate':<30} {base_wr:>14.1f}% {nar_wr:>14.1f}% {diff:>+14.1f}%")
    
    # Total Trades
    if base_stats and narrative_stats:
        base_trades = base_stats['total_trades']
        nar_trades = narrative_stats['total_trades']
        diff_count = nar_trades - base_trades
        print(f"{'Total Trades':<30} {base_trades:>15} {nar_trades:>15} {diff_count:>+15}")
    
    # Profit Factor
    if base_stats and narrative_stats:
        base_pf = base_stats['profit_factor']
        nar_pf = narrative_stats['profit_factor']
        diff = nar_pf - base_pf
        print(f"{'Profit Factor':<30} {base_pf:>15.2f} {nar_pf:>15.2f} {diff:>+15.2f}")
    
    # Sharpe Ratio
    base_sr = base_results['sharpe_ratio']
    nar_sr = narrative_results['sharpe_ratio']
    diff = nar_sr - base_sr
    print(f"{'Sharpe Ratio':<30} {base_sr:>15.3f} {nar_sr:>15.3f} {diff:>+15.3f}")
    
    # Sortino Ratio
    base_sort = base_results['sortino_ratio']
    nar_sort = narrative_results['sortino_ratio']
    diff = nar_sort - base_sort
    print(f"{'Sortino Ratio':<30} {base_sort:>15.3f} {nar_sort:>15.3f} {diff:>+15.3f}")
    
    # Calmar Ratio
    base_cal = base_results['calmar_ratio']
    nar_cal = narrative_results['calmar_ratio']
    diff = nar_cal - base_cal
    print(f"{'Calmar Ratio':<30} {base_cal:>15.3f} {nar_cal:>15.3f} {diff:>+15.3f}")
    
    # Max Drawdown
    base_dd = base_results['max_drawdown'] * 100
    nar_dd = narrative_results['max_drawdown'] * 100
    diff = nar_dd - base_dd
    print(f"{'Max Drawdown':<30} {base_dd:>14.2f}% {nar_dd:>14.2f}% {diff:>+14.2f}%")
    
    print("-" * 80)
    
    # Summary
    print("\n📊 SUMMARY")
    print("-" * 40)
    
    improvements = []
    if narrative_stats and base_stats:
        if narrative_stats['win_rate'] > base_stats['win_rate']:
            improvements.append(f"✅ Win rate improved by {(narrative_stats['win_rate'] - base_stats['win_rate'])*100:.1f}%")
        if narrative_results['sharpe_ratio'] > base_results['sharpe_ratio']:
            improvements.append(f"✅ Sharpe ratio improved by {narrative_results['sharpe_ratio'] - base_results['sharpe_ratio']:.3f}")
        if abs(narrative_results['max_drawdown']) < abs(base_results['max_drawdown']):
            improvements.append(f"✅ Max drawdown reduced by {abs(base_results['max_drawdown'] - narrative_results['max_drawdown'])*100:.2f}%")
        if narrative_results['total_return'] > base_results['total_return']:
            improvements.append(f"✅ Total return improved by {(narrative_results['total_return'] - base_results['total_return'])*100:.2f}%")
    
    if improvements:
        for imp in improvements:
            print(f"   {imp}")
    else:
        print("   ⚠️  No significant improvements detected")
        print("   (This may be due to lack of narrative data or market conditions)")
    
    print("\n" + "=" * 80)


def save_results(
    base_results: Dict, 
    narrative_results: Dict, 
    output_dir: str = "."
):
    """Save comparison results to files."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Save equity curves
    base_results['equity_curve'].to_csv(f'{output_dir}/base_equity_curve.csv')
    narrative_results['equity_curve'].to_csv(f'{output_dir}/narrative_equity_curve.csv')
    
    # Save comparison summary
    comparison = {
        'timestamp': datetime.now().isoformat(),
        'base_strategy': {
            'total_return': base_results['total_return'],
            'annualized_return': base_results['annualized_return'],
            'sharpe_ratio': base_results['sharpe_ratio'],
            'sortino_ratio': base_results['sortino_ratio'],
            'calmar_ratio': base_results['calmar_ratio'],
            'max_drawdown': base_results['max_drawdown'],
            'trade_stats': base_results['trade_stats']
        },
        'narrative_strategy': {
            'total_return': narrative_results['total_return'],
            'annualized_return': narrative_results['annualized_return'],
            'sharpe_ratio': narrative_results['sharpe_ratio'],
            'sortino_ratio': narrative_results['sortino_ratio'],
            'calmar_ratio': narrative_results['calmar_ratio'],
            'max_drawdown': narrative_results['max_drawdown'],
            'trade_stats': narrative_results['trade_stats']
        }
    }
    
    with open(f'{output_dir}/comparison_results.json', 'w') as f:
        json.dump(comparison, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to {output_dir}/")
    print(f"   - base_equity_curve.csv")
    print(f"   - narrative_equity_curve.csv")
    print(f"   - comparison_results.json")


def plot_comparison(
    base_results: Dict, 
    narrative_results: Dict,
    output_dir: str = "."
):
    """Generate comparison visualizations."""
    print("\n📈 Generating comparison charts...")
    
    plt.style.use('seaborn-v0_8-darkgrid')
    sns.set_palette("husl")
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    
    # Plot 1: Equity Curve Comparison
    ax1 = axes[0]
    base_eq = base_results['equity_curve']['equity']
    nar_eq = narrative_results['equity_curve']['equity']
    
    ax1.plot(base_eq.index, base_eq.values, linewidth=1.5, label='Base IRB', color='#3498DB', alpha=0.8)
    ax1.plot(nar_eq.index, nar_eq.values, linewidth=1.5, label='Narrative-Enhanced IRB', color='#2ECC71')
    ax1.axhline(y=base_results['initial_capital'], color='gray', linestyle='--', alpha=0.5)
    
    ax1.set_title('Hoffman IRB: Base vs Narrative-Enhanced', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Portfolio Value ($)')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
    
    # Plot 2: Drawdown Comparison
    ax2 = axes[1]
    base_running_max = base_eq.cummax()
    base_dd = (base_eq - base_running_max) / base_running_max * 100
    
    nar_running_max = nar_eq.cummax()
    nar_dd = (nar_eq - nar_running_max) / nar_running_max * 100
    
    ax2.fill_between(base_dd.index, base_dd.values, 0, color='#E74C3C', alpha=0.3, label='Base IRB')
    ax2.fill_between(nar_dd.index, nar_dd.values, 0, color='#F39C12', alpha=0.5, label='Narrative-Enhanced IRB')
    ax2.plot(base_dd.index, base_dd.values, color='#E74C3C', linewidth=1, alpha=0.7)
    ax2.plot(nar_dd.index, nar_dd.values, color='#F39C12', linewidth=1)
    
    ax2.set_title('Drawdown Comparison', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Drawdown (%)')
    ax2.set_xlabel('Date')
    ax2.legend(loc='lower left')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(f'{output_dir}/comparison_chart.png', dpi=150, bbox_inches='tight')
    print(f"   Saved: {output_dir}/comparison_chart.png")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description='Compare base vs narrative-enhanced Hoffman IRB')
    parser.add_argument('--symbol', default='BTC-USD', help='Trading symbol')
    parser.add_argument('--period', default='2y', help='Data period')
    parser.add_argument('--interval', default='1h', help='Candle interval')
    parser.add_argument('--initial-capital', type=float, default=10000.0, help='Initial capital')
    parser.add_argument('--output-dir', default='./results', help='Output directory')
    parser.add_argument('--mock-narrative', action='store_true', help='Use mock narrative signals')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("NARRATIVE-ENHANCED HOFFMAN IRB - BACKTEST COMPARISON")
    print("=" * 80)
    print(f"Symbol: {args.symbol} | Period: {args.period} | Interval: {args.interval}")
    print("=" * 80)
    
    # Download data
    data = download_data(args.symbol, args.period, args.interval)
    
    if len(data) < 100:
        raise ValueError(f"Insufficient data: only {len(data)} rows")
    
    # Strategy parameters
    strategy_params = {
        'ema_period': 20,
        'irb_threshold': 0.45,
        'risk_per_trade': 0.02,
        'risk_reward_ratio': 1.5,
        'max_irb_bars': 20,
        'use_atr_filter': True,
        'atr_multiplier': 2.0,
        'atr_period': 14
    }
    
    # Run base strategy backtest
    print("\n🔵 Running BASE Hoffman IRB backtest...")
    base_strategy = HoffmanIRBStrategy(**strategy_params)
    base_results = run_strategy_backtest(
        base_strategy, data, args.initial_capital, 0.001, args.symbol
    )
    
    # Run narrative-enhanced backtest
    print("\n🟢 Running NARRATIVE-ENHANCED Hoffman IRB backtest...")
    print("   (Connecting to NarrativeAlpha API at localhost:8000...)")
    
    narrative_params = {
        **strategy_params,
        'narrative_min_confidence': 'MEDIUM',
        'narrative_api_url': 'http://localhost:8000',
        'use_narrative_filter': not args.mock_narrative,
        'use_position_scaling': True
    }
    
    narrative_strategy = NarrativeEnhancedHoffmanIRB(**narrative_params)
    narrative_results = run_strategy_backtest(
        narrative_strategy, data, args.initial_capital, 0.001, args.symbol
    )
    
    # Print comparison
    print_comparison(base_results, narrative_results)
    
    # Save results
    save_results(base_results, narrative_results, args.output_dir)
    
    # Generate visualizations
    plot_comparison(base_results, narrative_results, args.output_dir)
    
    print("\n✅ Comparison complete!")


if __name__ == "__main__":
    main()
