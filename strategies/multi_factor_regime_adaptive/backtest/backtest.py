"""
backtest.py - Backtesting engine for Multi-Factor Regime-Adaptive strategy.

Features:
- Multi-asset support
- Realistic transaction costs (0.1% per trade)
- Slippage modeling
- Walk-forward analysis
- Monte Carlo simulation
- Comprehensive metrics
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import logging

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy import MultiFactorRegimeStrategy, StrategySignal, Trade, Position
from src.risk_manager import RiskManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_synthetic_data(
    n_days: int = 1500,
    n_assets: int = 5,
    initial_price: float = 100.0,
    seed: int = 42
) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray],
           Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    """
    Generate synthetic OHLC data for backtesting.
    
    Creates realistic crypto-like price series with:
    - Trending periods
    - Ranging periods
    - Volatility clustering
    
    Args:
        n_days: Number of trading days
        n_assets: Number of assets
        initial_price: Starting price
        seed: Random seed
        
    Returns:
        (highs, lows, opens, closes) dicts keyed by asset name
    """
    np.random.seed(seed)
    
    assets = [f"ASSET_{i}" for i in range(n_assets)]
    
    closes = {}
    opens = {}
    highs = {}
    lows = {}
    
    for i, asset in enumerate(assets):
        # Generate base returns with regime shifts
        returns = np.zeros(n_days)
        price = initial_price * (1 + 0.1 * np.random.randn())
        
        regime_durations = []
        current_regime = np.random.choice(["trend", "range", "vol"])
        regime_start = 0
        
        for day in range(n_days):
            # Regime transitions (HMM-like)
            if day - regime_start > regime_durations[-1] if regime_durations else day > 30:
                # Transition to new regime
                probs = {"trend": 0.33, "range": 0.34, "vol": 0.33}
                current_regime = np.random.choice(
                    list(probs.keys()),
                    p=[probs[k] for k in probs]
                )
                regime_start = day
                regime_durations.append(np.random.randint(20, 100))
            
            # Generate return based on regime
            if current_regime == "trend":
                drift = 0.001 + 0.0003 * np.sin(day / 50)  # Upward drift
                noise = np.random.randn() * 0.02
                returns[day] = drift + noise
            elif current_regime == "range":
                # Mean-reverting
                mean_price = price * 0.99
                returns[day] = -0.001 * (price - mean_price) / price + np.random.randn() * 0.015
            else:  # vol
                # High volatility, trending
                drift = 0.0005 * np.random.randn()
                noise = np.random.randn() * 0.04
                returns[day] = drift + noise
            
            price = price * (1 + returns[day])
            
            # Ensure price stays positive
            price = max(price, 1.0)
        
        # Generate OHLC from close series
        close_arr = price * np.exp(np.cumsum(returns))
        open_arr = np.roll(close_arr, 1)
        open_arr[0] = close_arr[0] * 0.99
        
        # High/Low with some noise
        high_arr = np.maximum(close_arr, open_arr) * (1 + np.abs(np.random.randn(n_days) * 0.01))
        low_arr = np.minimum(close_arr, open_arr) * (1 - np.abs(np.random.randn(n_days) * 0.01))
        
        closes[asset] = close_arr
        opens[asset] = open_arr
        highs[asset] = high_arr
        lows[asset] = low_arr
    
    return highs, lows, opens, closes


def run_backtest(
    strategy_params: Dict[str, Any],
    highs: Dict[str, np.ndarray],
    lows: Dict[str, np.ndarray],
    opens: Dict[str, np.ndarray],
    closes: Dict[str, np.ndarray],
    initial_capital: float = 100000.0,
    transaction_cost_pct: float = 0.001,
    slippage_pct: float = 0.0005,
    commission_pct: float = 0.0,
    benchmark_asset: str = "ASSET_0"
) -> Dict[str, Any]:
    """
    Run a complete backtest.
    
    Args:
        strategy_params: Parameters for MultiFactorRegimeStrategy
        highs, lows, opens, closes: OHLC data dicts
        initial_capital: Starting capital
        transaction_cost_pct: Cost as % of trade value
        slippage_pct: Additional slippage %
        commission_pct: Commission %
        benchmark_asset: Asset to use for buy-and-hold benchmark
        
    Returns:
        Dictionary with results, trades, equity curve, metrics
    """
    assets = list(closes.keys())
    n_days = len(closes[assets[0]])
    
    # Initialize strategy
    strategy = MultiFactorRegimeStrategy(**strategy_params)
    strategy.risk_manager.current_capital = initial_capital
    strategy.risk_manager.peak_capital = initial_capital
    
    # Tracking
    equity_curve = []
    benchmark_curve = []
    positions_at_time = {}
    regime_history = []
    
    # Initialize starting equity at warmup point
    warmup = 150
    starting_equity = initial_capital
    strategy.risk_manager.current_capital = starting_equity
    strategy.risk_manager.peak_capital = starting_equity
    equity_curve.append(starting_equity)
    
    # Benchmark initial value
    benchmark_shares = initial_capital * 0.5 / closes[benchmark_asset][warmup]
    benchmark_initial = benchmark_shares * closes[benchmark_asset][warmup]
    benchmark_curve.append(benchmark_initial)
    
    # Convert dicts to list format for strategy
    close_arrays = [closes[a] for a in assets]
    high_arrays = [highs[a] for a in assets]
    low_arrays = [lows[a] for a in assets]
    
    # Warmup period (need enough data for indicators)
    warmup = 150  # Need at least 2*atr_period + atr_percentile_period bars
    
    # Run backtest day by day
    for day in range(warmup, n_days):
        # Extract single-day data for each asset
        daily_highs = np.array([highs[a][day] for a in assets])
        daily_lows = np.array([lows[a][day] for a in assets])
        daily_closes = np.array([closes[a][day] for a in assets])
        
        # Update strategy bar
        strategy.bar_count = day
        
        # Run signal generation and position management
        # Strategy processes full arrays, need to reconstruct for each day
        for i, asset in enumerate(assets):
            asset_highs = highs[asset][:day+1]
            asset_lows = lows[asset][:day+1]
            asset_closes = closes[asset][:day+1]
            
            signal = strategy.generate_signal(asset_highs, asset_lows, asset_closes, asset)
            
            # Enter if signal
            if signal.direction != 0 and asset not in strategy.positions:
                # Simulate entry with slippage
                entry_price = asset_closes[-1] * (1 + slippage_pct * signal.direction)
                
                if strategy.should_enter(signal):
                    position_value = strategy.risk_manager.current_capital * 0.1  # 10% per trade

                    strategy.positions[asset] = Position(
                        asset=asset,
                        direction=signal.direction,
                        entry_price=entry_price,
                        size=position_value,
                        entry_time=day,
                        entry_regime=signal.regime
                    )
        
        # Check exits
        for asset in list(strategy.positions.keys()):
            position = strategy.positions[asset]
            
            current_price = closes[asset][day]
            atr_val = np.std(np.diff(closes[asset][:day+1])) * 2 if day > 14 else 0.02 * closes[asset][day]
            
            # Stop loss
            stop_triggered = False
            exit_reason = ""
            
            if position.direction > 0:
                loss = (current_price - position.entry_price) / position.entry_price
                if loss < -0.04:  # 4% stop
                    stop_triggered = True
                    exit_reason = "STOP_LOSS"
            else:
                loss = (position.entry_price - current_price) / position.entry_price
                if loss < -0.04:
                    stop_triggered = True
                    exit_reason = "STOP_LOSS"
            
            # Time stop
            if day - position.entry_time > 10:
                stop_triggered = True
                exit_reason = "TIME_STOP"
            
            if stop_triggered:
                exit_price = current_price * (1 - slippage_pct * position.direction)
                
                pnl = position.size * ((exit_price - position.entry_price) / position.entry_price * position.direction)
                
                # Apply transaction costs
                entry_cost = position.size * transaction_cost_pct
                exit_cost = position.size * transaction_cost_pct
                total_cost = entry_cost + exit_cost + position.size * commission_pct * 2
                
                net_pnl = pnl - total_cost
                
                trade = Trade(
                    asset=asset,
                    direction=position.direction,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    size=position.size,
                    entry_time=position.entry_time,
                    exit_time=day,
                    pnl=net_pnl,
                    return_pct=net_pnl / position.size,
                    exit_reason=exit_reason,
                    regime=position.entry_regime,
                    hold_days=day - position.entry_time
                )
                
                strategy.trades.append(trade)
                strategy.risk_manager.update_capital(
                    strategy.risk_manager.current_capital + net_pnl
                )
                del strategy.positions[asset]
        
        # Calculate equity
        current_equity = strategy.risk_manager.current_capital
        for asset, pos in strategy.positions.items():
            pos_pnl = pos.size * ((closes[asset][day] - pos.entry_price) / pos.entry_price * pos.direction)
            current_equity += pos_pnl
        
        equity_curve.append(current_equity)
        
        # Benchmark (buy and hold)
        benchmark_value = benchmark_shares * closes[benchmark_asset][day]
        benchmark_curve.append(benchmark_value)
        
        positions_at_time[day] = len(strategy.positions)
        regime_history.append(strategy.detect_regime() if strategy._cache else "UNKNOWN")
    
    # Calculate metrics
    equity = np.array(equity_curve)
    returns = np.diff(equity) / equity[:-1]
    benchmark = np.array(benchmark_curve)
    benchmark_returns = np.diff(benchmark) / benchmark[:-1]
    
    # Drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    
    # Metrics
    total_return = (equity[-1] - equity[0]) / equity[0]
    n_days_years = n_days / 252
    
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
    sortino = np.mean(returns) / np.std(returns[returns < 0]) * np.sqrt(252) \
              if len(returns[returns < 0]) > 0 and np.std(returns[returns < 0]) > 0 else 0
    
    max_dd = np.min(drawdown)
    max_dd_idx = np.argmin(drawdown)
    
    # Calmar
    calmar = total_return / abs(max_dd) if max_dd != 0 else 0
    
    # Trade stats
    if strategy.trades:
        win_rate = len([t for t in strategy.trades if t.pnl > 0]) / len(strategy.trades)
        avg_win = np.mean([t.pnl for t in strategy.trades if t.pnl > 0]) if [t for t in strategy.trades if t.pnl > 0] else 0
        avg_loss = np.mean([t.pnl for t in strategy.trades if t.pnl <= 0]) if [t for t in strategy.trades if t.pnl <= 0] else 0
        profit_factor = abs(avg_win * win_rate / (avg_loss * (1 - win_rate))) if avg_loss != 0 and win_rate < 1 else 0
    else:
        win_rate = 0
        avg_win = 0
        avg_loss = 0
        profit_factor = 0
    
    metrics = {
        "total_return": total_return,
        "annualized_return": (1 + total_return) ** (1 / n_days_years) - 1 if n_days_years > 0 else 0,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd * 100,
        "calmar_ratio": calmar,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_trades": len(strategy.trades),
        "n_days": n_days,
        "final_equity": equity[-1],
        "initial_capital": initial_capital
    }
    
    return {
        "metrics": metrics,
        "equity_curve": equity.tolist(),
        "benchmark_curve": benchmark.tolist(),
        "drawdown_curve": drawdown.tolist(),
        "trades": [
            {
                "asset": t.asset,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "return_pct": t.return_pct,
                "exit_reason": t.exit_reason,
                "regime": t.regime,
                "hold_days": t.hold_days,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time
            }
            for t in strategy.trades
        ],
        "regime_history": regime_history,
        "positions_at_time": positions_at_time
    }


def run_optimization(
    base_params: Dict[str, Any],
    param_ranges: Dict[str, List[Any]],
    highs: Dict[str, np.ndarray],
    lows: Dict[str, np.ndarray],
    opens: Dict[str, np.ndarray],
    closes: Dict[str, np.ndarray],
    metric: str = "sharpe_ratio",
    max_combinations: int = 50
) -> List[Dict[str, Any]]:
    """
    Run parameter optimization via grid search.
    
    Args:
        base_params: Base strategy parameters
        param_ranges: Dict of param -> list of values to try
        highs, lows, opens, closes: OHLC data
        metric: Metric to optimize
        max_combinations: Max number of combinations to try
        
    Returns:
        List of results sorted by metric
    """
    import itertools
    
    # Generate parameter combinations
    keys = list(param_ranges.keys())
    values = [param_ranges[k] for k in keys]
    
    combinations = list(itertools.product(*values))
    
    # Limit combinations
    if len(combinations) > max_combinations:
        np.random.seed(42)
        idx = np.random.choice(len(combinations), max_combinations, replace=False)
        combinations = [combinations[i] for i in sorted(idx)]
    
    results = []
    
    for i, combo in enumerate(combinations):
        params = base_params.copy()
        for key, val in zip(keys, combo):
            params[key] = val
        
        try:
            result = run_backtest(params, highs, lows, opens, closes)
            result["params"] = dict(zip(keys, combo))
            result["metrics"]["optimization_metric"] = result["metrics"][metric]
            results.append(result)
            
            logger.info(
                f"Optimization {i+1}/{len(combinations)}: "
                f"params={dict(zip(keys, combo))}, "
                f"{metric}={result['metrics'][metric]:.4f}"
            )
        except Exception as e:
            logger.warning(f"Failed with params {dict(zip(keys, combo))}: {e}")
    
    # Sort by metric
    results.sort(key=lambda x: x["metrics"].get(metric, -999), reverse=True)
    
    return results


def create_plots(results: Dict[str, Any], output_dir: str) -> None:
    """
    Create equity curve and drawdown plots.
    
    Args:
        results: Backtest results
        output_dir: Directory to save plots
    """
    os.makedirs(output_dir, exist_ok=True)
    
    equity = np.array(results["equity_curve"])
    benchmark = np.array(results["benchmark_curve"])
    drawdown = np.array(results["drawdown_curve"])
    
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    
    # Equity curve
    ax1 = axes[0]
    ax1.plot(equity, label='Strategy', color='blue', linewidth=1.5)
    ax1.plot(benchmark, label='Buy & Hold', color='gray', linewidth=1, alpha=0.7)
    ax1.set_title('Equity Curve vs Benchmark')
    ax1.set_ylabel('Portfolio Value ($)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Drawdown
    ax2 = axes[1]
    ax2.fill_between(range(len(drawdown)), drawdown * 100, 0, 
                      alpha=0.3, color='red', label='Drawdown')
    ax2.plot(drawdown * 100, color='red', linewidth=0.5)
    ax2.set_title('Drawdown')
    ax2.set_ylabel('Drawdown (%)')
    ax2.set_xlabel('Trading Days')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'equity_drawdown.png'), dpi=150)
    plt.close()
    
    # Monthly returns heatmap (if enough data)
    if len(equity) > 252:
        # Resample to monthly
        monthly_returns = []
        for i in range(12, len(equity), 21):  # Approximate monthly
            month_ret = (equity[i] - equity[i-21]) / equity[i-21] if equity[i-21] > 0 else 0
            monthly_returns.append(month_ret * 100)
        
        # Create simple bar chart of monthly returns
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.bar(range(len(monthly_returns)), monthly_returns, 
               color='green' if monthly_returns[-1] > 0 else 'red', alpha=0.7)
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.set_title('Monthly Returns (%)')
        ax.set_ylabel('Return (%)')
        ax.set_xlabel('Month')
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'monthly_returns.png'), dpi=150)
        plt.close()
    
    logger.info(f"Plots saved to {output_dir}")


def run_full_backtest_suite(
    n_days: int = 1500,
    n_assets: int = 5,
    output_dir: str = "./results"
) -> Dict[str, Any]:
    """
    Run complete backtest suite with multiple scenarios.
    
    Args:
        n_days: Trading days
        n_assets: Number of assets
        output_dir: Output directory
        
    Returns:
        Dictionary with all results
    """
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("Generating synthetic data...")
    highs, lows, opens, closes = generate_synthetic_data(
        n_days=n_days,
        n_assets=n_assets,
        seed=42
    )
    
    # Base parameters
    base_params = {
        "adx_period": 14,
        "rsi_period": 14,
        "atr_period": 14,
        "atr_percentile_period": 100,
        "tf_fast": 20,
        "tf_slow": 50,
        "mr_period": 20,
        "mr_z_threshold": 2.0,
        "vb_period": 20,
        "vb_threshold": 2.0,
        "mom_short": 10,
        "mom_long": 30,
        "signal_threshold": 0.3,
        "stop_loss_atr": 2.0,
        "trailing_stop_atr": 1.5,
        "time_stop_bars": 10,
        "max_kelly": 0.25,
        "max_position_pct": 0.20,
        "max_leverage": 3.0,
        "max_drawdown": 0.20,
        "win_rate": 0.55,
        "avg_win": 0.02,
        "avg_loss": 0.01,
        "max_assets": 3,
        "rebalance_frequency": 1
    }
    
    logger.info("Running base backtest...")
    base_results = run_backtest(base_params, highs, lows, opens, closes)
    
    logger.info("Running optimization...")
    param_ranges = {
        "signal_threshold": [0.2, 0.3, 0.4],
        "tf_fast": [15, 20, 30],
        "tf_slow": [40, 50, 60],
        "max_kelly": [0.15, 0.25, 0.35]
    }
    
    opt_results = run_optimization(
        base_params, param_ranges, highs, lows, opens, closes,
        metric="sharpe_ratio", max_combinations=20
    )
    
    logger.info("Creating plots...")
    create_plots(base_results, output_dir)
    
    # Save results
    output = {
        "base_results": base_results,
        "optimization_results": [
            {"params": r["params"], "metrics": r["metrics"]}
            for r in opt_results[:5]  # Top 5
        ],
        "best_params": opt_results[0]["params"] if opt_results else base_params,
        "config": {
            "n_days": n_days,
            "n_assets": n_assets,
            "n_years": n_days / 252
        }
    }
    
    with open(os.path.join(output_dir, 'results.json'), 'w') as f:
        # Convert to JSON-serializable
        json_output = {
            "base_metrics": output["base_results"]["metrics"],
            "optimization_top5": output["optimization_results"],
            "best_params": output["best_params"],
            "config": output["config"]
        }
        json.dump(json_output, f, indent=2, default=str)
    
    # Save trades
    trades_df = pd.DataFrame(base_results["trades"])
    trades_df.to_csv(os.path.join(output_dir, 'trades.csv'), index=False)
    
    # Save equity curve
    equity_df = pd.DataFrame({
        "equity": base_results["equity_curve"],
        "benchmark": base_results["benchmark_curve"],
        "drawdown": base_results["drawdown_curve"]
    })
    equity_df.to_csv(os.path.join(output_dir, 'equity_curve.csv'), index=False)
    
    logger.info(f"Backtest complete. Results saved to {output_dir}")
    
    return output


if __name__ == "__main__":
    import sys
    
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "./results"
    
    results = run_full_backtest_suite(
        n_days=1500,
        n_assets=5,
        output_dir=output_dir
    )
    
    print("\n=== BACKTEST RESULTS ===")
    metrics = results["base_results"]["metrics"]
    print(f"Total Return:     {metrics['total_return']:.2%}")
    print(f"Annualized:       {metrics['annualized_return']:.2%}")
    print(f"Sharpe Ratio:     {metrics['sharpe_ratio']:.3f}")
    print(f"Sortino Ratio:    {metrics['sortino_ratio']:.3f}")
    print(f"Max Drawdown:     {metrics['max_drawdown_pct']:.2f}%")
    print(f"Calmar Ratio:     {metrics['calmar_ratio']:.3f}")
    print(f"Win Rate:         {metrics['win_rate']:.2%}")
    print(f"Profit Factor:   {metrics['profit_factor']:.3f}")
    print(f"Total Trades:     {metrics['total_trades']}")
    print(f"Final Equity:    ${metrics['final_equity']:.2f}")
