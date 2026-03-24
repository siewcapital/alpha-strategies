import os
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

# Set up paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"


class PositionStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class BasisPosition:
    """Represents a basis trade position (long spot + short perp)."""
    
    # Position identification
    position_id: str
    symbol: str
    exchange: str
    
    # Entry details
    entry_timestamp: datetime
    entry_spot_price: float
    entry_perp_price: float
    entry_basis: float
    
    # Position sizes
    spot_size: float  # Amount of spot asset
    perp_size: float  # Amount of perp contracts (negative = short)
    
    # Margin/collateral
    margin_required: float
    leverage: float = 1.0
    
    # Current state
    status: PositionStatus = PositionStatus.PENDING
    
    # Exit details (filled when closing)
    exit_timestamp: Optional[datetime] = None
    exit_spot_price: Optional[float] = None
    exit_perp_price: Optional[float] = None
    exit_basis: Optional[float] = None
    
    # P&L tracking
    realized_pnl: float = 0.0
    funding_pnl: float = 0.0  # Accumulated funding payments
    fees: float = 0.0
    
    # Risk management
    stop_loss_basis: Optional[float] = None  # Close if basis drops below this
    take_profit_basis: Optional[float] = None  # Close if basis reaches this
    
    def __post_init__(self):
        """Generate position ID if not provided."""
        if not self.position_id:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            self.position_id = f"{self.exchange}_{self.symbol}_{timestamp}"
    
    @property
    def current_basis_premium(self) -> float:
        """Calculate the basis premium at entry."""
        return (self.entry_perp_price - self.entry_spot_price) / self.entry_spot_price
    
    @property
    def days_held(self) -> int:
        """Number of days position has been held."""
        end_time = self.exit_timestamp or datetime.now()
        return (end_time - self.entry_timestamp).days
    
    def calculate_unrealized_pnl(self, current_spot: float, current_perp: float) -> float:
        """
        Calculate unrealized P&L based on current prices.
        
        For basis trade:
        - Long spot: profit when spot price increases
        - Short perp: profit when perp price decreases
        """
        spot_pnl = (current_spot - self.entry_spot_price) * self.spot_size
        perp_pnl = (self.entry_perp_price - current_perp) * abs(self.perp_size)
        
        return spot_pnl + perp_pnl - self.fees
    
    def calculate_net_yield(self, current_spot: float, current_perp: float) -> float:
        """Calculate net yield percentage including funding."""
        unrealized = self.calculate_unrealized_pnl(current_spot, current_perp)
        total_pnl = unrealized + self.realized_pnl + self.funding_pnl
        
        if self.margin_required > 0:
            return (total_pnl / self.margin_required) * 100
        return 0.0
    
    def to_dict(self) -> Dict:
        """Convert position to dictionary for serialization."""
        return {
            'position_id': self.position_id,
            'symbol': self.symbol,
            'exchange': self.exchange,
            'entry_timestamp': self.entry_timestamp.isoformat(),
            'entry_spot_price': self.entry_spot_price,
            'entry_perp_price': self.entry_perp_price,
            'entry_basis': self.entry_basis,
            'spot_size': self.spot_size,
            'perp_size': self.perp_size,
            'margin_required': self.margin_required,
            'leverage': self.leverage,
            'status': self.status.value,
            'exit_timestamp': self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            'exit_spot_price': self.exit_spot_price,
            'exit_perp_price': self.exit_perp_price,
            'exit_basis': self.exit_basis,
            'realized_pnl': self.realized_pnl,
            'funding_pnl': self.funding_pnl,
            'fees': self.fees,
            'stop_loss_basis': self.stop_loss_basis,
            'take_profit_basis': self.take_profit_basis
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'BasisPosition':
        """Create position from dictionary."""
        return cls(
            position_id=data['position_id'],
            symbol=data['symbol'],
            exchange=data['exchange'],
            entry_timestamp=datetime.fromisoformat(data['entry_timestamp']),
            entry_spot_price=data['entry_spot_price'],
            entry_perp_price=data['entry_perp_price'],
            entry_basis=data['entry_basis'],
            spot_size=data['spot_size'],
            perp_size=data['perp_size'],
            margin_required=data['margin_required'],
            leverage=data.get('leverage', 1.0),
            status=PositionStatus(data['status']),
            exit_timestamp=datetime.fromisoformat(data['exit_timestamp']) if data.get('exit_timestamp') else None,
            exit_spot_price=data.get('exit_spot_price'),
            exit_perp_price=data.get('exit_perp_price'),
            exit_basis=data.get('exit_basis'),
            realized_pnl=data.get('realized_pnl', 0.0),
            funding_pnl=data.get('funding_pnl', 0.0),
            fees=data.get('fees', 0.0),
            stop_loss_basis=data.get('stop_loss_basis'),
            take_profit_basis=data.get('take_profit_basis')
        )


class PositionManager:
    """
    Manages basis trade positions across multiple exchanges.
    
    Handles:
    - Position tracking and lifecycle
    - P&L calculation
    - Risk monitoring
    - Position sizing
    """
    
    def __init__(self, state_file: str = None):
        """
        Initialize position manager.
        
        Args:
            state_file: Path to file for persisting position state
        """
        self.positions: Dict[str, BasisPosition] = {}
        self.position_history: List[BasisPosition] = []
        self.state_file = state_file or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'data', 'positions.json'
        )
        
        # Create data directory if needed
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        
        # Load any existing positions
        self.load_state()
    
    def create_position(self, 
                       symbol: str,
                       exchange: str,
                       spot_size: float,
                       entry_spot_price: float,
                       entry_perp_price: float,
                       entry_basis: float,
                       margin_required: float,
                       leverage: float = 1.0,
                       stop_loss_basis: Optional[float] = None,
                       take_profit_basis: Optional[float] = None) -> BasisPosition:
        """
        Create a new basis trade position.
        
        Args:
            symbol: Trading pair (e.g., 'BTC')
            exchange: Exchange name
            spot_size: Amount of spot asset to buy
            entry_spot_price: Entry price for spot leg
            entry_perp_price: Entry price for perp leg
            entry_basis: Annualized basis at entry
            margin_required: Capital required for position
            leverage: Leverage used for perp short
            stop_loss_basis: Basis level to trigger stop loss
            take_profit_basis: Basis level to trigger take profit
            
        Returns:
            New BasisPosition object
        """
        # Generate position ID
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        position_id = f"{exchange}_{symbol}_{timestamp}"
        
        # Perp size is negative (short)
        perp_size = -spot_size
        
        position = BasisPosition(
            position_id=position_id,
            symbol=symbol,
            exchange=exchange,
            entry_timestamp=datetime.now(),
            entry_spot_price=entry_spot_price,
            entry_perp_price=entry_perp_price,
            entry_basis=entry_basis,
            spot_size=spot_size,
            perp_size=perp_size,
            margin_required=margin_required,
            leverage=leverage,
            status=PositionStatus.OPEN,
            stop_loss_basis=stop_loss_basis,
            take_profit_basis=take_profit_basis
        )
        
        self.positions[position_id] = position
        self.save_state()
        
        return position
    
    def close_position(self, 
                      position_id: str,
                      exit_spot_price: float,
                      exit_perp_price: float) -> BasisPosition:
        """
        Close an existing position.
        
        Args:
            position_id: ID of position to close
            exit_spot_price: Current spot price
            exit_perp_price: Current perp price
            
        Returns:
            Closed BasisPosition object
        """
        if position_id not in self.positions:
            raise ValueError(f"Position {position_id} not found")
        
        position = self.positions[position_id]
        position.status = PositionStatus.CLOSED
        position.exit_timestamp = datetime.now()
        position.exit_spot_price = exit_spot_price
        position.exit_perp_price = exit_perp_price
        position.exit_basis = ((exit_perp_price - exit_spot_price) / exit_spot_price) * 100
        
        # Calculate realized P&L
        position.realized_pnl = position.calculate_unrealized_pnl(
            exit_spot_price, exit_perp_price
        )
        
        # Move to history
        self.position_history.append(position)
        del self.positions[position_id]
        
        self.save_state()
        
        return position
    
    def update_funding_pnl(self, position_id: str, funding_payment: float):
        """Update funding P&L for a position."""
        if position_id in self.positions:
            self.positions[position_id].funding_pnl += funding_payment
            self.save_state()
    
    def get_position(self, position_id: str) -> Optional[BasisPosition]:
        """Get a specific position by ID."""
        return self.positions.get(position_id)
    
    def get_open_positions(self, symbol: str = None, exchange: str = None) -> List[BasisPosition]:
        """Get all open positions, optionally filtered."""
        positions = list(self.positions.values())
        
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        if exchange:
            positions = [p for p in positions if p.exchange == exchange]
            
        return positions
    
    def get_total_exposure(self) -> Dict[str, float]:
        """Get total exposure by symbol."""
        exposure = {}
        for position in self.positions.values():
            if position.symbol not in exposure:
                exposure[position.symbol] = 0.0
            exposure[position.symbol] += position.spot_size * position.entry_spot_price
        return exposure
    
    def get_total_margin_used(self) -> float:
        """Get total margin used by all positions."""
        return sum(p.margin_required for p in self.positions.values())
    
    def calculate_portfolio_value(self, current_prices: Dict[str, Dict[str, float]]) -> float:
        """
        Calculate total portfolio value including unrealized P&L.
        
        Args:
            current_prices: Dict of {symbol: {'spot': price, 'perp': price}}
        """
        total = 0.0
        
        for position in self.positions.values():
            if position.symbol in current_prices:
                prices = current_prices[position.symbol]
                unrealized = position.calculate_unrealized_pnl(
                    prices['spot'], prices['perp']
                )
                total += position.margin_required + unrealized
                
        return total
    
    def check_risk_limits(self, current_prices: Dict[str, Dict[str, float]]) -> List[Dict]:
        """
        Check if any positions need to be closed due to risk limits.
        
        Returns:
            List of positions that triggered risk limits
        """
        alerts = []
        
        for position in self.positions.values():
            if position.symbol not in current_prices:
                continue
                
            prices = current_prices[position.symbol]
            current_basis = ((prices['perp'] - prices['spot']) / prices['spot']) * 100
            
            # Check stop loss
            if position.stop_loss_basis and current_basis < position.stop_loss_basis:
                alerts.append({
                    'position_id': position.position_id,
                    'reason': 'stop_loss',
                    'current_basis': current_basis,
                    'trigger_level': position.stop_loss_basis
                })
            
            # Check take profit
            elif position.take_profit_basis and current_basis >= position.take_profit_basis:
                alerts.append({
                    'position_id': position.position_id,
                    'reason': 'take_profit',
                    'current_basis': current_basis,
                    'trigger_level': position.take_profit_basis
                })
        
        return alerts
    
    def get_performance_summary(self) -> Dict:
        """Get performance summary of all positions."""
        open_positions = list(self.positions.values())
        closed_positions = self.position_history
        
        total_realized_pnl = sum(p.realized_pnl for p in closed_positions)
        total_funding_pnl = sum(p.funding_pnl for p in closed_positions)
        
        winning_trades = [p for p in closed_positions if p.realized_pnl > 0]
        losing_trades = [p for p in closed_positions if p.realized_pnl <= 0]
        
        return {
            'open_positions': len(open_positions),
            'closed_positions': len(closed_positions),
            'total_realized_pnl': total_realized_pnl,
            'total_funding_pnl': total_funding_pnl,
            'total_pnl': total_realized_pnl + total_funding_pnl,
            'win_rate': len(winning_trades) / len(closed_positions) if closed_positions else 0,
            'avg_win': sum(p.realized_pnl for p in winning_trades) / len(winning_trades) if winning_trades else 0,
            'avg_loss': sum(p.realized_pnl for p in losing_trades) / len(losing_trades) if losing_trades else 0,
            'margin_used': self.get_total_margin_used()
        }
    
    def save_state(self):
        """Save position state to file."""
        state = {
            'positions': {k: v.to_dict() for k, v in self.positions.items()},
            'history': [p.to_dict() for p in self.position_history],
            'last_updated': datetime.now().isoformat()
        }
        
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def load_state(self):
        """Load position state from file."""
        if not os.path.exists(self.state_file):
            return
            
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            # Load open positions
            for pos_id, pos_data in state.get('positions', {}).items():
                self.positions[pos_id] = BasisPosition.from_dict(pos_data)
            
            # Load history
            for pos_data in state.get('history', []):
                self.position_history.append(BasisPosition.from_dict(pos_data))
                
        except Exception as e:
            print(f"Error loading state: {e}")


def main():
    """Test the position manager."""
    pm = PositionManager()
    
    # Create a test position
    position = pm.create_position(
        symbol='BTC',
        exchange='binance',
        spot_size=0.1,
        entry_spot_price=70000,
        entry_perp_price=70700,
        entry_basis=10.5,
        margin_required=7000,
        leverage=1.0,
        stop_loss_basis=5.0,
        take_profit_basis=15.0
    )
    
    print(f"Created position: {position.position_id}")
    print(f"Entry basis: {position.entry_basis:.2f}%")
    print(f"Margin required: ${position.margin_required:,.2f}")
    
    # Check P&L with current prices
    current_spot = 70500
    current_perp = 71000
    
    unrealized = position.calculate_unrealized_pnl(current_spot, current_perp)
    print(f"\nUnrealized P&L: ${unrealized:,.2f}")
    
    # Get summary
    summary = pm.get_performance_summary()
    print(f"\nPortfolio Summary:")
    print(f"  Open positions: {summary['open_positions']}")
    print(f"  Margin used: ${summary['margin_used']:,.2f}")


if __name__ == "__main__":
    main()
