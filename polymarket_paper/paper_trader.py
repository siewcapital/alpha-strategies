"""
Polymarket Paper Trading Environment
Simulates live trading on Polymarket without real capital at risk.
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from enum import Enum

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(Enum):
    YES = "yes"
    NO = "no"


@dataclass
class Order:
    """Paper trading order."""
    id: str
    market_id: str
    side: OrderSide
    position_side: PositionSide
    size: float  # Number of shares/contracts
    price: float  # Price per share (0.01 to 0.99)
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    filled_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    
    @property
    def remaining_size(self) -> float:
        return self.size - self.filled_size
    
    @property
    def total_cost(self) -> float:
        return self.filled_size * self.filled_price


@dataclass
class Position:
    """Paper trading position."""
    market_id: str
    side: PositionSide
    size: float  # Number of shares
    avg_entry_price: float
    realized_pnl: float = 0.0
    opened_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    
    @property
    def unrealized_pnl(self, current_price: float = 0.5) -> float:
        """Calculate unrealized P&L at current price."""
        if self.side == PositionSide.YES:
            return self.size * (current_price - self.avg_entry_price)
        else:  # NO
            return self.size * ((1 - current_price) - self.avg_entry_price)
    
    def to_dict(self) -> Dict:
        return {
            'market_id': self.market_id,
            'side': self.side.value,
            'size': self.size,
            'avg_entry_price': self.avg_entry_price,
            'realized_pnl': self.realized_pnl,
            'opened_at': self.opened_at.isoformat(),
            'last_updated': self.last_updated.isoformat()
        }


@dataclass
class Trade:
    """Executed trade record."""
    id: str
    order_id: str
    market_id: str
    side: OrderSide
    position_side: PositionSide
    size: float
    price: float
    timestamp: datetime
    pnl: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'order_id': self.order_id,
            'market_id': self.market_id,
            'side': self.side.value,
            'position_side': self.position_side.value,
            'size': self.size,
            'price': self.price,
            'timestamp': self.timestamp.isoformat(),
            'pnl': self.pnl
        }


@dataclass
class Portfolio:
    """Paper trading portfolio state."""
    initial_balance: float = 10000.0  # Default $10k paper balance
    balance: float = 10000.0
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown: float = 0.0
    peak_balance: float = 10000.0
    created_at: datetime = field(default_factory=datetime.now)
    
    def update_peak(self):
        """Update peak balance and drawdown."""
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        
        drawdown = (self.peak_balance - self.balance) / self.peak_balance
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
    
    def record_trade(self, pnl: float):
        """Record a completed trade."""
        self.total_trades += 1
        self.total_pnl += pnl
        self.balance += pnl
        
        if pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        self.update_peak()
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    @property
    def profit_factor(self) -> float:
        """Gross profits / gross losses."""
        # Simplified - track separately for accuracy
        return 1.0
    
    def to_dict(self) -> Dict:
        return {
            'initial_balance': self.initial_balance,
            'balance': self.balance,
            'total_pnl': self.total_pnl,
            'total_trades': self.total_trades,
            'win_rate': self.win_rate,
            'max_drawdown': self.max_drawdown,
            'return_pct': (self.balance - self.initial_balance) / self.initial_balance * 100
        }


class PolymarketPaperTrader:
    """
    Paper trading environment for Polymarket strategies.
    Simulates order execution, position tracking, and P&L calculation.
    """
    
    def __init__(
        self,
        initial_balance: float = 10000.0,
        trading_fee: float = 0.002,  # 0.2% per trade
        data_dir: Optional[Path] = None
    ):
        self.initial_balance = initial_balance
        self.trading_fee = trading_fee
        self.data_dir = data_dir or Path(__file__).parent / "paper_trading_data"
        self.data_dir.mkdir(exist_ok=True)
        
        # State
        self.portfolio = Portfolio(initial_balance=initial_balance, balance=initial_balance)
        self.positions: Dict[str, Position] = {}  # market_id -> Position
        self.orders: Dict[str, Order] = {}  # order_id -> Order
        self.trades: List[Trade] = []
        self.price_cache: Dict[str, float] = {}  # market_id -> current price
        
        # Order counter for ID generation
        self._order_counter = 0
        
        # Load state if exists
        self._load_state()
        
        logger.info(f"Paper trader initialized with ${initial_balance:,.2f}")
    
    def _generate_id(self, prefix: str = "order") -> str:
        """Generate unique order ID."""
        self._order_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{prefix}_{timestamp}_{self._order_counter}"
    
    def _load_state(self):
        """Load saved state from disk."""
        state_file = self.data_dir / "paper_trader_state.json"
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                self.portfolio = Portfolio(**state.get('portfolio', {}))
                self.positions = {
                    k: Position(**v) for k, v in state.get('positions', {}).items()
                }
                logger.info(f"Loaded saved state: ${self.portfolio.balance:,.2f}")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        """Save current state to disk."""
        state = {
            'portfolio': {
                'initial_balance': self.portfolio.initial_balance,
                'balance': self.portfolio.balance,
                'total_pnl': self.portfolio.total_pnl,
                'total_trades': self.portfolio.total_trades,
                'winning_trades': self.portfolio.winning_trades,
                'losing_trades': self.losing_trades,
                'max_drawdown': self.portfolio.max_drawdown,
                'peak_balance': self.portfolio.peak_balance,
                'created_at': self.portfolio.created_at.isoformat()
            },
            'positions': {k: v.to_dict() for k, v in self.positions.items()},
            'last_updated': datetime.now().isoformat()
        }
        
        state_file = self.data_dir / "paper_trader_state.json"
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def place_order(
        self,
        market_id: str,
        side: OrderSide,
        position_side: PositionSide,
        size: float,
        price: float,
        immediate_fill: bool = True
    ) -> Order:
        """
        Place a paper order.
        
        Args:
            market_id: Polymarket market ID
            side: buy or sell
            position_side: yes or no
            size: Number of shares
            price: Price per share (0.01 to 0.99)
            immediate_fill: Whether to simulate immediate fill
        
        Returns:
            Order object
        """
        order = Order(
            id=self._generate_id("order"),
            market_id=market_id,
            side=side,
            position_side=position_side,
            size=size,
            price=price
        )
        
        # Check balance for buys
        if side == OrderSide.BUY:
            cost = size * price * (1 + self.trading_fee)
            if cost > self.portfolio.balance:
                order.status = OrderStatus.REJECTED
                logger.warning(f"Order rejected: insufficient balance (${cost:.2f} > ${self.portfolio.balance:.2f})")
                return order
        
        self.orders[order.id] = order
        
        if immediate_fill:
            self._fill_order(order)
        
        self._save_state()
        
        logger.info(
            f"Order placed: {side.value} {size} {position_side.value} "
            f"@{price:.4f} in {market_id}"
        )
        
        return order
    
    def _fill_order(self, order: Order):
        """Simulate order fill."""
        order.status = OrderStatus.FILLED
        order.filled_size = order.size
        order.filled_price = order.price
        order.filled_at = datetime.now()
        
        # Calculate trade value with fees
        trade_value = order.size * order.price
        fee = trade_value * self.trading_fee
        
        # Record trade
        trade = Trade(
            id=self._generate_id("trade"),
            order_id=order.id,
            market_id=order.market_id,
            side=order.side,
            position_side=order.position_side,
            size=order.size,
            price=order.price,
            timestamp=datetime.now()
        )
        
        # Update positions
        position_key = f"{order.market_id}:{order.position_side.value}"
        
        if order.side == OrderSide.BUY:
            # Opening or adding to position
            if position_key in self.positions:
                # Average into existing position
                pos = self.positions[position_key]
                total_cost = pos.size * pos.avg_entry_price + trade_value
                pos.size += order.size
                pos.avg_entry_price = total_cost / pos.size
                pos.last_updated = datetime.now()
            else:
                # New position
                self.positions[position_key] = Position(
                    market_id=order.market_id,
                    side=order.position_side,
                    size=order.size,
                    avg_entry_price=order.price
                )
            
            # Deduct balance
            self.portfolio.balance -= (trade_value + fee)
            trade.pnl = -fee
            
        else:  # SELL
            # Closing or reducing position
            if position_key in self.positions:
                pos = self.positions[position_key]
                
                # Calculate P&L
                if order.position_side == PositionSide.YES:
                    pnl = (order.price - pos.avg_entry_price) * order.size
                else:  # NO
                    pnl = ((1 - order.price) - pos.avg_entry_price) * order.size
                
                pnl -= fee
                trade.pnl = pnl
                
                # Update position
                pos.size -= order.size
                pos.realized_pnl += pnl
                pos.last_updated = datetime.now()
                
                if pos.size <= 0:
                    del self.positions[position_key]
                
                # Add to balance
                self.portfolio.balance += (trade_value - fee)
                self.portfolio.record_trade(pnl)
            else:
                # Short selling (opening new short)
                short_side = PositionSide.NO if order.position_side == PositionSide.YES else PositionSide.YES
                short_key = f"{order.market_id}:{short_side.value}"
                
                self.positions[short_key] = Position(
                    market_id=order.market_id,
                    side=short_side,
                    size=order.size,
                    avg_entry_price=1 - order.price  # Inverted for short
                )
                
                self.portfolio.balance += (trade_value - fee)
                trade.pnl = -fee
        
        self.trades.append(trade)
        
        logger.info(
            f"Order filled: {order.side.value} {order.size} @{order.price:.4f} "
            f"PnL: ${trade.pnl:.4f}"
        )
    
    def get_position(self, market_id: str) -> Optional[Position]:
        """Get position for a market."""
        for key, pos in self.positions.items():
            if pos.market_id == market_id:
                return pos
        return None
    
    def get_all_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self.positions.values())
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary."""
        # Calculate unrealized P&L
        unrealized_pnl = 0.0
        for pos in self.positions.values():
            current_price = self.price_cache.get(pos.market_id, 0.5)
            unrealized_pnl += pos.unrealized_pnl(current_price)
        
        return {
            'portfolio': self.portfolio.to_dict(),
            'unrealized_pnl': unrealized_pnl,
            'total_equity': self.portfolio.balance + unrealized_pnl,
            'open_positions': len(self.positions),
            'positions': [p.to_dict() for p in self.positions.values()]
        }
    
    def update_market_price(self, market_id: str, price: float):
        """Update cached market price for P&L calculation."""
        self.price_cache[market_id] = price
    
    def get_trade_history(self) -> pd.DataFrame:
        """Get trade history as DataFrame."""
        if not self.trades:
            return pd.DataFrame()
        
        data = [t.to_dict() for t in self.trades]
        df = pd.DataFrame(data)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    
    def reset(self, confirm: bool = False):
        """Reset paper trading account."""
        if not confirm:
            logger.warning("Set confirm=True to reset account")
            return
        
        self.portfolio = Portfolio(
            initial_balance=self.initial_balance,
            balance=self.initial_balance
        )
        self.positions = {}
        self.orders = {}
        self.trades = []
        self.price_cache = {}
        
        # Delete state file
        state_file = self.data_dir / "paper_trader_state.json"
        if state_file.exists():
            state_file.unlink()
        
        logger.info("Paper trading account reset")


class PolymarketPaperTradingBot:
    """
    Production-ready paper trading bot for Polymarket strategies.
    Integrates with strategy logic for realistic simulation.
    """
    
    def __init__(
        self,
        strategy_name: str,
        initial_balance: float = 10000.0,
        max_positions: int = 10,
        risk_per_trade: float = 0.02  # 2% per trade
    ):
        self.strategy_name = strategy_name
        self.trader = PolymarketPaperTrader(initial_balance=initial_balance)
        self.max_positions = max_positions
        self.risk_per_trade = risk_per_trade
        self.is_running = False
    
    def calculate_position_size(
        self,
        price: float,
        stop_loss: float,
        confidence: float
    ) -> float:
        """
        Calculate position size based on risk management.
        
        Args:
            price: Entry price
            stop_loss: Stop loss price
            confidence: Signal confidence (0-1)
        
        Returns:
            Position size in shares
        """
        portfolio_value = self.trader.portfolio.balance
        risk_amount = portfolio_value * self.risk_per_trade * confidence
        
        price_risk = abs(price - stop_loss)
        if price_risk == 0:
            return 0
        
        size = risk_amount / price_risk
        
        # Cap position size
        max_position_value = portfolio_value * 0.1  # 10% max per position
        max_size = max_position_value / price
        
        return min(size, max_size)
    
    def on_signal(
        self,
        market_id: str,
        signal_type: str,  # 'buy_yes', 'buy_no', 'sell_yes', 'sell_no'
        price: float,
        confidence: float,
        stop_loss: Optional[float] = None
    ) -> Optional[Order]:
        """
        Process trading signal.
        
        Args:
            market_id: Market ID
            signal_type: Type of signal
            price: Target price
            confidence: Signal confidence
            stop_loss: Optional stop loss price
        
        Returns:
            Order if executed
        """
        if not self.is_running:
            logger.warning("Bot not running")
            return None
        
        # Check position limits
        if len(self.trader.positions) >= self.max_positions:
            logger.warning("Max positions reached")
            return None
        
        # Parse signal
        parts = signal_type.split('_')
        if len(parts) != 2:
            logger.error(f"Invalid signal type: {signal_type}")
            return None
        
        action, position = parts
        
        side = OrderSide.BUY if action == 'buy' else OrderSide.SELL
        position_side = PositionSide.YES if position == 'yes' else PositionSide.NO
        
        # Calculate size
        stop = stop_loss or (price * 0.95 if side == OrderSide.BUY else price * 1.05)
        size = self.calculate_position_size(price, stop, confidence)
        
        if size <= 0:
            logger.warning("Calculated size is 0")
            return None
        
        # Place order
        order = self.trader.place_order(
            market_id=market_id,
            side=side,
            position_side=position_side,
            size=size,
            price=price
        )
        
        return order
    
    def get_status(self) -> Dict:
        """Get bot status."""
        return {
            'strategy': self.strategy_name,
            'is_running': self.is_running,
            'portfolio': self.trader.get_portfolio_summary()
        }
    
    def start(self):
        """Start the paper trading bot."""
        self.is_running = True
        logger.info(f"Paper trading bot '{self.strategy_name}' started")
    
    def stop(self):
        """Stop the paper trading bot."""
        self.is_running = False
        logger.info(f"Paper trading bot '{self.strategy_name}' stopped")


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Create paper trader
    trader = PolymarketPaperTrader(initial_balance=10000.0)
    
    # Simulate some trades
    order1 = trader.place_order(
        market_id="0x123abc",
        side=OrderSide.BUY,
        position_side=PositionSide.YES,
        size=100,
        price=0.55
    )
    
    print(f"\nPortfolio: {trader.get_portfolio_summary()}")
    
    # Update price and close position
    trader.update_market_price("0x123abc", 0.60)
    
    order2 = trader.place_order(
        market_id="0x123abc",
        side=OrderSide.SELL,
        position_side=PositionSide.YES,
        size=100,
        price=0.60
    )
    
    print(f"\nFinal Portfolio: {trader.get_portfolio_summary()}")
    print(f"\nTrade History:\n{trader.get_trade_history()}")
