"""
StatArb Alpha: Cointegrated Pairs Trading with Kalman Filter (Orchestrator)
-------------------------------------------------------------------------
Author: ATLAS Quant Research
Strategy: StatArb Alpha
Logic: Cointegrated Pairs Trading with Kalman Filter
Date: 2026-03-22
-------------------------------------------------------------------------
"""

import numpy as np
import pandas as pd
import yaml
import logging
from typing import Dict, List, Tuple, Optional

# Local modules
try:
    from .kalman_filter import KalmanFilter
    from .cointegration import CointegrationTest
    from .signal_generator import SignalGenerator
    from .risk_manager import RiskManager
except ImportError:
    from kalman_filter import KalmanFilter
    from cointegration import CointegrationTest
    from signal_generator import SignalGenerator
    from risk_manager import RiskManager

class StatArbStrategy:
    """
    Main orchestrator for the StatArb strategy.
    It manages the data flow between Kalman filtering, cointegration testing,
    signal generation, and risk management.
    """
    
    def __init__(self, config_path: str = "config/params.yaml"):
        """
        Initialize the strategy with the provided configuration file.
        :param config_path: Path to the YAML configuration file.
        """
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
            
        # Strategy Parameters
        self.pairs = self.config.get('pairs', [['SOL', 'ETH']])
        self.z_threshold = self.config.get('z_score_threshold', 2.0)
        self.lookback = self.config.get('lookback_period', 180)
        self.max_half_life = self.config.get('max_half_life', 15)
        
        # Initialize Sub-modules for each pair
        self.kalman_filters = {tuple(pair): KalmanFilter() for pair in self.pairs}
        self.coint_tests = {tuple(pair): CointegrationTest() for pair in self.pairs}
        self.signal_gens = {tuple(pair): SignalGenerator(z_threshold=self.z_threshold) for pair in self.pairs}
        self.risk_manager = RiskManager()
        
        # Performance Tracking
        self.trades = []
        self.equity_curve = [100000.0]
        self.log = logging.getLogger("StatArbStrategy")
        self._setup_logging()

    def _setup_logging(self):
        """Configure the strategy logger."""
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.log.addHandler(handler)
        self.log.setLevel(logging.INFO)

    def process_data(self, pair: Tuple[str, str], df: pd.DataFrame):
        """
        Process a time series of price data for a specific pair.
        :param pair: Tuple containing the names of the two assets.
        :param df: Pandas DataFrame with 'price_x' and 'price_y' columns.
        """
        self.log.info(f"Processing pair: {pair[0]}/{pair[1]} with {len(df)} data points.")
        
        # 1. Cointegration Check
        # We need a long-term check to see if the relationship exists.
        is_cointegrated = self.coint_tests[pair].check_cointegration(
            df['price_x'].values, df['price_y'].values
        )
        
        if not is_cointegrated:
            self.log.warning(f"Pair {pair[0]}/{pair[1]} is not cointegrated (p > 0.05). Skipping.")
            return
            
        # 2. Kalman Filtering and Spread Calculation
        # We'll use the Kalman Filter to estimate the dynamic hedge ratio (beta).
        prices_x = df['price_x'].values
        prices_y = df['price_y'].values
        
        kf = self.kalman_filters[pair]
        spreads = []
        betas = []
        
        # Batch process to get initial states and current spreads
        for x, y in zip(prices_x, prices_y):
            y_est, error, f_var = kf.step(x, y)
            spreads.append(error)
            betas.append(kf.get_hedge_ratio())
            
        spreads = np.array(spreads)
        
        # 3. Half-life Estimation
        # Check if the spread is mean-reverting enough.
        half_life = self.coint_tests[pair].calculate_half_life(spreads)
        if half_life > self.max_half_life:
            self.log.warning(f"Pair {pair[0]}/{pair[1]} has high half-life ({half_life:.2f} > {self.max_half_life}). Skipping.")
            return

        # 4. Signal Generation and Risk Management
        # Calculate Z-score of the spread
        z_scores = self.coint_tests[pair].calculate_z_score(spreads, window=self.lookback)
        
        for i in range(self.lookback, len(z_scores)):
            current_z = z_scores[i]
            current_beta = betas[i]
            
            # Generate Signal
            signal, reason = self.signal_gens[pair].generate_signal(current_z)
            
            if signal != 0:
                # We are in a position, calculate size and hypothetical PnL
                # For this orchestrator, we track the trades.
                # Simplified PnL calculation: change in spread * hedge ratio * size
                pnl = 0.0
                if i > 0:
                    delta_spread = spreads[i] - spreads[i-1]
                    # If Long Spread (Buy X, Sell Y), Profit if spread increases
                    # If Short Spread (Sell X, Buy Y), Profit if spread decreases
                    pnl = signal * delta_spread * current_beta
                
                # Risk Management
                # Check for drawdown limits
                if self.risk_manager.check_drawdown_limit(self.equity_curve[-1]):
                    self.log.error(f"Drawdown limit reached. Strategy halted.")
                    break
                    
                # Update portfolio
                self.risk_manager.update_portfolio(pnl)
                self.equity_curve.append(self.risk_manager.current_portfolio_value)
                
                if "Entry" in reason:
                    self.log.info(f"TRADE: {reason} at Index {i} (Z: {current_z:.2f}, Beta: {current_beta:.4f})")
                    self.trades.append({
                        'pair': pair,
                        'index': i,
                        'signal': signal,
                        'reason': reason,
                        'z_score': current_z,
                        'beta': current_beta,
                        'pnl': pnl
                    })

    def run(self, data_dict: Dict[Tuple[str, str], pd.DataFrame]):
        """
        Main run loop for the strategy.
        :param data_dict: Dictionary mapping pair tuples to price dataframes.
        """
        self.log.info("Starting StatArb Alpha execution...")
        
        for pair in self.pairs:
            pair_tuple = tuple(pair)
            if pair_tuple in data_dict:
                self.process_data(pair_tuple, data_dict[pair_tuple])
            else:
                self.log.error(f"No data found for pair: {pair[0]}/{pair[1]}")
                
        self.log.info(f"Strategy execution finished. Total trades: {len(self.trades)}")
        self.report()

    def report(self):
        """Generate a summary report of the strategy performance."""
        if not self.trades:
            self.log.info("No trades executed.")
            return
            
        df_trades = pd.DataFrame(self.trades)
        total_pnl = df_trades['pnl'].sum()
        win_rate = (df_trades['pnl'] > 0).mean()
        
        self.log.info(f"--- Strategy Performance Summary ---")
        self.log.info(f"Total PnL: ${total_pnl:.2f}")
        self.log.info(f"Win Rate: {win_rate:.2%}")
        self.log.info(f"Total Trades: {len(df_trades)}")
        self.log.info(f"Ending Equity: ${self.equity_curve[-1]:.2f}")
        self.log.info(f"------------------------------------")

if __name__ == "__main__":
    # Example usage (simulated)
    import os
    if not os.path.exists("config/params.yaml"):
        # We need to use relative path in some environments
        strat = StatArbStrategy(config_path="strategies/stat-arb-kalman/config/params.yaml")
    else:
        strat = StatArbStrategy()
    
    # Simulate some price data (highly correlated cointegrated prices)
    n = 1000
    t = np.arange(n)
    
    # Asset X is a random walk
    x = 100 + np.cumsum(np.random.normal(0, 0.5, n))
    
    # Asset Y is cointegrated with X: Y = 0.5 * X + 10 + stationary_noise
    beta = 0.5
    intercept = 10.0
    noise = np.random.normal(0, 1.0, n)
    y = beta * x + intercept + noise
    
    data = pd.DataFrame({'price_x': x, 'price_y': y})
    data_dict = {('SOL', 'ETH'): data}
    
    strat.run(data_dict)
