import os
import sys
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# Set up paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class ExecutionConfig:
    """Configuration for trade execution."""
    
    # Position sizing
    max_position_size: float = 10000.0  # Max $ per position
    max_total_exposure: float = 50000.0  # Max total exposure
    
    # Risk limits
    max_leverage: float = 3.0
    min_annualized_yield: float = 5.0  # Minimum yield to enter
    stop_loss_basis: float = 3.0  # Close if basis drops below entry - 3%
    take_profit_basis: float = 15.0  # Close if basis reaches 15%
    
    # Execution
    use_limit_orders: bool = True
    limit_order_offset: float = 0.001  # 0.1% offset for limit orders
    max_slippage: float = 0.002  # 0.2% max slippage
    
    # Rebalancing
    rebalance_threshold: float = 0.02  # Rebalance if delta exceeds 2%
    auto_rollover: bool = True  # Auto roll positions before expiry
    
    # Circuit breakers
    max_daily_loss: float = 1000.0
    max_drawdown_pct: float = 5.0


class RiskManager:
    """
    Manages risk for basis trade positions.
    
    Responsibilities:
    - Position sizing based on available capital
    - Pre-trade validation
    - Circuit breaker checks
    - Drawdown monitoring
    """
    
    def __init__(self, config: ExecutionConfig = None, initial_capital: float = 10000.0):
        """
        Initialize risk manager.
        
        Args:
            config: Execution configuration
            initial_capital: Starting capital
        """
        self.config = config or ExecutionConfig()
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        self.daily_pnl = 0.0
        self.last_reset = datetime.now().date()
        
        # Trade history for analysis
        self.trades_today = 0
        self.daily_loss = 0.0
    
    def reset_daily_stats(self):
        """Reset daily statistics."""
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_pnl = 0.0
            self.daily_loss = 0.0
            self.trades_today = 0
            self.last_reset = today
    
    def calculate_position_size(self, 
                               opportunity: Dict,
                               available_capital: float) -> Tuple[float, float]:
        """
        Calculate optimal position size for a basis trade.
        
        Args:
            opportunity: Basis opportunity dict
            available_capital: Available capital for trading
            
        Returns:
            Tuple of (spot_size, margin_required)
        """
        # Base position size on available capital
        max_size = min(
            available_capital * 0.5,  # Use max 50% of available capital
            self.config.max_position_size
        )
        
        # Adjust for yield - higher yield = slightly larger size
        annualized_yield = abs(opportunity.get('annualized_yield', 0))
        yield_multiplier = min(1.0 + (annualized_yield / 100), 1.5)  # Max 1.5x
        
        position_value = max_size * yield_multiplier
        
        # For basis trade:
        # - Spot leg: 100% of position value
        # - Perp leg: Requires margin (1/leverage)
        leverage = min(self.config.max_leverage, 2.0)  # Conservative default
        margin_required = position_value / leverage
        
        spot_size = position_value / opportunity.get('spot_price', 1)
        
        return spot_size, margin_required
    
    def validate_trade(self, 
                      opportunity: Dict,
                      current_positions: List[Dict],
                      available_capital: float) -> Tuple[bool, str]:
        """
        Validate if a trade should be executed.
        
        Returns:
            Tuple of (should_trade, reason)
        """
        self.reset_daily_stats()
        
        # Check minimum yield
        annualized_yield = opportunity.get('annualized_yield', 0)
        if annualized_yield < self.config.min_annualized_yield:
            return False, f"Yield {annualized_yield:.2f}% below minimum {self.config.min_annualized_yield}%"
        
        # Check available capital
        if available_capital < 1000:  # Minimum $1000
            return False, f"Insufficient capital: ${available_capital:,.2f}"
        
        # Check daily loss limit
        if self.daily_loss >= self.config.max_daily_loss:
            return False, f"Daily loss limit reached: ${self.daily_loss:,.2f}"
        
        # Check drawdown
        drawdown = self.calculate_drawdown()
        if drawdown >= self.config.max_drawdown_pct:
            return False, f"Max drawdown reached: {drawdown:.2f}%"
        
        # Check total exposure
        total_exposure = sum(p.get('margin_required', 0) for p in current_positions)
        spot_size, margin = self.calculate_position_size(opportunity, available_capital)
        
        if total_exposure + margin > self.config.max_total_exposure:
            return False, f"Max exposure would be exceeded"
        
        # Check if already have position for this symbol
        symbol = opportunity.get('symbol')
        existing = [p for p in current_positions if p.get('symbol') == symbol]
        if existing:
            return False, f"Already have position for {symbol}"
        
        return True, "Trade validated"
    
    def calculate_drawdown(self) -> float:
        """Calculate current drawdown percentage."""
        if self.peak_capital <= 0:
            return 0.0
        return ((self.peak_capital - self.current_capital) / self.peak_capital) * 100
    
    def update_capital(self, pnl: float):
        """Update capital with P&L."""
        self.current_capital += pnl
        self.daily_pnl += pnl
        
        if pnl < 0:
            self.daily_loss += abs(pnl)
        
        # Update peak
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        
        self.reset_daily_stats()
    
    def check_circuit_breakers(self) -> Tuple[bool, str]:
        """
        Check if circuit breakers should be triggered.
        
        Returns:
            Tuple of (halt_trading, reason)
        """
        self.reset_daily_stats()
        
        # Daily loss limit
        if self.daily_loss >= self.config.max_daily_loss:
            return True, f"Daily loss limit: ${self.daily_loss:,.2f}"
        
        # Drawdown limit
        drawdown = self.calculate_drawdown()
        if drawdown >= self.config.max_drawdown_pct:
            return True, f"Drawdown limit: {drawdown:.2f}%"
        
        return False, ""
    
    def get_risk_metrics(self) -> Dict:
        """Get current risk metrics."""
        return {
            'initial_capital': self.initial_capital,
            'current_capital': self.current_capital,
            'peak_capital': self.peak_capital,
            'drawdown_pct': self.calculate_drawdown(),
            'daily_pnl': self.daily_pnl,
            'daily_loss': self.daily_loss,
            'trades_today': self.trades_today,
            'available_capital': self.current_capital - (self.current_capital * 0.1)  # Keep 10% reserve
        }


class ExecutionEngine:
    """
    Handles execution of basis trades.
    
    Responsibilities:
    - Order placement and management
    - Simultaneous leg execution
    - Slippage monitoring
    - Error handling and retries
    """
    
    def __init__(self, exchange_connector, risk_manager: RiskManager = None):
        """
        Initialize execution engine.
        
        Args:
            exchange_connector: CCXT connector instance
            risk_manager: Risk manager instance
        """
        self.exchange = exchange_connector
        self.risk_manager = risk_manager or RiskManager()
        self.pending_orders = {}
    
    async def execute_basis_trade(self,
                                  symbol: str,
                                  spot_size: float,
                                  perp_size: float,
                                  opportunity: Dict) -> Dict:
        """
        Execute a basis trade (long spot + short perp).
        
        Args:
            symbol: Trading symbol (e.g., 'BTC')
            spot_size: Amount to buy in spot market
            perp_size: Amount to short in perp market (negative)
            opportunity: Basis opportunity details
            
        Returns:
            Execution result dict
        """
        result = {
            'success': False,
            'position_id': None,
            'spot_order': None,
            'perp_order': None,
            'error': None,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Execute spot leg (buy)
            spot_symbol = f"{symbol}/USDT"
            spot_order = await self._place_order(
                symbol=spot_symbol,
                side=OrderSide.BUY,
                amount=spot_size,
                order_type=OrderType.MARKET
            )
            result['spot_order'] = spot_order
            
            # Execute perp leg (short)
            perp_symbol = f"{symbol}/USDT:USDT"
            perp_order = await self._place_order(
                symbol=perp_symbol,
                side=OrderSide.SELL,
                amount=abs(perp_size),
                order_type=OrderType.MARKET
            )
            result['perp_order'] = perp_order
            
            # Verify both legs executed
            if spot_order and perp_order:
                result['success'] = True
                result['position_id'] = f"{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                
                # Calculate slippage
                spot_slippage = self._calculate_slippage(
                    opportunity.get('spot_price', 0),
                    spot_order.get('average_price', spot_order.get('price', 0))
                )
                result['spot_slippage'] = spot_slippage
                
                perp_slippage = self._calculate_slippage(
                    opportunity.get('futures_price', 0),
                    perp_order.get('average_price', perp_order.get('price', 0))
                )
                result['perp_slippage'] = perp_slippage
            else:
                # One leg failed - need to revert
                result['error'] = "One leg failed to execute"
                await self._revert_trade(spot_order, perp_order)
                
        except Exception as e:
            result['error'] = str(e)
            # Attempt to revert any executed legs
            await self._revert_trade(result.get('spot_order'), result.get('perp_order'))
        
        return result
    
    async def _place_order(self,
                          symbol: str,
                          side: OrderSide,
                          amount: float,
                          order_type: OrderType = OrderType.MARKET,
                          price: float = None) -> Optional[Dict]:
        """
        Place a single order.
        
        Args:
            symbol: Trading pair
            side: Buy or sell
            amount: Order size
            order_type: Market or limit
            price: Limit price (required for limit orders)
            
        Returns:
            Order dict or None if failed
        """
        try:
            order_side = side.value
            order_type_str = order_type.value
            
            if order_type == OrderType.LIMIT and price:
                order = self.exchange.create_limit_buy_order(symbol, amount, price) if side == OrderSide.BUY \
                       else self.exchange.create_limit_sell_order(symbol, amount, price)
            else:
                order = self.exchange.create_market_buy_order(symbol, amount) if side == OrderSide.BUY \
                       else self.exchange.create_market_sell_order(symbol, amount)
            
            return order
            
        except Exception as e:
            print(f"Error placing order: {e}")
            return None
    
    async def _revert_trade(self, spot_order: Dict = None, perp_order: Dict = None):
        """
        Revert a partially executed trade.
        
        This is called when one leg fails to execute.
        """
        try:
            if spot_order and spot_order.get('filled'):
                # Sell the spot position
                symbol = spot_order.get('symbol')
                amount = spot_order.get('filled')
                self.exchange.create_market_sell_order(symbol, amount)
                print(f"Reverted spot leg: sold {amount} {symbol}")
                
            if perp_order and perp_order.get('filled'):
                # Close the perp position
                symbol = perp_order.get('symbol')
                amount = perp_order.get('filled')
                self.exchange.create_market_buy_order(symbol, amount)  # Buy to close short
                print(f"Reverted perp leg: bought {amount} {symbol}")
                
        except Exception as e:
            print(f"Error reverting trade: {e}")
    
    def _calculate_slippage(self, expected_price: float, executed_price: float) -> float:
        """Calculate slippage percentage."""
        if expected_price <= 0:
            return 0.0
        return abs(executed_price - expected_price) / expected_price
    
    async def close_position(self,
                            position: Dict,
                            current_spot_price: float,
                            current_perp_price: float) -> Dict:
        """
        Close an existing basis trade position.
        
        Args:
            position: Position dict
            current_spot_price: Current spot price
            current_perp_price: Current perp price
            
        Returns:
            Close result dict
        """
        result = {
            'success': False,
            'spot_close': None,
            'perp_close': None,
            'error': None
        }
        
        try:
            symbol = position.get('symbol')
            spot_size = position.get('spot_size', 0)
            perp_size = position.get('perp_size', 0)
            
            # Close spot leg (sell)
            spot_symbol = f"{symbol}/USDT"
            spot_close = await self._place_order(
                symbol=spot_symbol,
                side=OrderSide.SELL,
                amount=spot_size,
                order_type=OrderType.MARKET
            )
            result['spot_close'] = spot_close
            
            # Close perp leg (buy to cover)
            perp_symbol = f"{symbol}/USDT:USDT"
            perp_close = await self._place_order(
                symbol=perp_symbol,
                side=OrderSide.BUY,
                amount=abs(perp_size),
                order_type=OrderType.MARKET
            )
            result['perp_close'] = perp_close
            
            if spot_close and perp_close:
                result['success'] = True
            else:
                result['error'] = "Failed to close one or more legs"
                
        except Exception as e:
            result['error'] = str(e)
        
        return result


def main():
    """Test the risk manager and execution engine."""
    
    # Test risk manager
    print("Testing Risk Manager...")
    rm = RiskManager(initial_capital=10000.0)
    
    # Test opportunity
    opportunity = {
        'symbol': 'BTC',
        'spot_price': 70000,
        'futures_price': 70700,
        'annualized_yield': 10.5
    }
    
    spot_size, margin = rm.calculate_position_size(opportunity, 10000.0)
    print(f"\nPosition sizing:")
    print(f"  Spot size: {spot_size:.4f} BTC")
    print(f"  Margin required: ${margin:,.2f}")
    
    # Validate trade
    should_trade, reason = rm.validate_trade(opportunity, [], 10000.0)
    print(f"\nTrade validation: {should_trade} - {reason}")
    
    # Risk metrics
    metrics = rm.get_risk_metrics()
    print(f"\nRisk metrics:")
    print(f"  Available capital: ${metrics['available_capital']:,.2f}")
    print(f"  Drawdown: {metrics['drawdown_pct']:.2f}%")


if __name__ == "__main__":
    main()
