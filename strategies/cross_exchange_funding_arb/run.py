#!/usr/bin/env python3
"""
Cross-Exchange Funding Rate Arbitrage - Execution Script

This script runs the funding arbitrage strategy in either backtest or live mode.

Usage:
    python run.py --mode backtest --start 2021-01-01 --end 2026-01-01
    python run.py --mode live --config config/params.yaml
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent / 'backtest'))

from strategy import FundingArbitrageStrategy, StrategyConfig
from risk_manager import RiskLimits
from backtest import FundingBacktester, BacktestConfig
from data_loader import FundingDataLoader
import yaml


def setup_logging(log_level: str = "INFO"):
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('funding_arbitrage.log')
        ]
    )


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def run_backtest(args):
    """Run backtest mode."""
    logger = logging.getLogger(__name__)
    logger.info("="*60)
    logger.info("CROSS-EXCHANGE FUNDING ARBITRAGE - BACKTEST MODE")
    logger.info("="*60)
    
    # Parse dates
    start_date = datetime.strptime(args.start, '%Y-%m-%d')
    end_date = datetime.strptime(args.end, '%Y-%m-%d')
    
    # Load or create configuration
    if args.config:
        config_dict = load_config(args.config)
        strategy_config = StrategyConfig(**config_dict.get('strategy', {}))
        risk_limits = RiskLimits(**config_dict.get('risk', {}))
    else:
        strategy_config = StrategyConfig()
        risk_limits = RiskLimits()
    
    # Create strategy
    strategy = FundingArbitrageStrategy(
        config=strategy_config,
        risk_limits=risk_limits
    )
    
    # Create backtester
    backtest_config = BacktestConfig(
        initial_capital=args.capital,
        maker_fee=args.maker_fee,
        taker_fee=args.taker_fee
    )
    
    backtester = FundingBacktester(strategy, backtest_config)
    
    # Load data
    logger.info(f"Loading data from {start_date.date()} to {end_date.date()}...")
    loader = FundingDataLoader()
    
    data = loader.load_synthetic_data(
        exchanges=strategy_config.exchanges,
        symbols=strategy_config.symbols,
        start_date=start_date,
        end_date=end_date,
        add_stress_periods=True
    )
    
    # Print data statistics
    stats_df = loader.calculate_summary_statistics(data)
    logger.info("\nFunding Rate Statistics:")
    print(stats_df.to_string())
    
    # Run backtest
    logger.info("\nRunning backtest...")
    results = backtester.run(data)
    
    # Print results
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    
    print(f"\nPerformance Metrics:")
    print(f"  Total Return: {results['total_return_pct']:.2f}%")
    print(f"  Total Profit: ${results['total_return_usd']:,.2f}")
    print(f"  Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {results['max_drawdown_pct']:.2f}%")
    
    print(f"\nTrade Statistics:")
    print(f"  Total Trades: {results['total_trades']}")
    print(f"  Win Rate: {results['win_rate']:.1f}%")
    print(f"  Profit Factor: {results['profit_factor']:.2f}")
    print(f"  Avg Trade PnL: ${results['avg_trade_pnl']:,.2f}")
    print(f"  Avg Win: ${results['avg_win']:,.2f}")
    print(f"  Avg Loss: ${results['avg_loss']:,.2f}")
    
    print(f"\nFunding Breakdown:")
    print(f"  Total Funding Earned: ${results['total_funding_earned']:,.2f}")
    print(f"  Trading Fees: ${results['total_trading_fees']:,.2f}")
    print(f"  Slippage: ${results['total_slippage']:,.2f}")
    print(f"  Net Funding Premium: ${results['net_funding_premium']:,.2f}")
    
    print(f"\nHold Statistics:")
    print(f"  Avg Hold Time: {results['avg_hold_time_hours']:.1f} hours")
    
    print(f"\nCapital:")
    print(f"  Initial: ${args.capital:,.2f}")
    print(f"  Final: ${results['final_capital']:,.2f}")
    
    print("="*60)
    
    # Save trade report
    if args.output:
        trade_report = backtester.get_trade_report()
        trade_report.to_csv(args.output, index=False)
        logger.info(f"Trade report saved to {args.output}")
        
        equity_curve = backtester.get_equity_curve()
        equity_curve.to_csv(args.output.replace('.csv', '_equity.csv'))
        logger.info(f"Equity curve saved to {args.output.replace('.csv', '_equity.csv')}")
    
    return results


def run_live(args):
    """Run live trading mode (placeholder)."""
    logger = logging.getLogger(__name__)
    logger.warning("="*60)
    logger.warning("LIVE TRADING MODE - PLACEHOLDER IMPLEMENTATION")
    logger.warning("="*60)
    
    # Load configuration
    if args.config:
        config_dict = load_config(args.config)
        strategy_config = StrategyConfig(**config_dict.get('strategy', {}))
        risk_limits = RiskLimits(**config_dict.get('risk', {}))
    else:
        strategy_config = StrategyConfig()
        risk_limits = RiskLimits()
    
    # Create strategy
    strategy = FundingArbitrageStrategy(
        config=strategy_config,
        risk_limits=risk_limits
    )
    
    logger.info("Strategy initialized for live trading")
    logger.info(f"Symbols: {strategy_config.symbols}")
    logger.info(f"Exchanges: {strategy_config.exchanges}")
    
    # TODO: Implement live trading loop with exchange APIs
    logger.warning("Live trading implementation requires exchange API integration")
    logger.warning("This is a placeholder - do not run with real funds")


def main():
    parser = argparse.ArgumentParser(
        description='Cross-Exchange Funding Rate Arbitrage Strategy'
    )
    
    parser.add_argument(
        '--mode',
        choices=['backtest', 'live'],
        default='backtest',
        help='Operating mode (default: backtest)'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default='config/params.yaml',
        help='Path to configuration file'
    )
    
    # Backtest arguments
    parser.add_argument(
        '--start',
        type=str,
        default='2021-01-01',
        help='Backtest start date (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--end',
        type=str,
        default='2026-01-01',
        help='Backtest end date (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--capital',
        type=float,
        default=100000.0,
        help='Initial capital for backtest'
    )
    
    parser.add_argument(
        '--maker-fee',
        type=float,
        default=0.0002,
        help='Maker fee rate'
    )
    
    parser.add_argument(
        '--taker-fee',
        type=float,
        default=0.0005,
        help='Taker fee rate'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='trade_report.csv',
        help='Output file for trade report'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_level)
    
    # Run appropriate mode
    if args.mode == 'backtest':
        run_backtest(args)
    elif args.mode == 'live':
        run_live(args)


if __name__ == '__main__':
    main()
