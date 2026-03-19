"""
Rob Hoffman IRB Strategy - Backtest Engine

Comprehensive backtesting with performance metrics:
- Sharpe Ratio
- Sortino Ratio
- Calmar Ratio
- Maximum Drawdown
- Win Rate
- Profit Factor

Author: ATLAS Alpha Hunter
Date: March 15, 2026
"""

import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from datetime import datetime, timedelta
from typing import Dict, Tuple, List
import warnings
warnings.filterwarnings('ignore')

from strategy import HoffmanIRBStrategy, TradeDirection


def download_data(
    symbol: str = "BTC-USD",
    period: str = "2y",
    interval: str = "1h"
) -> pd.DataFrame:
    """
    Download historical price data from Yahoo Finance.
    
    Parameters:
    -----------
    symbol : str
        Ticker symbol (default: BTC-USD)
    period : str
        Data period (default: 2y = 2 years)
    interval : str
        Candle interval (default: 1h = 1 hour)
    """
    print(f"Downloading {symbol} data ({period}, {interval})...")
    
    data = yf.download(
        symbol,
        period=period,
        interval=interval,
        progress=False
    )
    
    # Flatten multi-index columns if present
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    
    # Rename columns to lowercase
    data.columns = [c.lower() for c in data.columns]
    
    # Handle different column naming conventions
    column_mapping = {
        'adj close': 'close',
        'adj_close': 'close'
    }
    data.rename(columns=column_mapping, inplace=True)
    
    print(f"Downloaded {len(data)} rows from {data.index[0]} to {data.index[-1]}")
    
    return data


def calculate_returns(equity_curve: pd.DataFrame) -> pd.Series:
    """Calculate returns series from equity curve."""
    returns = equity_curve['equity'].pct_change().dropna()
    return returns


def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Calculate annualized Sharpe Ratio.
    
    Sharpe = (Mean Return - Risk Free Rate) / Standard Deviation of Returns
    """
    if len(returns) == 0 or returns.std() == 0:
        return 0.0
    
    # Annualize (assuming hourly data, ~8760 hours/year)
    periods_per_year = 8760
    excess_returns = returns - risk_free_rate / periods_per_year
    
    sharpe = (excess_returns.mean() * periods_per_year) / (returns.std() * np.sqrt(periods_per_year))
    
    return sharpe


def calculate_sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Calculate annualized Sortino Ratio.
    
    Sortino = (Mean Return - Risk Free Rate) / Downside Deviation
    Only penalizes downside volatility.
    """
    if len(returns) == 0:
        return 0.0
    
    periods_per_year = 8760
    excess_returns = returns - risk_free_rate / periods_per_year
    
    # Calculate downside deviation (only negative returns)
    downside_returns = returns[returns < 0]
    if len(downside_returns) == 0:
        return float('inf')
    
    downside_std = downside_returns.std() * np.sqrt(periods_per_year)
    
    if downside_std == 0:
        return float('inf')
    
    sortino = (excess_returns.mean() * periods_per_year) / downside_std
    
    return sortino


def calculate_max_drawdown(equity_curve: pd.DataFrame) -> Tuple[float, pd.Timestamp, pd.Timestamp]:
    """
    Calculate maximum drawdown and its period.
    
    Returns:
    --------
    Tuple of (max_drawdown_pct, peak_date, trough_date)
    """
    equity = equity_curve['equity']
    
    # Calculate running maximum
    running_max = equity.cummax()
    
    # Calculate drawdown
    drawdown = (equity - running_max) / running_max
    
    # Find maximum drawdown
    max_dd_idx = drawdown.idxmin()
    max_dd = drawdown.min()
    
    # Find the peak before this drawdown
    peak_mask = equity.index <= max_dd_idx
    peak_idx = equity[peak_mask].idxmax()
    
    return max_dd, peak_idx, max_dd_idx


def calculate_calmar_ratio(returns: pd.Series, max_drawdown: float) -> float:
    """
    Calculate Calmar Ratio.
    
    Calmar = Annualized Return / |Maximum Drawdown|
    """
    if max_drawdown == 0:
        return 0.0
    
    periods_per_year = 8760
    annualized_return = returns.mean() * periods_per_year
    
    calmar = annualized_return / abs(max_drawdown)
    
    return calmar


def calculate_monthly_returns(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Calculate monthly returns heatmap data."""
    equity = equity_curve['equity'].resample('ME').last()
    monthly_returns = equity.pct_change().dropna()
    
    # Create pivot table for heatmap
    monthly_df = pd.DataFrame({
        'year': monthly_returns.index.year,
        'month': monthly_returns.index.month,
        'return': monthly_returns.values
    })
    
    heatmap_data = monthly_df.pivot(index='year', columns='month', values='return')
    heatmap_data.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                            'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    return heatmap_data


def run_comprehensive_backtest(
    symbol: str = "BTC-USD",
    period: str = "2y",
    interval: str = "1h",
    initial_capital: float = 10000.0,
    transaction_cost: float = 0.001,
    strategy_params: Dict = None
) -> Dict:
    """
    Run comprehensive backtest with all metrics.
    
    Parameters:
    -----------
    symbol : str
        Trading symbol
    period : str
        Data period
    interval : str
        Candle interval
    initial_capital : float
        Starting capital
    transaction_cost : float
        Transaction cost per trade (0.001 = 0.1%)
    strategy_params : Dict
        Optional strategy parameter overrides
        
    Returns:
    --------
    Dict containing all backtest results and metrics
    """
    print("=" * 60)
    print(f"HOFFMAN IRB STRATEGY BACKTEST")
    print(f"Symbol: {symbol} | Period: {period} | Interval: {interval}")
    print("=" * 60)
    
    # Download data
    data = download_data(symbol, period, interval)
    
    if len(data) < 100:
        raise ValueError(f"Insufficient data: only {len(data)} rows")
    
    # Initialize strategy
    params = strategy_params or {}
    strategy = HoffmanIRBStrategy(**params)
    
    # Run backtest
    print("\nRunning backtest...")
    signals, equity_curve = strategy.run_backtest(
        data,
        initial_capital=initial_capital,
        transaction_cost=transaction_cost
    )
    
    # Calculate returns
    returns = calculate_returns(equity_curve)
    
    # Calculate metrics
    print("\nCalculating performance metrics...")
    
    # Basic trade statistics
    trade_stats = strategy.get_trade_statistics()
    
    # Sharpe Ratio
    sharpe = calculate_sharpe_ratio(returns)
    
    # Sortino Ratio
    sortino = calculate_sortino_ratio(returns)
    
    # Maximum Drawdown
    max_dd, peak_date, trough_date = calculate_max_drawdown(equity_curve)
    
    # Calmar Ratio
    calmar = calculate_calmar_ratio(returns, max_dd)
    
    # Total return
    total_return = (equity_curve['equity'].iloc[-1] / initial_capital) - 1
    
    # Annualized return
    days = (equity_curve.index[-1] - equity_curve.index[0]).days
    annualized_return = ((equity_curve['equity'].iloc[-1] / initial_capital) ** (365 / max(days, 1))) - 1
    
    # Monthly returns for heatmap
    monthly_returns = calculate_monthly_returns(equity_curve)
    
    # Compile results
    results = {
        'symbol': symbol,
        'period': period,
        'interval': interval,
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
        'data_points': len(data),
        'trade_stats': trade_stats,
        'signals': signals,
        'equity_curve': equity_curve,
        'monthly_returns': monthly_returns,
        'trades': strategy.trades
    }
    
    return results


def print_results(results: Dict):
    """Print formatted backtest results."""
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    
    print(f"\n📊 OVERALL PERFORMANCE")
    print(f"   Initial Capital:    ${results['initial_capital']:,.2f}")
    print(f"   Final Equity:       ${results['final_equity']:,.2f}")
    print(f"   Total Return:       {results['total_return']*100:+.2f}%")
    print(f"   Annualized Return:  {results['annualized_return']*100:+.2f}%")
    
    print(f"\n📈 RISK METRICS")
    print(f"   Sharpe Ratio:       {results['sharpe_ratio']:.3f}")
    print(f"   Sortino Ratio:      {results['sortino_ratio']:.3f}")
    print(f"   Calmar Ratio:       {results['calmar_ratio']:.3f}")
    print(f"   Maximum Drawdown:   {results['max_drawdown']*100:.2f}%")
    print(f"   DD Peak Date:       {results['max_drawdown_peak']}")
    print(f"   DD Trough Date:     {results['max_drawdown_trough']}")
    
    stats = results['trade_stats']
    if stats:
        print(f"\n🎯 TRADE STATISTICS")
        print(f"   Total Trades:       {stats['total_trades']}")
        print(f"   Winning Trades:     {stats['winning_trades']}")
        print(f"   Losing Trades:      {stats['losing_trades']}")
        print(f"   Win Rate:           {stats['win_rate']*100:.1f}%")
        print(f"   Profit Factor:      {stats['profit_factor']:.2f}")
        print(f"   Average Win:        ${stats['average_win']:,.2f}")
        print(f"   Average Loss:       ${stats['average_loss']:,.2f}")
        print(f"   Win/Loss Ratio:     {stats['win_loss_ratio']:.2f}")
        print(f"   Net Profit:         ${stats['net_profit']:,.2f}")
    
    print("\n" + "=" * 60)


def generate_visualizations(results: Dict, output_dir: str = "."):
    """Generate all visualization charts."""
    print("\nGenerating visualizations...")
    
    # Set style
    plt.style.use('seaborn-v0_8-darkgrid')
    sns.set_palette("husl")
    
    # 1. Equity Curve
    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    
    # Plot 1: Equity Curve with Drawdown
    ax1 = axes[0]
    equity = results['equity_curve']['equity']
    ax1.plot(equity.index, equity.values, linewidth=1.5, color='#2E86AB', label='Portfolio Value')
    ax1.axhline(y=results['initial_capital'], color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
    
    # Highlight max drawdown
    ax1.axvspan(results['max_drawdown_peak'], results['max_drawdown_trough'], 
                alpha=0.2, color='red', label=f'Max DD: {results["max_drawdown"]*100:.1f}%')
    
    ax1.set_title(f"Hoffman IRB Strategy - Equity Curve\n{results['symbol']} ({results['period']}, {results['interval']})", 
                  fontsize=14, fontweight='bold')
    ax1.set_ylabel('Portfolio Value ($)')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
    
    # Plot 2: Drawdown Chart
    ax2 = axes[1]
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max * 100
    ax2.fill_between(drawdown.index, drawdown.values, 0, color='#E94F37', alpha=0.5)
    ax2.plot(drawdown.index, drawdown.values, color='#E94F37', linewidth=1)
    ax2.set_title('Drawdown Over Time', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Drawdown (%)')
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Monthly Returns Heatmap
    ax3 = axes[2]
    monthly_data = results['monthly_returns']
    
    # Create heatmap
    sns.heatmap(monthly_data * 100, annot=True, fmt='.1f', cmap='RdYlGn', 
                center=0, ax=ax3, cbar_kws={'label': 'Return (%)'},
                linewidths=0.5, linecolor='white')
    ax3.set_title('Monthly Returns Heatmap', fontsize=12, fontweight='bold')
    ax3.set_xlabel('Month')
    ax3.set_ylabel('Year')
    
    plt.tight_layout()
    plt.savefig(f'{output_dir}/equity_curve.png', dpi=150, bbox_inches='tight')
    print(f"   Saved: {output_dir}/equity_curve.png")
    plt.close()
    
    # 2. Trade Distribution
    if results['trades']:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        
        # P&L Distribution
        ax1 = axes[0]
        pnls = [t.pnl for t in results['trades'] if t.status == 'closed']
        colors = ['green' if p > 0 else 'red' for p in pnls]
        ax1.bar(range(len(pnls)), pnls, color=colors, alpha=0.7)
        ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax1.set_title('Trade P&L Distribution', fontsize=12, fontweight='bold')
        ax1.set_xlabel('Trade Number')
        ax1.set_ylabel('P&L ($)')
        ax1.grid(True, alpha=0.3)
        
        # Win/Loss Pie Chart
        ax2 = axes[1]
        stats = results['trade_stats']
        if stats['winning_trades'] + stats['losing_trades'] > 0:
            sizes = [stats['winning_trades'], stats['losing_trades']]
            labels = [f'Wins\n({stats["winning_trades"]})', f'Losses\n({stats["losing_trades"]})']
            colors_pie = ['#2ECC71', '#E74C3C']
            explode = (0.05, 0)
            ax2.pie(sizes, explode=explode, labels=labels, colors=colors_pie,
                   autopct='%1.1f%%', shadow=True, startangle=90)
            ax2.set_title(f'Win Rate: {stats["win_rate"]*100:.1f}%', fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(f'{output_dir}/trade_distribution.png', dpi=150, bbox_inches='tight')
        print(f"   Saved: {output_dir}/trade_distribution.png")
        plt.close()


def main():
    """Main execution function."""
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
    
    # Run backtest
    results = run_comprehensive_backtest(
        symbol="BTC-USD",
        period="2y",
        interval="1h",
        initial_capital=10000.0,
        transaction_cost=0.001,  # 0.1% per trade
        strategy_params=strategy_params
    )
    
    # Print results
    print_results(results)
    
    # Generate visualizations
    output_dir = "/Users/siewbrayden/.openclaw/agents/atlas/workspace/alpha-hunter/strategies/hoffman-irb"
    generate_visualizations(results, output_dir)
    
    # Save data
    print("\nSaving data...")
    results['equity_curve'].to_csv(f'{output_dir}/data/equity_curve.csv')
    results['signals'].to_csv(f'{output_dir}/data/signals.csv')
    
    # Save trades to CSV
    if results['trades']:
        trades_df = pd.DataFrame([
            {
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'direction': 'LONG' if t.direction == TradeDirection.LONG else 'SHORT',
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'stop_loss': t.stop_loss,
                'take_profit': t.take_profit,
                'position_size': t.position_size,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'exit_reason': t.exit_reason
            }
            for t in results['trades']
        ])
        trades_df.to_csv(f'{output_dir}/data/trades.csv', index=False)
        print(f"   Saved trades: {len(results['trades'])} trades")
    
    print("\n✅ Backtest complete!")
    
    return results


if __name__ == "__main__":
    results = main()
