"""
Combined Paper Trading Runner
Runs both Polymarket HFT and Funding Arbitrage strategies in paper mode.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
import sys
import threading
import time

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'strategies' / 'cross_exchange_funding_arb'))
sys.path.insert(0, str(Path(__file__).parent / 'polymarket_paper'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('paper_trading_combined.log')
    ]
)
logger = logging.getLogger(__name__)


class CombinedPaperTrader:
    """
    Runs multiple strategies in paper trading mode.
    Coordinates Polymarket HFT and Funding Arbitrage.
    """
    
    def __init__(self, initial_capital: float = 20000.0):
        self.initial_capital = initial_capital
        self.allocations = {
            'polymarket_hft': initial_capital * 0.5,  # 50%
            'funding_arb': initial_capital * 0.5      # 50%
        }
        
        self.results = {
            'polymarket_hft': {'pnl': 0.0, 'trades': 0},
            'funding_arb': {'pnl': 0.0, 'trades': 0}
        }
        
        self.running = False
        self.start_time = None
    
    async def run_polymarket_hft(self):
        """Run Polymarket HFT paper trading."""
        logger.info("Starting Polymarket HFT paper trading...")
        
        try:
            # Import and run the existing paper runner
            from polymarket_paper.paper_runner import PolymarketHFTPaperRunner
            
            runner = PolymarketHFTPaperRunner(
                strategy_name="Polymarket HFT Paper",
                initial_balance=self.allocations['polymarket_hft'],
                max_positions=20,
                risk_per_trade=0.02,
                update_interval=30
            )
            
            runner.bot.start()
            
            cycle = 0
            while self.running:
                cycle += 1
                await runner.run_cycle()
                
                # Update results
                status = runner.bot.get_status()
                portfolio = status['portfolio']['portfolio']
                self.results['polymarket_hft'] = {
                    'pnl': portfolio['total_pnl'],
                    'trades': portfolio['total_trades'],
                    'balance': portfolio['balance'],
                    'win_rate': portfolio['win_rate']
                }
                
                # Log every 10 cycles
                if cycle % 10 == 0:
                    logger.info(
                        f"[Polymarket HFT] PnL: ${portfolio['total_pnl']:+.2f} | "
                        f"Trades: {portfolio['total_trades']} | "
                        f"Win Rate: {portfolio['win_rate']*100:.1f}%"
                    )
                
                await asyncio.sleep(30)
            
            runner.bot.stop()
            
        except Exception as e:
            logger.error(f"Polymarket HFT error: {e}")
    
    async def run_funding_arb(self):
        """Run Funding Arbitrage paper trading."""
        logger.info("Starting Funding Arbitrage paper trading...")
        
        try:
            from strategies.cross_exchange_funding_arb.paper_trading import FundingArbPaperTrader
            
            trader = FundingArbPaperTrader(
                initial_capital=self.allocations['funding_arb'],
                min_differential=0.0005,
                max_positions=5,
                position_size_pct=0.2,
                exchanges=['binance']
            )
            
            await trader.init_connectors()
            
            cycle = 0
            while self.running:
                cycle += 1
                
                # Scan for opportunities
                opportunities = await trader.scan_opportunities()
                
                if opportunities:
                    # Take best opportunity
                    best = opportunities[0]
                    if not trader.has_open_position(best['symbol']):
                        trader.open_position(best)
                        logger.info(
                            f"[Funding Arb] Opened {best['symbol']} position: "
                            f"{best['differential_bps']:.2f} bps"
                        )
                
                # Update funding
                trader.update_funding()
                
                # Update results
                summary = trader.get_portfolio_summary()
                self.results['funding_arb'] = {
                    'pnl': summary['total_pnl'],
                    'trades': summary['total_trades'],
                    'balance': summary['balance'],
                    'open_positions': summary['open_positions']
                }
                
                # Log every 5 cycles
                if cycle % 5 == 0:
                    logger.info(
                        f"[Funding Arb] PnL: ${summary['total_pnl']:+.2f} | "
                        f"Trades: {summary['total_trades']} | "
                        f"Open Positions: {summary['open_positions']}"
                    )
                
                await asyncio.sleep(60)
            
            # Close connectors
            for connector in trader.connectors.values():
                await connector.close()
                
        except Exception as e:
            logger.error(f"Funding Arb error: {e}")
    
    def print_combined_status(self):
        """Print combined status of all strategies."""
        total_pnl = sum(r['pnl'] for r in self.results.values())
        total_trades = sum(r['trades'] for r in self.results.values())
        
        print("\n" + "=" * 70)
        print("COMBINED PAPER TRADING STATUS")
        print("=" * 70)
        print(f"\nPortfolio:")
        print(f"  Initial Capital: ${self.initial_capital:,.2f}")
        print(f"  Total PnL: ${total_pnl:+.2f}")
        print(f"  Return: {(total_pnl / self.initial_capital * 100):+.2f}%")
        print(f"  Total Trades: {total_trades}")
        
        print(f"\nBy Strategy:")
        for strategy, result in self.results.items():
            print(f"  {strategy}:")
            print(f"    PnL: ${result['pnl']:+.2f}")
            print(f"    Trades: {result['trades']}")
        
        elapsed = datetime.now() - self.start_time if self.start_time else timedelta(0)
        print(f"\nUptime: {elapsed}")
        print("=" * 70)
    
    async def run(self):
        """Run all strategies concurrently."""
        logger.info("=" * 70)
        logger.info("COMBINED PAPER TRADING STARTED")
        logger.info("=" * 70)
        logger.info(f"Initial Capital: ${self.initial_capital:,.2f}")
        logger.info(f"Polymarket HFT Allocation: ${self.allocations['polymarket_hft']:,.2f}")
        logger.info(f"Funding Arb Allocation: ${self.allocations['funding_arb']:,.2f}")
        
        self.running = True
        self.start_time = datetime.now()
        
        # Create tasks for each strategy
        tasks = [
            asyncio.create_task(self.run_polymarket_hft()),
            asyncio.create_task(self.run_funding_arb())
        ]
        
        # Status reporter task
        async def status_reporter():
            while self.running:
                await asyncio.sleep(300)  # Every 5 minutes
                self.print_combined_status()
        
        tasks.append(asyncio.create_task(status_reporter()))
        
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
        finally:
            self.running = False
            
            # Cancel all tasks
            for task in tasks:
                task.cancel()
            
            # Print final status
            self.print_combined_status()
            
            # Save final results
            final_results = {
                'initial_capital': self.initial_capital,
                'allocations': self.allocations,
                'results': self.results,
                'total_pnl': sum(r['pnl'] for r in self.results.values()),
                'total_trades': sum(r['trades'] for r in self.results.values()),
                'return_pct': sum(r['pnl'] for r in self.results.values()) / self.initial_capital * 100,
                'start_time': self.start_time.isoformat() if self.start_time else None,
                'end_time': datetime.now().isoformat()
            }
            
            with open('paper_trading_final_results.json', 'w') as f:
                json.dump(final_results, f, indent=2)
            
            logger.info("Results saved to paper_trading_final_results.json")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Combined Paper Trading')
    parser.add_argument('--capital', type=float, default=20000.0, help='Initial capital')
    
    args = parser.parse_args()
    
    trader = CombinedPaperTrader(initial_capital=args.capital)
    
    try:
        asyncio.run(trader.run())
    except KeyboardInterrupt:
        print("\nShutdown complete.")


if __name__ == "__main__":
    main()
