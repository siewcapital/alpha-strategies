import os
import sys
import asyncio
import argparse
from typing import Dict, List, Optional
from datetime import datetime
import json

# Set up paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)

from basis_monitor import BasisMonitor, BasisOpportunity
from position_manager import PositionManager, BasisPosition, PositionStatus
from execution import ExecutionEngine, RiskManager, ExecutionConfig


class BasisTradeBot:
    """
    Main bot for executing basis trade strategy.
    
    Combines:
    - Basis monitoring
    - Position management
    - Risk management
    - Trade execution
    """
    
    def __init__(self,
                 capital: float = 10000.0,
                 exchanges: List[str] = None,
                 min_yield: float = 5.0,
                 paper_trading: bool = True,
                 state_file: str = None):
        """
        Initialize the basis trade bot.
        
        Args:
            capital: Trading capital
            exchanges: List of exchanges to monitor
            min_yield: Minimum annualized yield to enter position
            paper_trading: Run in paper trading mode
            state_file: Path to state file
        """
        self.capital = capital
        self.paper_trading = paper_trading
        self.min_yield = min_yield
        self.exchanges = exchanges or ['binance', 'bybit', 'okx']
        
        print(f"Initializing Basis Trade Bot...")
        print(f"  Capital: ${capital:,.2f}")
        print(f"  Mode: {'Paper Trading' if paper_trading else 'LIVE'}")
        print(f"  Exchanges: {', '.join(self.exchanges)}")
        print(f"  Min Yield: {min_yield}%")
        
        # Initialize components
        self.monitor = BasisMonitor(
            exchanges=self.exchanges,
            min_annualized_yield=min_yield
        )
        
        self.position_manager = PositionManager(
            state_file=state_file or self._default_state_file()
        )
        
        config = ExecutionConfig(
            min_annualized_yield=min_yield,
            max_position_size=capital * 0.3,  # Max 30% per position
            max_total_exposure=capital * 0.9  # Max 90% total
        )
        
        self.risk_manager = RiskManager(
            config=config,
            initial_capital=capital
        )
        
        self.running = False
        self.cycle_count = 0
        
        # Statistics
        self.stats = {
            'opportunities_seen': 0,
            'positions_opened': 0,
            'positions_closed': 0,
            'total_pnl': 0.0
        }
    
    def _default_state_file(self) -> str:
        """Get default state file path."""
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, 'bot_state.json')
    
    async def run(self, interval: int = 60, max_cycles: int = None):
        """
        Run the bot main loop.
        
        Args:
            interval: Seconds between cycles
            max_cycles: Maximum number of cycles (None = infinite)
        """
        self.running = True
        
        print(f"\n{'='*60}")
        print("BASIS TRADE BOT STARTED")
        print(f"{'='*60}\n")
        
        try:
            while self.running:
                self.cycle_count += 1
                
                print(f"\n--- Cycle {self.cycle_count} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
                
                # Check circuit breakers
                halt, reason = self.risk_manager.check_circuit_breakers()
                if halt:
                    print(f"🛑 CIRCUIT BREAKER: {reason}")
                    print("Halting trading...")
                    break
                
                # Run trading cycle
                await self._trading_cycle()
                
                # Check if max cycles reached
                if max_cycles and self.cycle_count >= max_cycles:
                    print(f"\nReached max cycles ({max_cycles}). Stopping.")
                    break
                
                # Wait for next cycle
                print(f"Waiting {interval}s until next cycle...")
                await asyncio.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nStopping bot...")
        finally:
            self.stop()
    
    async def _trading_cycle(self):
        """Execute one trading cycle."""
        
        # 1. Check existing positions for exit signals
        await self._check_position_exits()
        
        # 2. Fetch new opportunities
        opportunities = self.monitor.fetch_basis_opportunities()
        funding_rates = self.monitor.get_funding_rates()
        
        print(f"Found {len(opportunities)} basis opportunities")
        print(f"Found {len(funding_rates)} funding rate entries")
        
        self.stats['opportunities_seen'] += len(opportunities)
        
        # 3. Look for new entry signals
        await self._check_entries(opportunities, funding_rates)
        
        # 4. Print status
        self._print_status()
    
    async def _check_position_exits(self):
        """Check if any positions should be closed."""
        open_positions = self.position_manager.get_open_positions()
        
        if not open_positions:
            return
        
        print(f"\nChecking {len(open_positions)} open positions for exit signals...")
        
        for position in open_positions:
            # Get current prices
            current_prices = self._get_current_prices(position.symbol, position.exchange)
            
            if not current_prices:
                continue
            
            current_basis = ((current_prices['perp'] - current_prices['spot']) >/ current_prices['spot']) * 100
            
            # Check stop loss
            if position.stop_loss_basis and current_basis < position.stop_loss_basis:
                print(f"  🔴 STOP LOSS triggered for {position.position_id}")
                print(f"     Current basis: {current_basis:.2f}% | Stop: {position.stop_loss_basis:.2f}%")
                await self._close_position(position, current_prices)
                continue
            
            # Check take profit
            if position.take_profit_basis and current_basis >= position.take_profit_basis:
                print(f"  🟢 TAKE PROFIT triggered for {position.position_id}")
                print(f"     Current basis: {current_basis:.2f}% | Target: {position.take_profit_basis:.2f}%")
                await self._close_position(position, current_prices)
                continue
            
            # Check if basis has compressed significantly
            basis_compression = position.entry_basis - current_basis
            if basis_compression >= 5.0:  # Close if captured 5% or more
                print(f"  📊 BASIS COMPRESSION for {position.position_id}")
                print(f"     Entry: {position.entry_basis:.2f}% | Current: {current_basis:.2f}%")
                print(f"     Captured: {basis_compression:.2f}%")
                await self._close_position(position, current_prices)
    
    async def _check_entries(self, opportunities: List[BasisOpportunity], funding_rates: List[Dict]):
        """Check for new entry opportunities."""
        
        if not opportunities:
            return
        
        print(f"\nChecking {len(opportunities)} opportunities for entry...")
        
        # Get current positions
        open_positions = self.position_manager.get_open_positions()
        
        # Get available capital
        risk_metrics = self.risk_manager.get_risk_metrics()
        available_capital = risk_metrics['available_capital']
        
        for opp in opportunities:
            # Skip if already have position for this symbol
            existing = [p for p in open_positions if p.symbol == opp.symbol]
            if existing:
                continue
            
            # Validate opportunity
            opp_dict = {
                'symbol': opp.symbol,
                'spot_price': opp.spot_price,
                'futures_price': opp.futures_price,
                'annualized_yield': opp.annualized_yield
            }
            
            should_trade, reason = self.risk_manager.validate_trade(
                opp_dict, 
                [p.to_dict() for p in open_positions],
                available_capital
            )
            
            if should_trade:
                print(f"\n  🎯 ENTRY SIGNAL: {opp.symbol} on {opp.exchange.upper()}")
                print(f"     Basis: {opp.annualized_yield:+.2f}%")
                print(f"     Spot: ${opp.spot_price:,.2f} | Perp: ${opp.futures_price:,.2f}")
                
                if self.paper_trading:
                    await self._open_position_paper(opp, available_capital)
                else:
                    # Live execution would go here
                    print("     (Live execution disabled)")
                
                # Update available capital
                risk_metrics = self.risk_manager.get_risk_metrics()
                available_capital = risk_metrics['available_capital']
            else:
                print(f"  ⏸️  Skipped {opp.symbol}: {reason}")
    
    async def _open_position_paper(self, opportunity: BasisOpportunity, available_capital: float):
        """Open a paper trading position."""
        
        # Calculate position size
        spot_size, margin = self.risk_manager.calculate_position_size(
            {'spot_price': opportunity.spot_price, 'annualized_yield': opportunity.annualized_yield},
            available_capital
        )
        
        # Create position
        stop_loss = opportunity.annualized_yield - 3.0  # 3% stop
        take_profit = min(opportunity.annualized_yield + 5.0, 15.0)  # 5% target, max 15%
        
        position = self.position_manager.create_position(
            symbol=opportunity.symbol,
            exchange=opportunity.exchange,
            spot_size=spot_size,
            entry_spot_price=opportunity.spot_price,
            entry_perp_price=opportunity.futures_price,
            entry_basis=opportunity.annualized_yield,
            margin_required=margin,
            stop_loss_basis=stop_loss,
            take_profit_basis=take_profit
        )
        
        print(f"     ✓ Position opened: {position.position_id}")
        print(f"     Size: {spot_size:.4f} {opportunity.symbol}")
        print(f"     Margin: ${margin:,.2f}")
        print(f"     Stop: {stop_loss:.2f}% | Target: {take_profit:.2f}%")
        
        self.stats['positions_opened'] += 1
    
    async def _close_position(self, position: BasisPosition, current_prices: Dict):
        """Close a position."""
        
        if self.paper_trading:
            closed = self.position_manager.close_position(
                position.position_id,
                current_prices['spot'],
                current_prices['perp']
            )
            
            pnl = closed.realized_pnl
            self.risk_manager.update_capital(pnl)
            
            print(f"     ✓ Position closed")
            print(f"     P&L: ${pnl:,.2f}")
            
            self.stats['positions_closed'] += 1
            self.stats['total_pnl'] += pnl
    
    def _get_current_prices(self, symbol: str, exchange: str) -> Optional[Dict]:
        """Get current spot and perp prices."""
        try:
            exchange_obj = self.monitor._get_exchange(exchange)
            if not exchange_obj:
                return None
            
            spot_symbol = f"{symbol}/USDT"
            perp_symbol = f"{symbol}/USDT:USDT"
            
            spot_ticker = exchange_obj.fetch_ticker(spot_symbol)
            perp_ticker = exchange_obj.fetch_ticker(perp_symbol)
            
            return {
                'spot': spot_ticker.get('last', 0),
                'perp': perp_ticker.get('last', 0)
            }
        except Exception as e:
            print(f"Error fetching prices: {e}")
            return None
    
    def _print_status(self):
        """Print current bot status."""
        
        print(f"\n{'-'*60}")
        print("BOT STATUS")
        print(f"{'-'*60}")
        
        # Risk metrics
        risk = self.risk_manager.get_risk_metrics()
        print(f"Capital:")
        print(f"  Current: ${risk['current_capital']:,.2f}")
        print(f"  Available: ${risk['available_capital']:,.2f}")
        print(f"  Drawdown: {risk['drawdown_pct']:.2f}%")
        print(f"  Daily P&L: ${risk['daily_pnl']:,.2f}")
        
        # Positions
        open_positions = self.position_manager.get_open_positions()
        print(f"\nPositions:")
        print(f"  Open: {len(open_positions)}")
        print(f"  Closed (session): {self.stats['positions_closed']}")
        
        if open_positions:
            print(f"\n  Open Positions:")
            for pos in open_positions:
                print(f"    {pos.symbol} on {pos.exchange.upper()}")
                print(f"      Entry basis: {pos.entry_basis:.2f}%")
                print(f"      Margin: ${pos.margin_required:,.2f}")
        
        print(f"\nSession Stats:")
        print(f"  Cycles: {self.cycle_count}")
        print(f"  Opportunities seen: {self.stats['opportunities_seen']}")
        print(f"  Total P&L: ${self.stats['total_pnl']:,.2f}")
        print(f"{'-'*60}")
    
    def stop(self):
        """Stop the bot."""
        self.running = False
        print(f"\n{'='*60}")
        print("BOT STOPPED")
        print(f"{'='*60}")
        print(f"Total cycles: {self.cycle_count}")
        print(f"Positions opened: {self.stats['positions_opened']}")
        print(f"Positions closed: {self.stats['positions_closed']}")
        print(f"Total P&L: ${self.stats['total_pnl']:,.2f}")
        print(f"{'='*60}\n")


async def main():
    """Main entry point."""
    
    parser = argparse.ArgumentParser(description='Basis Trade Bot')
    parser.add_argument('--capital', type=float, default=10000.0,
                       help='Trading capital (default: 10000)')
    parser.add_argument('--min-yield', type=float, default=5.0,
                       help='Minimum annualized yield %% (default: 5)')
    parser.add_argument('--interval', type=int, default=60,
                       help='Check interval in seconds (default: 60)')
    parser.add_argument('--cycles', type=int, default=None,
                       help='Max cycles to run (default: infinite)')
    parser.add_argument('--live', action='store_true',
                       help='Enable live trading (default: paper)')
    parser.add_argument('--exchanges', nargs='+', default=['binance', 'bybit'],
                       help='Exchanges to monitor (default: binance bybit)')
    
    args = parser.parse_args()
    
    # Create bot
    bot = BasisTradeBot(
        capital=args.capital,
        exchanges=args.exchanges,
        min_yield=args.min_yield,
        paper_trading=not args.live
    )
    
    # Run bot
    try:
        await bot.run(
            interval=args.interval,
            max_cycles=args.cycles
        )
    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
