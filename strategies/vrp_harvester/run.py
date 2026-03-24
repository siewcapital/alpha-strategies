"""
Run script for VRP Harvester Strategy

Provides CLI interface for:
- Backtesting
- Paper trading
- Live trading

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import argparse
import yaml
import logging
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data_loader import create_backtest_data
from backtest.backtest import BacktestEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def run_backtest(args):
    """Run strategy backtest"""
    logger.info("=" * 60)
    logger.info("VRP HARVESTER BACKTEST")
    logger.info("=" * 60)
    
    # Load configuration and flatten
    raw_config = load_config(args.config)
    
    # Flatten nested config and map keys correctly
    config = {}
    # Entry params
    entry = raw_config.get('entry', {})
    config['iv_rank_threshold'] = entry.get('iv_rank_min', 70)  # Strategy uses iv_rank_threshold
    config['iv_percentile_min'] = entry.get('iv_percentile_min', 70)
    config['vrp_min_threshold'] = entry.get('vrp_min', 0.05)  # Strategy uses vrp_min_threshold
    config['vrp_optimal'] = entry.get('vrp_optimal', 0.15)
    config['max_dte_entry'] = entry.get('max_dte_entry', 21)
    config['min_dte_entry'] = entry.get('min_dte_entry', 7)
    config['trend_filter'] = entry.get('trend_filter', True)
    config['min_adx'] = entry.get('min_adx', 20)
    
    # Exit params
    exit_p = raw_config.get('exit', {})
    config['profit_target'] = exit_p.get('profit_target', 0.50)
    config['stop_loss'] = exit_p.get('stop_loss', 2.00)
    config['time_stop_dte'] = exit_p.get('time_stop_dte', 5)
    
    # Hedging params
    hedge = raw_config.get('hedging', {})
    config['delta_threshold'] = hedge.get('delta_threshold', 0.15)
    config['target_delta'] = hedge.get('target_delta', 0.05)
    
    # Risk params
    risk = raw_config.get('risk', {})
    config['max_positions'] = risk.get('max_correlated_positions', 3)
    config['max_drawdown_pct'] = risk.get('max_drawdown_pct', 0.10)
    config['daily_loss_limit'] = risk.get('daily_loss_limit', 0.02)
    config['consecutive_loss_limit'] = risk.get('consecutive_loss_limit', 3)
    config['dvol_filter'] = risk.get('vix_upper_limit', 80)
    
    # Signal generator uses different key names
    config['iv_rank_min'] = config['iv_rank_threshold']
    config['vrp_min'] = config['vrp_min_threshold']
    config['dvol_max'] = config['dvol_filter']
    
    logger.info(f"Config loaded: IV Rank Min={config['iv_rank_threshold']}, VRP Min={config['vrp_min_threshold']}")
    
    # Determine date range
    end_date = datetime.now()
    if args.years:
        start_date = end_date - timedelta(days=int(args.years * 365))
    else:
        start_date = end_date - timedelta(days=365)
    
    logger.info(f"Backtest period: {start_date.date()} to {end_date.date()}")
    
    # Generate/load data
    logger.info("Loading data...")
    data = create_backtest_data(
        start_date=start_date,
        end_date=end_date,
        use_real_data=args.real_data
    )
    
    logger.info(f"Data loaded: {len(data)} assets, {len(list(data.values())[0])} periods")
    
    # Run backtest
    backtest_config = {
        'initial_capital': args.capital,
        'commission_rate': 0.001,
        'slippage': 0.001,
        'hedge_cost': 0.0005
    }
    
    engine = BacktestEngine(backtest_config, config)
    results = engine.run(data)
    
    # Print results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Initial Capital:    ${results.get('initial_capital', args.capital):,.0f}")
    print(f"Final Capital:      ${results.get('final_capital', args.capital):,.0f}")
    print(f"Total Return:       {results.get('total_return', 0):.2%}")
    print(f"Total P&L:          ${results.get('total_pnl', 0):,.0f}")
    print(f"Sharpe Ratio:       {results.get('sharpe_ratio', 0):.2f}")
    print(f"Max Drawdown:       {results.get('max_drawdown', 0):.2%}")
    print(f"Win Rate:           {results.get('win_rate', 0):.1%}")
    print(f"Profit Factor:      {results.get('profit_factor', 0):.2f}")
    print(f"Number of Trades:   {results.get('num_trades', 0)}")
    print(f"Winning Trades:     {results.get('winning_trades', 0)}")
    print(f"Losing Trades:      {results.get('losing_trades', 0)}")
    print(f"Average Trade:      ${results.get('avg_trade_pnl', 0):,.0f}")
    print(f"Average Win:        ${results.get('avg_win', 0):,.0f}")
    print(f"Average Loss:       ${results.get('avg_loss', 0):,.0f}")
    
    if results['exit_analysis']:
        print("\nExit Analysis:")
        for reason, stats in results['exit_analysis'].items():
            print(f"  {reason}: {stats['count']} trades, ${stats['pnl']:,.0f}")
    
    # Save results if requested
    if args.output:
        import json
        # Convert to serializable format
        output_results = {k: v for k, v in results.items() 
                         if k not in ['equity_curve', 'trades']}
        with open(args.output, 'w') as f:
            json.dump(output_results, f, indent=2, default=str)
        logger.info(f"Results saved to {args.output}")
    
    return results


def run_paper_trading(args):
    """Run paper trading mode"""
    logger.info("Starting paper trading mode...")
    config = load_config(args.config)
    
    # TODO: Implement paper trading loop
    # This would connect to exchange APIs in paper mode
    logger.info("Paper trading not yet implemented")
    logger.info("Use backtest mode for now")


def run_live_trading(args):
    """Run live trading mode"""
    logger.warning("=" * 60)
    logger.warning("LIVE TRADING MODE")
    logger.warning("=" * 60)
    logger.warning("This will trade with REAL MONEY!")
    logger.warning("Press Ctrl+C within 5 seconds to cancel...")
    
    import time
    time.sleep(5)
    
    config = load_config(args.config)
    
    # TODO: Implement live trading loop
    logger.info("Live trading not yet implemented")


def main():
    parser = argparse.ArgumentParser(
        description='VRP Harvester Strategy - Crypto Volatility Risk Premium Harvesting',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run backtest with default settings
  python run.py backtest
  
  # Run 3-year backtest with $200k capital
  python run.py backtest --years 3 --capital 200000
  
  # Run with custom config
  python run.py backtest --config my_config.yaml
  
  # Run paper trading
  python run.py paper --config config/params.yaml
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Backtest command
    backtest_parser = subparsers.add_parser('backtest', help='Run backtest')
    backtest_parser.add_argument('--config', default='config/params.yaml',
                                help='Configuration file path')
    backtest_parser.add_argument('--years', type=float, default=3,
                                help='Number of years to backtest')
    backtest_parser.add_argument('--capital', type=float, default=100000,
                                help='Initial capital')
    backtest_parser.add_argument('--real-data', action='store_true',
                                help='Use real market data (requires yfinance)')
    backtest_parser.add_argument('--output', type=str,
                                help='Output file for results (JSON)')
    
    # Paper trading command
    paper_parser = subparsers.add_parser('paper', help='Run paper trading')
    paper_parser.add_argument('--config', default='config/params.yaml',
                             help='Configuration file path')
    
    # Live trading command
    live_parser = subparsers.add_parser('live', help='Run live trading')
    live_parser.add_argument('--config', default='config/params.yaml',
                            help='Configuration file path')
    
    args = parser.parse_args()
    
    if args.command == 'backtest':
        run_backtest(args)
    elif args.command == 'paper':
        run_paper_trading(args)
    elif args.command == 'live':
        run_live_trading(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
