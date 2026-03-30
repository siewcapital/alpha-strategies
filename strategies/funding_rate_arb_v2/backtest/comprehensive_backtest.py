"""
Comprehensive Backtest Runner for Funding Rate Arbitrage V2

Runs multiple backtest configurations and generates detailed reports.
Includes parameter sweeps and sensitivity analysis.

Author: ATLAS
Date: March 30, 2026
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import json
import itertools

import numpy as np
import pandas as pd

from backtest_engine import BacktestConfig, BacktestEngine, BacktestResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ComprehensiveBacktestRunner:
    """
    Runs comprehensive backtests with multiple configurations.
    """
    
    def __init__(self, output_dir: str = "results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.results: List[Tuple[BacktestConfig, BacktestResult]] = []
    
    def generate_realistic_synthetic_data(self, exchanges: List[str], symbols: List[str],
                                         days: int = 1095,
                                         base_spread_mean: float = 0.0002,
                                         base_spread_std: float = 0.0003) -> pd.DataFrame:
        """
        Generate synthetic data with realistic funding spreads.
        
        This creates data where exchanges have systematic biases and
        occasional large divergences (the alpha we're trying to capture).
        """
        logger.info(f"Generating realistic synthetic data with spreads for {days} days")
        
        records = []
        start_date = datetime(2021, 1, 1)
        
        # Generate funding times (every 8 hours)
        funding_times = pd.date_range(
            start=start_date,
            periods=days * 3,
            freq='8h'
        )
        
        for symbol in symbols:
            # Symbol-specific parameters
            base_funding = np.random.uniform(-0.00005, 0.00015)
            volatility = np.random.uniform(0.00015, 0.0005)
            
            # Generate base funding rate (market-wide component)
            market_funding = []
            current = base_funding
            for _ in funding_times:
                theta = 0.2
                mu = base_funding
                current += theta * (mu - current) + np.random.normal(0, volatility)
                current = max(-0.005, min(0.005, current))
                market_funding.append(current)
            
            for exchange in exchanges:
                # Exchange-specific bias (systematic differences)
                if exchange == 'binance':
                    exchange_bias = np.random.normal(0, 0.00002)  # Slight negative bias
                elif exchange == 'bybit':
                    exchange_bias = np.random.normal(0.00005, 0.00003)  # Slight positive bias
                else:  # okx
                    exchange_bias = np.random.normal(0.00002, 0.000025)
                
                # Generate funding with spread opportunities
                for i, t in enumerate(funding_times):
                    # Base rate + exchange bias
                    rate = market_funding[i] + exchange_bias
                    
                    # Add occasional large divergences (the alpha)
                    if np.random.random() < 0.05:  # 5% chance of divergence
                        divergence = np.random.choice([-1, 1]) * np.random.uniform(0.0002, 0.001)
                        rate += divergence
                    
                    # Add noise
                    rate += np.random.normal(0, 0.00005)
                    
                    # Clamp
                    rate = max(-0.01, min(0.01, rate))
                    
                    records.append({
                        'timestamp': t,
                        'exchange': exchange,
                        'symbol': symbol,
                        'funding_rate': rate
                    })
        
        df = pd.DataFrame(records)
        logger.info(f"Generated {len(df)} realistic funding records")
        
        # Verify spreads exist
        self._verify_spreads(df)
        
        return df
    
    def _verify_spreads(self, df: pd.DataFrame):
        """Verify that meaningful spreads exist in the data."""
        spreads = []
        
        for symbol in df['symbol'].unique():
            symbol_data = df[df['symbol'] == symbol]
            
            for timestamp in symbol_data['timestamp'].unique():
                ts_data = symbol_data[symbol_data['timestamp'] == timestamp]
                
                if len(ts_data) >= 2:
                    rates = ts_data['funding_rate'].values
                    spread = abs(rates.max() - rates.min())
                    spreads.append(spread)
        
        if spreads:
            mean_spread = np.mean(spreads)
            max_spread = np.max(spreads)
            annualized_mean = mean_spread * 3 * 365
            annualized_max = max_spread * 3 * 365
            
            logger.info(f"Spread statistics:")
            logger.info(f"  Mean spread (8h): {mean_spread:.6f} ({annualized_mean:.2%} annualized)")
            logger.info(f"  Max spread (8h): {max_spread:.6f} ({annualized_max:.2%} annualized)")
    
    def run_single_backtest(self, config: BacktestConfig, 
                           funding_data: pd.DataFrame) -> BacktestResult:
        """Run a single backtest with given configuration."""
        engine = BacktestEngine(config)
        engine.funding_df = funding_data
        
        result = engine.run()
        return result
    
    def run_parameter_sweep(self, funding_data: pd.DataFrame) -> pd.DataFrame:
        """
        Run backtests with different parameter combinations.
        """
        logger.info("Starting parameter sweep...")
        
        # Parameter grid
        entry_thresholds = [0.10, 0.15, 0.20, 0.25]
        min_persistence_values = [0.6, 0.7, 0.8]
        use_maker_only_options = [True, False]
        
        results = []
        
        for entry_thresh, persistence, maker_only in itertools.product(
            entry_thresholds, min_persistence_values, use_maker_only_options
        ):
            config = BacktestConfig(
                start_date=datetime(2021, 1, 1),
                end_date=datetime(2024, 1, 1),
                initial_capital=100000,
                entry_threshold=entry_thresh,
                exit_threshold=entry_thresh * 0.33,  # Exit at 1/3 of entry
                min_persistence=persistence,
                maker_fee=0.0002,
                taker_fee=0.0005,
                slippage_bps=2.0,
                use_maker_only=maker_only
            )
            
            logger.info(f"Testing: entry={entry_thresh}, persistence={persistence}, maker={maker_only}")
            
            result = self.run_single_backtest(config, funding_data)
            
            results.append({
                'entry_threshold': entry_thresh,
                'min_persistence': persistence,
                'use_maker_only': maker_only,
                'total_return': result.total_return,
                'annualized_return': result.annualized_return,
                'sharpe_ratio': result.sharpe_ratio,
                'max_drawdown': result.max_drawdown,
                'calmar_ratio': result.calmar_ratio,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'total_trades': result.total_trades,
                'avg_hold_time': result.avg_hold_time
            })
            
            self.results.append((config, result))
        
        df = pd.DataFrame(results)
        
        # Save results
        output_file = self.output_dir / "parameter_sweep.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved parameter sweep results to {output_file}")
        
        return df
    
    def run_cost_sensitivity(self, funding_data: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze sensitivity to transaction costs.
        """
        logger.info("Running cost sensitivity analysis...")
        
        fee_levels = [
            (0.0001, 0.0002),  # Low fees (VIP rates)
            (0.0002, 0.0005),  # Standard rates
            (0.0003, 0.0007),  # High fees
        ]
        
        slippage_levels = [1.0, 2.0, 5.0]  # bps
        
        results = []
        
        for (maker, taker), slippage in itertools.product(fee_levels, slippage_levels):
            config = BacktestConfig(
                start_date=datetime(2021, 1, 1),
                end_date=datetime(2024, 1, 1),
                initial_capital=100000,
                entry_threshold=0.15,
                exit_threshold=0.05,
                min_persistence=0.7,
                maker_fee=maker,
                taker_fee=taker,
                slippage_bps=slippage,
                use_maker_only=True
            )
            
            logger.info(f"Testing: maker={maker:.4%}, taker={taker:.4%}, slippage={slippage}bps")
            
            result = self.run_single_backtest(config, funding_data)
            
            results.append({
                'maker_fee': maker,
                'taker_fee': taker,
                'slippage_bps': slippage,
                'total_return': result.total_return,
                'annualized_return': result.annualized_return,
                'sharpe_ratio': result.sharpe_ratio,
                'max_drawdown': result.max_drawdown,
                'calmar_ratio': result.calmar_ratio,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'total_trades': result.total_trades
            })
        
        df = pd.DataFrame(results)
        
        output_file = self.output_dir / "cost_sensitivity.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"Saved cost sensitivity results to {output_file}")
        
        return df
    
    def generate_report(self) -> str:
        """Generate comprehensive backtest report."""
        report_lines = []
        
        report_lines.append("=" * 80)
        report_lines.append("FUNDING RATE ARBITRAGE V2 - COMPREHENSIVE BACKTEST REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"Generated: {datetime.now().isoformat()}")
        report_lines.append("")
        
        # Best configuration
        if self.results:
            report_lines.append("-" * 80)
            report_lines.append("BEST PERFORMING CONFIGURATION")
            report_lines.append("-" * 80)
            
            # Find best by Sharpe ratio
            best_sharpe = max(self.results, key=lambda x: x[1].sharpe_ratio if x[1].total_trades > 0 else -1)
            config, result = best_sharpe
            
            report_lines.append(f"Entry Threshold: {config.entry_threshold:.2%}")
            report_lines.append(f"Min Persistence: {config.min_persistence}")
            report_lines.append(f"Maker Only: {config.use_maker_only}")
            report_lines.append("")
            report_lines.append(f"Total Return: {result.total_return:.2%}")
            report_lines.append(f"Annualized Return: {result.annualized_return:.2%}")
            report_lines.append(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
            report_lines.append(f"Max Drawdown: {result.max_drawdown:.2%}")
            report_lines.append(f"Calmar Ratio: {result.calmar_ratio:.2f}")
            report_lines.append(f"Win Rate: {result.win_rate:.2%}")
            report_lines.append(f"Total Trades: {result.total_trades}")
            report_lines.append("")
        
        # Summary statistics
        report_lines.append("-" * 80)
        report_lines.append("ALL CONFIGURATIONS SUMMARY")
        report_lines.append("-" * 80)
        
        for config, result in self.results:
            report_lines.append(f"\nEntry: {config.entry_threshold:.0%}, "
                              f"Persist: {config.min_persistence}, "
                              f"Maker: {config.use_maker_only}")
            report_lines.append(f"  Return: {result.annualized_return:+.2%}, "
                              f"Sharpe: {result.sharpe_ratio:.2f}, "
                              f"Trades: {result.total_trades}")
        
        report_lines.append("")
        report_lines.append("=" * 80)
        
        report = "\n".join(report_lines)
        
        # Save report
        report_file = self.output_dir / "backtest_report.txt"
        with open(report_file, 'w') as f:
            f.write(report)
        
        logger.info(f"Saved report to {report_file}")
        return report


def main():
    """Run comprehensive backtest suite."""
    runner = ComprehensiveBacktestRunner(output_dir="backtest/results")
    
    # Generate realistic synthetic data
    funding_data = runner.generate_realistic_synthetic_data(
        exchanges=['binance', 'bybit', 'okx'],
        symbols=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        days=1095  # 3 years
    )
    
    # Save generated data
    data_file = runner.output_dir / "synthetic_funding_data.csv"
    funding_data.to_csv(data_file, index=False)
    logger.info(f"Saved synthetic data to {data_file}")
    
    # Run parameter sweep
    sweep_results = runner.run_parameter_sweep(funding_data)
    
    # Run cost sensitivity
    cost_results = runner.run_cost_sensitivity(funding_data)
    
    # Generate report
    report = runner.generate_report()
    print(report)
    
    # Print summary
    print("\n" + "=" * 80)
    print("TOP 5 CONFIGURATIONS BY SHARPE RATIO")
    print("=" * 80)
    
    sorted_results = sorted(
        [(c, r) for c, r in runner.results if r.total_trades > 0],
        key=lambda x: x[1].sharpe_ratio,
        reverse=True
    )[:5]
    
    for i, (config, result) in enumerate(sorted_results, 1):
        print(f"\n{i}. Entry: {config.entry_threshold:.0%}, "
              f"Persist: {config.min_persistence}, Maker: {config.use_maker_only}")
        print(f"   Return: {result.annualized_return:+.2%}, "
              f"Sharpe: {result.sharpe_ratio:.2f}, "
              f"DD: {result.max_drawdown:.2%}, "
              f"Trades: {result.total_trades}")


if __name__ == "__main__":
    main()
