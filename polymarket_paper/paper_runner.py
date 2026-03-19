"""
Polymarket Paper Trading Runner
Production-ready paper trading bot for Polymarket strategies.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys
import json

# Add polymarket_paper to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from polymarket_paper.paper_trader import (
    PolymarketPaperTradingBot, OrderSide, PositionSide
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PolymarketHFTPaperRunner:
    """
    Paper trading runner for Polymarket HFT strategy.
    Simulates high-frequency trading on Polymarket.
    """
    
    def __init__(
        self,
        strategy_name: str = "Polymarket HFT Paper",
        initial_balance: float = 10000.0,
        max_positions: int = 20,
        risk_per_trade: float = 0.02,
        update_interval: int = 30
    ):
        self.bot = PolymarketPaperTradingBot(
            strategy_name=strategy_name,
            initial_balance=initial_balance,
            max_positions=max_positions,
            risk_per_trade=risk_per_trade
        )
        self.update_interval = update_interval
        self.running = False
        
        # Track simulated markets
        self.watched_markets = [
            "0x123abc...",  # Example market IDs
            "0x456def...",
            "0x789ghi..."
        ]
    
    async def simulate_market_data(self):
        """
        Simulate market data for paper trading.
        In production, this would connect to Polymarket CLOB API.
        """
        # Simulated market prices (would come from API)
        simulated_prices = {
            "0x123abc...": 0.52 + (0.02 * (hash(datetime.now().isoformat()) % 10 - 5) / 10),
            "0x456def...": 0.73 + (0.02 * (hash(datetime.now().isoformat()) % 10 - 5) / 10),
            "0x789ghi...": 0.31 + (0.02 * (hash(datetime.now().isoformat()) % 10 - 5) / 10)
        }
        
        for market_id, price in simulated_prices.items():
            self.bot.trader.update_market_price(market_id, price)
    
    async def generate_signals(self):
        """
        Generate trading signals based on simulated strategy logic.
        In production, this would use real HFT signals.
        """
        # Simple mean reversion signal simulation
        for market_id in self.watched_markets:
            current_price = self.bot.trader.price_cache.get(market_id, 0.5)
            
            # Generate random signals for demonstration
            import random
            if random.random() < 0.1:  # 10% chance of signal
                if current_price < 0.45:
                    signal_type = 'buy_yes'
                    confidence = 0.7
                elif current_price > 0.65:
                    signal_type = 'buy_no'
                    confidence = 0.7
                else:
                    continue
                
                order = self.bot.on_signal(
                    market_id=market_id,
                    signal_type=signal_type,
                    price=current_price,
                    confidence=confidence
                )
                
                if order:
                    logger.info(f"Signal executed: {signal_type} @ {current_price:.4f}")
    
    async def run_cycle(self):
        """Run one trading cycle."""
        await self.simulate_market_data()
        await self.generate_signals()
        
        # Log status every 10 cycles
        if datetime.now().second % 30 < self.update_interval:
            status = self.bot.get_status()
            portfolio = status['portfolio']['portfolio']
            
            logger.info(
                f"Balance: ${portfolio['balance']:,.2f} | "
                f"PnL: ${portfolio['total_pnl']:+,.2f} | "
                f"Trades: {portfolio['total_trades']} | "
                f"Win Rate: {portfolio['win_rate']*100:.1f}%"
            )
    
    async def run(self):
        """Main run loop."""
        logger.info("="*50)
        logger.info("POLYMARKET HFT PAPER TRADING")
        logger.info(f"Initial Balance: ${self.bot.trader.portfolio.initial_balance:,.2f}")
        logger.info(f"Max Positions: {self.bot.max_positions}")
        logger.info(f"Risk/Trade: {self.bot.risk_per_trade*100:.1f}%")
        logger.info("="*50)
        
        self.bot.start()
        self.running = True
        
        cycle_count = 0
        
        try:
            while self.running:
                await self.run_cycle()
                cycle_count += 1
                await asyncio.sleep(self.update_interval)
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the runner."""
        self.running = False
        self.bot.stop()
        
        # Print final summary
        status = self.bot.get_status()
        portfolio = status['portfolio']
        
        logger.info("\n" + "="*50)
        logger.info("FINAL PAPER TRADING SUMMARY")
        logger.info("="*50)
        logger.info(f"Final Balance: ${portfolio['portfolio']['balance']:,.2f}")
        logger.info(f"Total PnL: ${portfolio['portfolio']['total_pnl']:+,.2f}")
        logger.info(f"Return: {portfolio['portfolio']['return_pct']:+.2f}%")
        logger.info(f"Total Trades: {portfolio['portfolio']['total_trades']}")
        logger.info(f"Win Rate: {portfolio['portfolio']['win_rate']*100:.1f}%")
        logger.info(f"Open Positions: {portfolio['open_positions']}")
        
        # Save results
        results_file = Path(__file__).parent / "paper_trading_results.json"
        with open(results_file, 'w') as f:
            json.dump(portfolio, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {results_file}")


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Polymarket Paper Trading')
    parser.add_argument('--balance', type=float, default=10000.0, help='Initial balance')
    parser.add_argument('--max-positions', type=int, default=20, help='Max positions')
    parser.add_argument('--risk', type=float, default=0.02, help='Risk per trade')
    parser.add_argument('--interval', type=int, default=30, help='Update interval')
    parser.add_argument('--reset', action='store_true', help='Reset account')
    
    args = parser.parse_args()
    
    # Reset if requested
    if args.reset:
        from polymarket_paper.paper_trader import PolymarketPaperTrader
        trader = PolymarketPaperTrader(initial_balance=args.balance)
        trader.reset(confirm=True)
        logger.info("Account reset")
        return
    
    runner = PolymarketHFTPaperRunner(
        initial_balance=args.balance,
        max_positions=args.max_positions,
        risk_per_trade=args.risk,
        update_interval=args.interval
    )
    
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
