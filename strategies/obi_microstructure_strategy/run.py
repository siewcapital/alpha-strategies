#!/usr/bin/env python3
"""
Order Book Imbalance Strategy - Main Entry Point

Usage:
    python run.py --backtest --duration 24
    python run.py --live --config config/params.yaml
    python run.py --test

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from backtest import run_backtest

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_backtest_mode(duration_hours: float, seed: int):
    """Run backtest mode."""
    logger.info(f"Starting backtest: {duration_hours} hours, seed={seed}")
    
    result = run_backtest(duration_hours=duration_hours, random_seed=seed)
    result.print_summary()
    
    # Save results
    output_dir = Path('results')
    output_dir.mkdir(exist_ok=True)
    
    # Save equity curve
    result.equity_curve.to_csv(output_dir / 'equity_curve.csv', index=False)
    logger.info(f"Equity curve saved to {output_dir / 'equity_curve.csv'}")
    
    # Save trades
    if result.trades:
        import pandas as pd
        trades_df = pd.DataFrame([
            {
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'side': t.side,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'exit_reason': t.exit_reason,
                'holding_seconds': t.holding_seconds,
                'confidence': t.confidence,
                'obi_entry': t.obi_entry
            }
            for t in result.trades
        ])
        trades_df.to_csv(output_dir / 'trades.csv', index=False)
        logger.info(f"Trades saved to {output_dir / 'trades.csv'}")


def run_test_mode():
    """Run test mode."""
    logger.info("Running unit tests...")
    
    import subprocess
    result = subprocess.run(
        ['python3', '-m', 'pytest', 'tests/', '-v'],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    return result.returncode


def run_live_mode(config_path: str):
    """Run live trading mode (placeholder)."""
    logger.info(f"Starting live trading with config: {config_path}")
    
    # This is a placeholder for live trading implementation
    # In production, this would:
    # 1. Connect to exchange WebSocket
    # 2. Initialize order manager
    # 3. Start signal processing loop
    # 4. Monitor positions and risk
    
    print("""
    ⚠️  LIVE TRADING NOT IMPLEMENTED
    
    To implement live trading:
    1. Add exchange API client (ccxt recommended)
    2. Implement order management system
    3. Add position tracking
    4. Connect to real-time L2 WebSocket feed
    5. Add monitoring and alerting
    
    Example implementation:
    
    from src import OrderBookImbalanceStrategy, RiskManager
    import ccxt
    
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    strategy = OrderBookImbalanceStrategy(config)
    risk_manager = RiskManager(risk_config)
    
    # WebSocket message handler
    def on_order_book_update(book):
        signal = strategy.generate_signal(book)
        if signal and risk_manager.can_trade():
            execute_trade(signal)
    """)


def main():
    parser = argparse.ArgumentParser(
        description='Order Book Imbalance Strategy'
    )
    
    parser.add_argument(
        '--backtest',
        action='store_true',
        help='Run backtest mode'
    )
    
    parser.add_argument(
        '--duration',
        type=float,
        default=24.0,
        help='Backtest duration in hours (default: 24)'
    )
    
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Random seed for reproducibility (default: 42)'
    )
    
    parser.add_argument(
        '--live',
        action='store_true',
        help='Run live trading mode'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default='config/params.yaml',
        help='Path to config file'
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run unit tests'
    )
    
    args = parser.parse_args()
    
    if args.test:
        sys.exit(run_test_mode())
    elif args.live:
        run_live_mode(args.config)
    elif args.backtest:
        run_backtest_mode(args.duration, args.seed)
    else:
        # Default: run backtest
        run_backtest_mode(24.0, 42)


if __name__ == '__main__':
    main()
