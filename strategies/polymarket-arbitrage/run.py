#!/usr/bin/env python3
"""
Polymarket Arbitrage Strategy - Production Runner

This is the main entry point for running the arbitrage strategy.
It coordinates data ingestion, opportunity detection, and execution.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from data_ingestion import PolymarketCLOBClient, DataAggregator
from arb_engine import ArbitrageEngine
from whale_tracker import WhaleTracker
from execution import PolymarketExecutor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PolymarketArbitrageBot:
    """
    Main bot class that orchestrates the arbitrage strategy
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.data_agg = DataAggregator()
        self.arb_engine = ArbitrageEngine(min_profit_threshold=config.get("min_profit", 0.015))
        self.whale_tracker = WhaleTracker(min_trade_size=config.get("min_whale_size", 10000))
        self.executor = PolymarketExecutor(
            api_key=config.get("api_key"),
            test_mode=config.get("test_mode", True)
        )
        
        self.is_running = False
        
    async def run(self):
        """Main execution loop"""
        logger.info("Starting Polymarket Arbitrage Bot...")
        logger.info(f"Mode: {'TEST' if self.config.get('test_mode') else 'LIVE'}")
        
        self.is_running = True
        
        # Set initial capital
        self.executor.set_cash(self.config.get("capital", 10000))
        
        while self.is_running:
            try:
                # 1. Scan for arbitrage opportunities
                logger.info("Scanning for arbitrage opportunities...")
                
                events_to_monitor = self.config.get("events", [
                    "Bitcoin above 100k 2026",
                    "Ethereum above 10k 2026",
                ])
                
                scan_results = await self.arb_engine.run_full_scan(events_to_monitor)
                
                logger.info(f"Found {scan_results['opportunities_found']} opportunities")
                
                # 2. Execute if opportunities found
                for opp in scan_results.get("top_opportunities", []):
                    if opp.is_executable(self.config.get("min_profit", 0.015)):
                        logger.info(f"Executable opportunity: {opp.event_name} ({opp.profit_percent*100:.2f}%)")
                        
                        # Calculate position sizing
                        sizing = self.arb_engine.calculate_position_sizing(opp, self.executor.cash)
                        
                        if not self.config.get("dry_run"):
                            # Execute the arbitrage
                            execution = await self.executor.execute_arbitrage({
                                "legs": opp.legs,
                                "size": sizing["total_capital"]
                            })
                            
                            logger.info(f"Execution result: {execution['success']}")
                
                # 3. Check whale signals
                whale_signals = self.whale_tracker.get_active_signals(min_confidence=0.6)
                logger.info(f"Active whale signals: {len(whale_signals)}")
                
                # 4. Portfolio status
                portfolio = self.executor.get_portfolio_summary()
                logger.info(f"Cash: ${portfolio['cash']:,.2f} | Positions: {portfolio['total_positions']}")
                
                # Sleep between scans
                await asyncio.sleep(self.config.get("scan_interval", 60))
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(10)
        
        logger.info("Bot stopped")
    
    def stop(self):
        """Stop the bot gracefully"""
        logger.info("Stopping bot...")
        self.is_running = False


def main():
    """Entry point"""
    config = {
        "test_mode": True,        # Set to False for live trading
        "dry_run": True,          # Don't actually execute trades
        "capital": 10000,         # Starting capital
        "min_profit": 0.015,      # 1.5% minimum profit
        "min_whale_size": 10000,  # $10k min whale trade
        "scan_interval": 60,      # Scan every 60 seconds
        "events": [
            "Bitcoin above 100k 2026",
            "Ethereum above 10k 2026",
            "Fed rate cut June 2026",
            "Trump approval rating",
        ]
    }
    
    bot = PolymarketArbitrageBot(config)
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        bot.stop()


if __name__ == "__main__":
    main()
