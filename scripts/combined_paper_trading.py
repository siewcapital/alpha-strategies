"""
Combined Paper Trading Launcher for Polymarket HFT + Funding Arbitrage
Deploys both strategies in paper trading mode with unified monitoring.
"""

import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime
import json
import signal
import argparse

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'polymarket_paper'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'strategies' / 'cross_exchange_funding_arb'))

from polymarket_paper.paper_trader import PolymarketPaperTradingBot
from trading_connectors.ccxt_connector import CCXTExchangeConnector, MultiExchangeConnector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CombinedPaperTrader:
    """
    Unified paper trading environment for multiple strategies.
    Manages Polymarket HFT + Cross-Exchange Funding Arbitrage.
    """
    
    def __init__(
        self,
        initial_balance: float = 10000.0,
        run_duration_hours: float = 24.0
    ):
        self.initial_balance = initial_balance
        self.run_duration_hours = run_duration_hours
        self.start_time = None
        self.running = False
        
        # Polymarket HFT Paper Trading
        self.polymarket_bot = PolymarketPaperTradingBot(
            strategy_name="Polymarket HFT",
            initial_balance=initial_balance * 0.5,  # 50% allocation
            max_positions=10,
            risk_per_trade=0.02
        )
        
        # Funding Arbitrage Paper Trading
        self.funding_connector = None
        self.funding_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
        
        # Results tracking
        self.results = {
            'start_time': None,
            'end_time': None,
            'polymarket': {},
            'funding_arb': {},
            'summary': {}
        }
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("\nShutdown signal received, stopping...")
        self.running = False
    
    async def initialize_funding_connector(self):
        """Initialize CCXT connector for funding arbitrage."""
        try:
            self.funding_connector = CCXTExchangeConnector(
                'binance',
                testnet=True
            )
            logger.info("✓ Funding arb connector initialized (Binance testnet)")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to initialize funding connector: {e}")
            return False
    
    async def run_polymarket_cycle(self):
        """Run one Polymarket HFT cycle."""
        try:
            # Simulate watching Polymarket markets
            import random
            
            # Mock markets for demonstration
            markets = [
                "0x123abc...",  # Crypto price prediction
                "0x456def...",  # Election outcome
                "0x789ghi..."   # Sports event
            ]
            
            for market_id in markets:
                if not self.running:
                    break
                
                # Simulate price movement
                current_price = 0.3 + random.random() * 0.4  # 0.3 to 0.7
                self.polymarket_bot.trader.update_market_price(market_id, current_price)
                
                # Generate signal based on simple logic
                if random.random() < 0.05:  # 5% chance of signal
                    from polymarket_paper.paper_trader import OrderSide, PositionSide
                    
                    if current_price < 0.35:
                        signal_type = 'buy_yes'
                        confidence = 0.7
                    elif current_price > 0.65:
                        signal_type = 'buy_no'
                        confidence = 0.7
                    else:
                        continue
                    
                    order = self.polymarket_bot.on_signal(
                        market_id=market_id,
                        signal_type=signal_type,
                        price=current_price,
                        confidence=confidence
                    )
                    
                    if order:
                        logger.info(f"📊 Polymarket: {signal_type} @ {current_price:.4f}")
        
        except Exception as e:
            logger.error(f"Polymarket cycle error: {e}")
    
    async def run_funding_arb_cycle(self):
        """Run one Funding Arbitrage cycle."""
        try:
            if not self.funding_connector:
                return
            
            funding_data = {}
            
            for symbol in self.funding_symbols:
                try:
                    funding = await self.funding_connector.get_funding_rate(symbol)
                    ticker = await self.funding_connector.get_ticker(symbol)
                    
                    if funding and ticker:
                        funding_data[symbol] = {
                            'rate': funding.funding_rate,
                            'price': ticker.last,
                            'next_funding': funding.next_funding_time.isoformat() if funding.next_funding_time else None
                        }
                except Exception as e:
                    logger.debug(f"Error fetching {symbol}: {e}")
            
            # Check for arbitrage opportunities
            if len(funding_data) >= 2:
                rates = {s: d['rate'] for s, d in funding_data.items()}
                max_rate = max(rates.values())
                min_rate = min(rates.values())
                diff = max_rate - min_rate
                
                if diff > 0.0001:  # 1 bps threshold
                    long_sym = min(rates, key=rates.get)
                    short_sym = max(rates, key=rates.get)
                    logger.info(
                        f"💰 Funding Arb Opportunity: {diff*10000:.2f} bps | "
                        f"Long {long_sym} ({rates[long_sym]:.4%}) / "
                        f"Short {short_sym} ({rates[short_sym]:.4%})"
                    )
        
        except Exception as e:
            logger.error(f"Funding arb cycle error: {e}")
    
    async def print_status(self):
        """Print current status."""
        try:
            # Polymarket status
            pm_status = self.polymarket_bot.get_status()
            pm_portfolio = pm_status['portfolio']['portfolio']
            
            # Time elapsed
            elapsed = datetime.now() - self.start_time
            hours_remaining = self.run_duration_hours - (elapsed.total_seconds() / 3600)
            
            logger.info(
                f"\n📈 STATUS UPDATE | {elapsed.total_seconds()/60:.1f}m elapsed | "
                f"{hours_remaining:.1f}h remaining"
            )
            logger.info(
                f"  Polymarket HFT: Balance=${pm_portfolio['balance']:,.2f} | "
                f"PnL=${pm_portfolio['total_pnl']:+,.2f} | "
                f"Trades={pm_portfolio['total_trades']}"
            )
            
            if self.funding_connector:
                logger.info("  Funding Arb: Active | Monitoring BTC, ETH, SOL")
            
        except Exception as e:
            logger.error(f"Status print error: {e}")
    
    async def run(self):
        """Main run loop."""
        logger.info("="*70)
        logger.info("COMBINED PAPER TRADING - POLYMARKET HFT + FUNDING ARBITRAGE")
        logger.info("="*70)
        logger.info(f"Start Time: {datetime.now()}")
        logger.info(f"Initial Balance: ${self.initial_balance:,.2f}")
        logger.info(f"Duration: {self.run_duration_hours} hours")
        logger.info(f"Mode: PAPER TRADING (no real capital at risk)")
        logger.info("="*70)
        
        self.start_time = datetime.now()
        self.running = True
        
        # Initialize
        await self.initialize_funding_connector()
        self.polymarket_bot.start()
        
        cycle_count = 0
        last_status_time = datetime.now()
        
        try:
            while self.running:
                # Check duration
                elapsed = datetime.now() - self.start_time
                if elapsed.total_seconds() / 3600 >= self.run_duration_hours:
                    logger.info("Run duration complete")
                    break
                
                # Run strategy cycles
                await self.run_polymarket_cycle()
                await self.run_funding_arb_cycle()
                
                # Print status every 5 minutes
                if (datetime.now() - last_status_time).total_seconds() >= 300:
                    await self.print_status()
                    last_status_time = datetime.now()
                
                cycle_count += 1
                await asyncio.sleep(30)  # 30 second cycle
        
        except Exception as e:
            logger.error(f"Main loop error: {e}")
        
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Clean shutdown."""
        logger.info("\n" + "="*70)
        logger.info("SHUTTING DOWN PAPER TRADING")
        logger.info("="*70)
        
        self.running = False
        self.polymarket_bot.stop()
        
        if self.funding_connector:
            await self.funding_connector.close()
        
        # Save results
        await self.save_results()
    
    async def save_results(self):
        """Save trading results."""
        try:
            self.results['start_time'] = self.start_time.isoformat() if self.start_time else None
            self.results['end_time'] = datetime.now().isoformat()
            
            # Polymarket results
            pm_status = self.polymarket_bot.get_status()
            self.results['polymarket'] = pm_status
            
            # Summary
            pm_portfolio = pm_status['portfolio']['portfolio']
            self.results['summary'] = {
                'initial_balance': self.initial_balance,
                'final_polymarket_balance': pm_portfolio['balance'],
                'total_pnl': pm_portfolio['total_pnl'],
                'return_pct': pm_portfolio['return_pct'],
                'total_trades': pm_portfolio['total_trades'],
                'win_rate': pm_portfolio['win_rate'] * 100
            }
            
            # Save to file
            results_dir = Path(__file__).parent / "paper_trading_results"
            results_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = results_dir / f"combined_paper_trading_{timestamp}.json"
            
            with open(results_file, 'w') as f:
                json.dump(self.results, f, indent=2, default=str)
            
            logger.info(f"\n📁 Results saved to: {results_file}")
            
            # Print summary
            logger.info("\n" + "="*70)
            logger.info("FINAL SUMMARY")
            logger.info("="*70)
            logger.info(f"Total Return: {self.results['summary']['return_pct']:+.2f}%")
            logger.info(f"Total P&L: ${self.results['summary']['total_pnl']:+,.2f}")
            logger.info(f"Total Trades: {self.results['summary']['total_trades']}")
            logger.info(f"Win Rate: {self.results['summary']['win_rate']:.1f}%")
            logger.info("="*70)
        
        except Exception as e:
            logger.error(f"Error saving results: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Combined Paper Trading for Polymarket HFT + Funding Arb'
    )
    parser.add_argument(
        '--balance',
        type=float,
        default=10000.0,
        help='Initial balance (default: 10000.0)'
    )
    parser.add_argument(
        '--duration',
        type=float,
        default=24.0,
        help='Run duration in hours (default: 24.0)'
    )
    
    args = parser.parse_args()
    
    trader = CombinedPaperTrader(
        initial_balance=args.balance,
        run_duration_hours=args.duration
    )
    
    try:
        asyncio.run(trader.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
