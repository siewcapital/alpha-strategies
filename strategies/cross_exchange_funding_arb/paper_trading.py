"""
Funding Rate Arbitrage - Paper Trading Deployment
Simulates live funding arbitrage across exchanges without real capital.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import sys
import time

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'trading_connectors'))

from trading_connectors.ccxt_connector import CCXTExchangeConnector, FundingRateData

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('funding_arb_paper.log')
    ]
)
logger = logging.getLogger(__name__)


class PaperPosition:
    """Paper trading position for funding arbitrage."""
    
    def __init__(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str,
        size_usd: float,
        entry_time: datetime
    ):
        self.symbol = symbol
        self.long_exchange = long_exchange
        self.short_exchange = short_exchange
        self.size_usd = size_usd
        self.entry_time = entry_time
        self.exit_time: Optional[datetime] = None
        self.funding_earned = 0.0
        self.trading_fees = 0.0
        self.status = "open"
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'long_exchange': self.long_exchange,
            'short_exchange': self.short_exchange,
            'size_usd': self.size_usd,
            'entry_time': self.entry_time.isoformat(),
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'funding_earned': self.funding_earned,
            'trading_fees': self.trading_fees,
            'status': self.status
        }


class FundingArbPaperTrader:
    """
    Paper trading implementation of funding rate arbitrage.
    Simulates trades across exchanges without real capital.
    """
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        min_differential: float = 0.0005,  # 0.05%
        max_positions: int = 5,
        position_size_pct: float = 0.2,  # 20% per position
        exchanges: List[str] = None
    ):
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.min_differential = min_differential
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct
        self.exchanges = exchanges or ['binance']
        
        # State
        self.positions: List[PaperPosition] = []
        self.closed_positions: List[PaperPosition] = []
        self.total_trades = 0
        self.total_pnl = 0.0
        self.total_funding_earned = 0.0
        self.total_fees = 0.0
        
        # Connectors (testnet mode)
        self.connectors: Dict[str, CCXTExchangeConnector] = {}
        
        # Load state
        self._load_state()
        
        logger.info(f"Funding Arb Paper Trader initialized")
        logger.info(f"Capital: ${initial_capital:,.2f}")
        logger.info(f"Min Differential: {min_differential:.4%}")
        logger.info(f"Max Positions: {max_positions}")
    
    def _load_state(self):
        """Load saved state."""
        state_file = Path('funding_arb_paper_state.json')
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                self.balance = state.get('balance', self.initial_capital)
                self.total_trades = state.get('total_trades', 0)
                self.total_pnl = state.get('total_pnl', 0.0)
                logger.info(f"Loaded state: Balance ${self.balance:,.2f}")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        """Save current state."""
        state = {
            'balance': self.balance,
            'total_trades': self.total_trades,
            'total_pnl': self.total_pnl,
            'total_funding_earned': self.total_funding_earned,
            'total_fees': self.total_fees,
            'timestamp': datetime.now().isoformat()
        }
        
        with open('funding_arb_paper_state.json', 'w') as f:
            json.dump(state, f, indent=2)
    
    async def init_connectors(self):
        """Initialize exchange connectors."""
        for exchange_id in self.exchanges:
            try:
                connector = CCXTExchangeConnector(
                    exchange_id=exchange_id,
                    testnet=True
                )
                self.connectors[exchange_id] = connector
                logger.info(f"Connected to {exchange_id} testnet")
            except Exception as e:
                logger.error(f"Failed to connect to {exchange_id}: {e}")
    
    async def scan_opportunities(self) -> List[Dict]:
        """Scan for funding rate arbitrage opportunities."""
        opportunities = []
        
        # Collect funding rates from all exchanges
        all_rates: Dict[str, Dict[str, FundingRateData]] = {}
        
        for exchange_id, connector in self.connectors.items():
            try:
                rates = await connector.get_all_funding_rates()
                for rate in rates:
                    symbol = rate.symbol.replace('/USDT:USDT', '')
                    if symbol not in all_rates:
                        all_rates[symbol] = {}
                    all_rates[symbol][exchange_id] = rate
            except Exception as e:
                logger.error(f"Error fetching rates from {exchange_id}: {e}")
        
        # Find differentials
        for symbol, exchange_rates in all_rates.items():
            if len(exchange_rates) < 2:
                continue
            
            rates_list = list(exchange_rates.items())
            for i, (ex1, rate1) in enumerate(rates_list):
                for ex2, rate2 in rates_list[i+1:]:
                    diff = abs(rate1.funding_rate - rate2.funding_rate)
                    
                    if diff >= self.min_differential:
                        # Determine long/short
                        if rate1.funding_rate < rate2.funding_rate:
                            long_ex, short_ex = ex1, ex2
                            long_rate, short_rate = rate1.funding_rate, rate2.funding_rate
                        else:
                            long_ex, short_ex = ex2, ex1
                            long_rate, short_rate = rate2.funding_rate, rate1.funding_rate
                        
                        opportunities.append({
                            'symbol': symbol,
                            'differential': diff,
                            'differential_bps': diff * 10000,
                            'long_exchange': long_ex,
                            'short_exchange': short_ex,
                            'long_rate': long_rate,
                            'short_rate': short_rate,
                            'expected_daily_return': diff / 3,  3 funding periods per day
                        })
        
        # Sort by differential
        opportunities.sort(key=lambda x: x['differential'], reverse=True)
        return opportunities
    
    def has_open_position(self, symbol: str) -> bool:
        """Check if we have an open position for symbol."""
        return any(p.symbol == symbol and p.status == "open" for p in self.positions)
    
    def open_position(self, opportunity: Dict):
        """Open a paper position."""
        if len(self.positions) >= self.max_positions:
            logger.warning("Max positions reached")
            return
        
        if self.has_open_position(opportunity['symbol']):
            logger.info(f"Already have position for {opportunity['symbol']}")
            return
        
        # Calculate position size
        position_size = self.balance * self.position_size_pct
        
        position = PaperPosition(
            symbol=opportunity['symbol'],
            long_exchange=opportunity['long_exchange'],
            short_exchange=opportunity['short_exchange'],
            size_usd=position_size,
            entry_time=datetime.now()
        )
        
        # Deduct trading fees (0.05% per side)
        trading_fee = position_size * 0.0005 * 2  # Both sides
        position.trading_fees = trading_fee
        self.total_fees += trading_fee
        self.balance -= trading_fee
        
        self.positions.append(position)
        self.total_trades += 1
        
        logger.info(f"🟢 OPENED position: {opportunity['symbol']}")
        logger.info(f"   Long: {opportunity['long_exchange']} ({opportunity['long_rate']:.6%})")
        logger.info(f"   Short: {opportunity['short_exchange']} ({opportunity['short_rate']:.6%})")
        logger.info(f"   Differential: {opportunity['differential_bps']:.2f} bps")
        logger.info(f"   Size: ${position_size:,.2f}")
        logger.info(f"   Fees: ${trading_fee:.2f}")
        
        self._save_state()
    
    def close_position(self, position: PaperPosition, reason: str = "take_profit"):
        """Close a paper position."""
        position.status = "closed"
        position.exit_time = datetime.now()
        
        # Calculate PnL (simplified - just funding earned minus fees)
        pnl = position.funding_earned - position.trading_fees
        self.total_pnl += pnl
        self.balance += position.size_usd + position.funding_earned
        
        self.positions.remove(position)
        self.closed_positions.append(position)
        
        logger.info(f"🔴 CLOSED position: {position.symbol}")
        logger.info(f"   Reason: {reason}")
        logger.info(f"   Funding Earned: ${position.funding_earned:.2f}")
        logger.info(f"   PnL: ${pnl:.2f}")
        
        self._save_state()
    
    def update_funding(self):
        """Update funding earned for all positions."""
        for position in self.positions:
            if position.status != "open":
                continue
            
            # Estimate funding earned (simplified)
            # In reality, this would track actual funding payments
            hourly_rate = 0.0001  # Placeholder
            position.funding_earned += position.size_usd * hourly_rate
            self.total_funding_earned += position.size_usd * hourly_rate
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary."""
        return {
            'initial_capital': self.initial_capital,
            'balance': self.balance,
            'total_pnl': self.total_pnl,
            'total_trades': self.total_trades,
            'open_positions': len(self.positions),
            'total_funding_earned': self.total_funding_earned,
            'total_fees': self.total_fees,
            'return_pct': (self.balance - self.initial_capital) / self.initial_capital * 100
        }
    
    def print_status(self):
        """Print current status."""
        summary = self.get_portfolio_summary()
        
        print("\n" + "=" * 70)
        print("FUNDING ARBITRAGE - PAPER TRADING STATUS")
        print("=" * 70)
        print(f"\nPortfolio:")
        print(f"  Initial Capital: ${summary['initial_capital']:,.2f}")
        print(f"  Current Balance: ${summary['balance']:,.2f}")
        print(f"  Total PnL: ${summary['total_pnl']:+.2f}")
        print(f"  Return: {summary['return_pct']:+.2f}%")
        print(f"\nActivity:")
        print(f"  Total Trades: {summary['total_trades']}")
        print(f"  Open Positions: {summary['open_positions']}")
        print(f"  Funding Earned: ${summary['total_funding_earned']:.2f}")
        print(f"  Trading Fees: ${summary['total_fees']:.2f}")
        
        if self.positions:
            print(f"\nOpen Positions:")
            for p in self.positions:
                print(f"  {p.symbol}: Long {p.long_exchange} / Short {p.short_exchange} (${p.size_usd:,.2f})")
        
        print("=" * 70)
    
    async def run(self, scan_interval: int = 60):
        """Main trading loop."""
        logger.info("=" * 70)
        logger.info("FUNDING ARBITRAGE PAPER TRADING STARTED")
        logger.info("=" * 70)
        
        # Initialize connectors
        await self.init_connectors()
        
        if not self.connectors:
            logger.error("No exchange connectors available. Exiting.")
            return
        
        cycle_count = 0
        
        try:
            while True:
                cycle_count += 1
                
                # Scan for opportunities
                logger.info(f"\n--- Scan Cycle #{cycle_count} ---")
                opportunities = await self.scan_opportunities()
                
                if opportunities:
                    logger.info(f"Found {len(opportunities)} opportunities")
                    
                    # Show top 3
                    for i, opp in enumerate(opportunities[:3], 1):
                        logger.info(
                            f"  {i}. {opp['symbol']}: "
                            f"{opp['differential_bps']:.2f} bps "
                            f"({opp['long_exchange']} <-> {opp['short_exchange']})"
                        )
                    
                    # Open position on best opportunity
                    if not self.has_open_position(opportunities[0]['symbol']):
                        self.open_position(opportunities[0])
                else:
                    logger.info("No opportunities found")
                
                # Update funding
                self.update_funding()
                
                # Print status every 5 cycles
                if cycle_count % 5 == 0:
                    self.print_status()
                
                # Wait before next scan
                await asyncio.sleep(scan_interval)
                
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
        finally:
            # Close connectors
            for connector in self.connectors.values():
                await connector.close()
            
            # Print final status
            self.print_status()
            
            # Save results
            results = {
                'summary': self.get_portfolio_summary(),
                'open_positions': [p.to_dict() for p in self.positions],
                'closed_positions': [p.to_dict() for p in self.closed_positions],
                'timestamp': datetime.now().isoformat()
            }
            
            with open('funding_arb_paper_results.json', 'w') as f:
                json.dump(results, f, indent=2)
            
            logger.info("Results saved to funding_arb_paper_results.json")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Funding Arbitrage Paper Trading')
    parser.add_argument('--capital', type=float, default=10000.0, help='Initial capital')
    parser.add_argument('--min-diff', type=float, default=0.0005, help='Min differential (0.0005 = 0.05%)')
    parser.add_argument('--max-positions', type=int, default=5, help='Max positions')
    parser.add_argument('--interval', type=int, default=60, help='Scan interval in seconds')
    
    args = parser.parse_args()
    
    trader = FundingArbPaperTrader(
        initial_capital=args.capital,
        min_differential=args.min_diff,
        max_positions=args.max_positions
    )
    
    asyncio.run(trader.run(scan_interval=args.interval))


if __name__ == "__main__":
    main()
