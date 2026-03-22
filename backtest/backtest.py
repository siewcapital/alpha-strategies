"""
StatArb Alpha: Backtest Engine
------------------------------
This script runs the StatArb strategy on historical or synthetic data
and generates comprehensive performance metrics and plots.
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import json
from datetime import datetime, timedelta

# Local imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(project_root, "src"))

try:
    from .strategy import StatArbStrategy
except ImportError:
    from strategy import StatArbStrategy

class BacktestEngine:
    """
    Handles data generation, strategy execution, and results analysis.
    """
    def __init__(self, strategy: StatArbStrategy):
        self.strategy = strategy
        self.results_dir = os.path.join(project_root, "results")
        os.makedirs(self.results_dir, exist_ok=True)

    def generate_synthetic_data(self, pair: tuple, n_points: int = 2000) -> pd.DataFrame:
        """
        Generate synthetic cointegrated price data for testing.
        :param pair: The pair (e.g., SOL, ETH).
        :param n_points: Number of data points.
        :return: DataFrame with prices.
        """
        np.random.seed(42)
        # Asset X is a random walk
        x = 100 + np.cumsum(np.random.normal(0, 0.1, n_points))
        
        # Cointegrated Y with a fixed hedge ratio for initial test
        beta = 0.5
        intercept = 10.0
        # Stationary noise (mean reverting)
        noise = np.random.normal(0, 0.1, n_points)
        
        # Add some jumps to test signals
        noise[500:550] += 2.0
        noise[1200:1250] -= 2.0
        
        y = beta * x + intercept + noise
        
        # Combine into DataFrame
        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2021-01-01', periods=n_points, freq='h'),
            'price_x': x,
            'price_y': y
        })
        return df

    def calculate_metrics(self, equity_curve: list, trades: list) -> dict:
        """
        Calculate quantitative performance metrics.
        """
        equity = np.array(equity_curve)
        returns = np.diff(equity) / equity[:-1]
        
        # Risk-free rate (assumed 5% annual, 0% hourly)
        # Sharpe ratio
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(24 * 365) if np.std(returns) > 0 else 0
        
        # Sortino ratio (downside risk)
        downside_returns = returns[returns < 0]
        sortino = np.mean(returns) / np.std(downside_returns) * np.sqrt(24 * 365) if len(downside_returns) > 0 else 0
        
        # Max Drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_drawdown = np.max(drawdown)
        
        # Win Rate
        trades_df = pd.DataFrame(trades)
        win_rate = (trades_df['pnl'] > 0).mean() if not trades_df.empty else 0
        
        # Total PnL
        total_pnl = equity[-1] - 100000.0
        
        metrics = {
            'Sharpe Ratio': float(sharpe),
            'Sortino Ratio': float(sortino),
            'Max Drawdown': float(max_drawdown),
            'Win Rate': float(win_rate),
            'Total PnL': float(total_pnl),
            'Total Trades': int(len(trades))
        }
        return metrics

    def plot_results(self, equity_curve: list, metrics: dict, pair: tuple, df: pd.DataFrame):
        """
        Generate visual performance plots.
        """
        plt.style.use('ggplot')
        fig, axes = plt.subplots(3, 1, figsize=(12, 18))
        
        # 1. Equity Curve
        axes[0].plot(equity_curve, color='blue', label='Strategy Equity')
        axes[0].set_title(f"Equity Curve - StatArb Alpha ({pair[0]}/{pair[1]})")
        axes[0].set_xlabel("Time (Hours)")
        axes[0].set_ylabel("Portfolio Value ($)")
        axes[0].legend()
        
        # 2. Drawdown
        equity = np.array(equity_curve)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        axes[1].fill_between(range(len(drawdown)), 0, -drawdown, color='red', alpha=0.3)
        axes[1].set_title("Drawdown Analysis")
        axes[1].set_xlabel("Time (Hours)")
        axes[1].set_ylabel("Drawdown (%)")
        
        # 3. Spread and Trades
        # We need to recalculate the spread for plotting (this is simplified)
        # In a real system, we'd store the spread in the strategy.
        axes[2].set_title("Prices (X and Y)")
        axes[2].plot(df['price_x'], label=f'Price {pair[0]}', color='green', alpha=0.6)
        axes[2].plot(df['price_y'], label=f'Price {pair[1]}', color='purple', alpha=0.6)
        axes[2].set_ylabel("Price ($)")
        axes[2].legend()
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.results_dir, f"equity_curve_{pair[0]}_{pair[1]}.png"))
        plt.close()
        
        # Save metrics as JSON
        with open(os.path.join(self.results_dir, "metrics.json"), "w") as f:
            json.dump(metrics, f, indent=4)

    def run(self):
        """Execute the full backtest pipeline."""
        print(f"--- Starting StatArb Alpha Backtest: {datetime.now()} ---")
        
        # Process each pair
        data_dict = {}
        for pair in self.strategy.pairs:
            pair_tuple = tuple(pair)
            df = self.generate_synthetic_data(pair_tuple)
            data_dict[pair_tuple] = df
            
        # Run Strategy
        self.strategy.run(data_dict)
        
        # Analyze Results
        if self.strategy.trades:
            # For this simplified backtest, we analyze the first pair's results
            pair = tuple(self.strategy.pairs[0])
            metrics = self.calculate_metrics(self.strategy.equity_curve, self.strategy.trades)
            print(f"Metrics: {metrics}")
            
            self.plot_results(
                self.strategy.equity_curve, 
                metrics, 
                pair, 
                data_dict[pair]
            )
            print(f"Backtest plots saved to {self.results_dir}")
        else:
            print("No trades were generated during the backtest.")

if __name__ == "__main__":
    # Ensure dependencies are installed (pseudo-check)
    # import yaml, matplotlib, seaborn, statsmodels
    
    # Use config relative to backtest script
    config_path = os.path.join(project_root, "config", "params.yaml")
    strat = StatArbStrategy(config_path=config_path)
    engine = BacktestEngine(strat)
    engine.run()
