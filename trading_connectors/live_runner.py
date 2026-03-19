"""
Live Funding Arbitrage Runner
Production-ready runner using CCXT for live exchange connectivity.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
import json
import sys

# Add strategy module to path
sys.path.insert(0, str(Path(__file__).parent.parent / "strategies" / "cross_exchange_funding_arb"))

from trading_connectors.ccxt_connector import (
    CCXTExchangeConnector, MultiExchangeConnector, ExchangeCredentials
)

try:
    from src.strategy import FundingArbitrageStrategy, StrategyConfig
    from src.risk_manager import RiskLimits
except ImportError:
    print("Strategy modules not found. Ensure cross_exchange_funding_arb is in the path.")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LiveFundingArbitrageRunner:
    """
    Live runner for funding rate arbitrage strategy.
    Uses CCXT for real exchange connectivity.
    """
    
    def __init__(
        self,
        testnet: bool = True,
        exchanges: list = None,
        symbols: list = None,
        update_interval: int = 60
    ):
        self.testnet = testnet
        self.exchanges = exchanges or ['binance', 'bybit']
        self.symbols = symbols or ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
        self.update_interval = update_interval
        
        self.multi_connector = MultiExchangeConnector(testnet=testnet)
        self.strategy = None
        self.running = False
    
    def initialize_exchanges(self):
        """Initialize exchange connections."""
        logger.info(f"Initializing exchanges: {self.exchanges}")
        
        for exchange_id in self.exchanges:
            try:
                # Load credentials from environment (if available)
                creds = ExchangeCredentials.from_env(exchange_id, testnet=self.testnet)
                
                # For testnet, we can use public API for data
                if self.testnet and not creds.api_key:
                    creds = None
                
                self.multi_connector.add_exchange(exchange_id, credentials=creds)
                logger.info(f"  ✓ Connected to {exchange_id}")
                
            except Exception as e:
                logger.error(f"  ✗ Failed to connect to {exchange_id}: {e}")
    
    def initialize_strategy(self):
        """Initialize the funding arbitrage strategy."""
        config = StrategyConfig(
            entry_threshold=0.0002,  # 0.02%
            exit_threshold=0.00005,  # 0.005%
            max_positions=5,
            max_position_size_usd=10000.0,
            default_leverage=2.0,
            exchanges=self.exchanges,
            symbols=self.symbols
        )
        
        risk_limits = RiskLimits(
            max_total_exposure_usd=50000.0,
            max_drawdown_pct=0.10,
            max_daily_loss_pct=0.02,
            max_position_size_usd=10000.0,
            max_leverage=3.0
        )
        
        self.strategy = FundingArbitrageStrategy(config, risk_limits)
        logger.info("Strategy initialized")
    
    async def update_funding_rates(self):
        """Fetch and update funding rates from all exchanges."""
        try:
            rates_by_exchange = await self.multi_connector.get_all_funding_rates()
            
            for exchange_id, rates in rates_by_exchange.items():
                for rate in rates:
                    # Extract symbol without /USDT:USDT suffix
                    symbol = rate.symbol.replace('/USDT:USDT', '')
                    
                    if symbol in self.symbols:
                        self.strategy.process_funding_update(
                            exchange=exchange_id,
                            symbol=symbol,
                            funding_rate=rate.funding_rate,
                            timestamp=rate.timestamp,
                            premium_index=rate.mark_price,
                            next_funding_time=rate.next_funding_time
                        )
            
            logger.debug("Funding rates updated")
            
        except Exception as e:
            logger.error(f"Error updating funding rates: {e}")
    
    async def run_cycle(self):
        """Run one strategy update cycle."""
        await self.update_funding_rates()
        
        result = self.strategy.update(datetime.now())
        
        if result.get('status') == 'success':
            if result.get('entry_signals', 0) > 0 or result.get('exit_signals', 0) > 0:
                logger.info(
                    f"Cycle: {result['entry_signals']} entries, "
                    f"{result['exit_signals']} exits, "
                    f"{result['active_positions']} positions, "
                    f"PnL: ${result['total_pnl']:.2f}"
                )
    
    async def run(self):
        """Main run loop."""
        logger.info("="*50)
        logger.info("LIVE FUNDING ARBITRAGE RUNNER")
        logger.info(f"Mode: {'TESTNET' if self.testnet else 'LIVE'}")
        logger.info(f"Exchanges: {self.exchanges}")
        logger.info(f"Symbols: {self.symbols}")
        logger.info("="*50)
        
        # Initialize
        self.initialize_exchanges()
        self.initialize_strategy()
        self.strategy.start()
        
        self.running = True
        
        try:
            while self.running:
                await self.run_cycle()
                await asyncio.sleep(self.update_interval)
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the runner and cleanup."""
        self.running = False
        
        if self.strategy:
            self.strategy.stop()
        
        await self.multi_connector.close_all()
        logger.info("Runner stopped")
    
    def get_status(self) -> dict:
        """Get current runner status."""
        if not self.strategy:
            return {'status': 'not_initialized'}
        
        return {
            'status': 'running' if self.running else 'stopped',
            'testnet': self.testnet,
            'exchanges': self.exchanges,
            'strategy': self.strategy.get_status()
        }


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Live Funding Arbitrage Runner')
    parser.add_argument('--live', action='store_true', help='Use live trading (default: testnet)')
    parser.add_argument('--exchanges', nargs='+', default=['binance'], help='Exchanges to use')
    parser.add_argument('--symbols', nargs='+', default=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'], help='Symbols to trade')
    parser.add_argument('--interval', type=int, default=60, help='Update interval in seconds')
    
    args = parser.parse_args()
    
    runner = LiveFundingArbitrageRunner(
        testnet=not args.live,
        exchanges=args.exchanges,
        symbols=args.symbols,
        update_interval=args.interval
    )
    
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
