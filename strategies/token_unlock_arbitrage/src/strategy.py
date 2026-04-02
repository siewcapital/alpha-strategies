"""
Token Unlock Arbitrage Strategy
================================
Research Source: Animoca Brands/Smartkarma (35,000 unlock events, 89 tokens)
Key Finding: 1% unlock → 0.3% price drop (anticipation + post-unlock selling)
Optimal Entry: 2 days before unlock
Optimal Exit: Days 3-4 after unlock

Edge: Predictable market microstructure around predictable supply shocks.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Tuple
import numpy as np
import pandas as pd
from pathlib import Path
import yaml
import json


class SignalType(Enum):
    SHORT = "short"
    NEUTRAL = "neutral"


class PositionStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class UnlockEvent:
    """Represents a token unlock event."""
    token: str
    unlock_date: datetime
    unlock_amount: float  # in tokens
    circulating_supply: float
    unlock_pct: float = field(init=False)  # % of circulating supply
    
    def __post_init__(self):
        self.unlock_pct = (self.unlock_amount / self.circulating_supply) * 100
    
    @property
    def is_significant(self) -> bool:
        """Unlocks > 1% of supply are significant per research."""
        return self.unlock_pct >= 1.0
    
    @property
    def impact_score(self) -> float:
        """Calculate expected price impact score."""
        # Research: 1% unlock ≈ 0.3% price drop each direction
        # Scale by square root (diminishing returns on larger unlocks)
        return -0.3 * np.sqrt(self.unlock_pct)


@dataclass
class Trade:
    """Represents a trade."""
    token: str
    entry_date: datetime
    exit_date: Optional[datetime] = None
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    position_size: float = 0.0  # USD
    signal_type: SignalType = SignalType.NEUTRAL
    status: PositionStatus = PositionStatus.PENDING
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    
    def close(self, exit_price: float, exit_date: datetime):
        """Close the trade."""
        self.exit_price = exit_price
        self.exit_date = exit_date
        self.status = PositionStatus.CLOSED
        
        if self.signal_type == SignalType.SHORT:
            self.pnl = (self.entry_price - exit_price) * (self.position_size / self.entry_price)
            self.pnl_pct = (self.entry_price - exit_price) / self.entry_price
        else:
            self.pnl = (exit_price - self.entry_price) * (self.position_size / self.entry_price)
            self.pnl_pct = (exit_price - self.entry_price) / self.entry_price


class TokenUnlockStrategy:
    """
    Token Unlock Arbitrage Strategy
    
    Entry Rules (per research):
    - Identify unlocks > 1% of circulating supply
    - Enter SHORT 2 days before unlock date
    - Position size scales with unlock magnitude
    
    Exit Rules:
    - Exit on day 4 after unlock (peak selling pressure ends)
    - OR stop loss hit
    - OR profit target (3x expected move)
    
    Risk Management:
    - Max 10% portfolio per trade
    - Max 3 concurrent positions
    - Stop loss: 2% (tight, this is an event trade)
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.params = self._load_params(config_path)
        self.positions: Dict[str, Trade] = {}
        self.trade_history: List[Trade] = []
        self.unlocks: List[UnlockEvent] = []
        self.current_date: Optional[datetime] = None
        self.portfolio_value: float = self.params.get('initial_capital', 100000)
        
    def _load_params(self, config_path: Optional[str]) -> dict:
        """Load strategy parameters."""
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        
        # Default parameters based on research
        return {
            'initial_capital': 100000,
            'max_position_pct': 0.10,  # 10% max per trade
            'max_concurrent_positions': 3,
            'min_unlock_pct': 1.0,  # Minimum 1% of supply to trade
            'entry_days_before': 2,  # Research: 2 days before optimal
            'exit_days_after': 4,  # Research: day 4 post-unlock
            'stop_loss_pct': 0.02,  # 2% stop (tight for event trade)
            'profit_target_multiplier': 3.0,  # 3x expected move
            'trading_cost_pct': 0.001,  # 0.1% round-trip
        }
    
    def load_unlock_schedule(self, unlock_data: List[Dict]):
        """Load unlock events from data source."""
        self.unlocks = []
        for data in unlock_data:
            unlock = UnlockEvent(
                token=data['token'],
                unlock_date=datetime.fromisoformat(data['unlock_date']),
                unlock_amount=data['unlock_amount'],
                circulating_supply=data['circulating_supply']
            )
            self.unlocks.append(unlock)
        
        # Sort by date
        self.unlocks.sort(key=lambda x: x.unlock_date)
        print(f"Loaded {len(self.unlocks)} unlock events")
        print(f"Significant unlocks (≥1%): {sum(1 for u in self.unlocks if u.is_significant)}")
    
    def generate_signals(self, date: datetime, prices: Dict[str, float]) -> List[Trade]:
        """Generate entry signals for the given date."""
        self.current_date = date
        signals = []
        
        for unlock in self.unlocks:
            # Check if entry day (2 days before unlock)
            entry_date = unlock.unlock_date - timedelta(days=self.params['entry_days_before'])
            
            if date.date() == entry_date.date() and unlock.is_significant:
                # Check if we already have a position
                if unlock.token in self.positions:
                    continue
                
                # Check max positions
                if len(self.positions) >= self.params['max_concurrent_positions']:
                    continue
                
                # Check price available
                if unlock.token not in prices:
                    continue
                
                # Calculate position size based on Kelly Criterion
                # Research: 1% unlock → 0.3% drop, but we expect 2x that (anticipation + selling)
                expected_return = abs(unlock.impact_score) * 2  # 2x for entry+exit capture
                win_rate = 0.65  # Research-based estimate
                
                kelly_pct = self._kelly_criterion(win_rate, expected_return, self.params['stop_loss_pct'])
                position_pct = min(kelly_pct * 0.25, self.params['max_position_pct'])  # Quarter-Kelly
                position_size = self.portfolio_value * position_pct
                
                trade = Trade(
                    token=unlock.token,
                    entry_date=date,
                    entry_price=prices[unlock.token],
                    position_size=position_size,
                    signal_type=SignalType.SHORT,
                    status=PositionStatus.OPEN
                )
                
                signals.append(trade)
                self.positions[unlock.token] = trade
                
                print(f"🔴 SHORT {unlock.token} @ ${prices[unlock.token]:.4f}")
                print(f"   Unlock: {unlock.unlock_pct:.2f}% of supply on {unlock.unlock_date.date()}")
                print(f"   Position: ${position_size:,.2f} ({position_pct*100:.1f}%)")
        
        return signals
    
    def _kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Calculate Kelly criterion position size."""
        if avg_loss == 0:
            return 0
        b = avg_win / avg_loss
        q = 1 - win_rate
        kelly = (win_rate * b - q) / b
        return max(0, min(kelly, 0.5))  # Cap at 50%
    
    def check_exits(self, date: datetime, prices: Dict[str, float]) -> List[Trade]:
        """Check for exit signals."""
        exits = []
        
        for token, trade in list(self.positions.items()):
            if trade.status != PositionStatus.OPEN:
                continue
            
            current_price = prices.get(token)
            if not current_price:
                continue
            
            # Find the unlock event
            unlock = next((u for u in self.unlocks if u.token == token), None)
            if not unlock:
                continue
            
            exit_triggered = False
            exit_reason = ""
            
            # Check time-based exit (day 4 after unlock)
            exit_date = unlock.unlock_date + timedelta(days=self.params['exit_days_after'])
            if date.date() >= exit_date.date():
                exit_triggered = True
                exit_reason = "Time exit (day 4 post-unlock)"
            
            # Check stop loss (for shorts, price goes up)
            if trade.signal_type == SignalType.SHORT:
                loss_pct = (current_price - trade.entry_price) / trade.entry_price
                if loss_pct >= self.params['stop_loss_pct']:
                    exit_triggered = True
                    exit_reason = f"Stop loss ({loss_pct*100:.2f}%)"
                
                # Check profit target
                expected_move = abs(unlock.impact_score) * self.params['profit_target_multiplier']
                gain_pct = (trade.entry_price - current_price) / trade.entry_price
                if gain_pct >= expected_move:
                    exit_triggered = True
                    exit_reason = f"Profit target ({gain_pct*100:.2f}%)"
            
            if exit_triggered:
                trade.close(current_price, date)
                exits.append(trade)
                del self.positions[token]
                self.trade_history.append(trade)
                
                # Update portfolio value
                self.portfolio_value += trade.pnl
                
                print(f"✅ EXIT {token} @ ${current_price:.4f} | {exit_reason}")
                print(f"   PnL: ${trade.pnl:,.2f} ({trade.pnl_pct*100:+.2f}%)")
        
        return exits
    
    def get_metrics(self) -> Dict:
        """Calculate strategy performance metrics."""
        if not self.trade_history:
            return {}
        
        closed_trades = [t for t in self.trade_history if t.status == PositionStatus.CLOSED]
        if not closed_trades:
            return {}
        
        pnls = [t.pnl for t in closed_trades]
        pnl_pcts = [t.pnl_pct for t in closed_trades]
        
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_return = (self.portfolio_value - self.params['initial_capital']) / self.params['initial_capital']
        
        return {
            'total_trades': len(closed_trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': len(wins) / len(closed_trades) if closed_trades else 0,
            'avg_trade_pnl': np.mean(pnls) if pnls else 0,
            'avg_win': np.mean(wins) if wins else 0,
            'avg_loss': np.mean(losses) if losses else 0,
            'total_return': total_return,
            'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf'),
            'sharpe_ratio': self._calculate_sharpe(pnl_pcts),
            'max_drawdown': self._calculate_max_drawdown(),
            'current_portfolio': self.portfolio_value,
        }
    
    def _calculate_sharpe(self, returns: List[float], risk_free_rate: float = 0.0) -> float:
        """Calculate annualized Sharpe ratio."""
        if len(returns) < 2:
            return 0.0
        
        # Assume ~12 trades per year for scaling
        returns_array = np.array(returns)
        excess_returns = returns_array - risk_free_rate
        
        if np.std(excess_returns) == 0:
            return 0.0
        
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(12)
    
    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown."""
        if not self.trade_history:
            return 0.0
        
        # Calculate running portfolio value
        values = [self.params['initial_capital']]
        for trade in sorted(self.trade_history, key=lambda x: x.exit_date or x.entry_date):
            if trade.pnl is not None:
                values.append(values[-1] + trade.pnl)
        
        peak = values[0]
        max_dd = 0.0
        
        for value in values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            max_dd = max(max_dd, dd)
        
        return max_dd
    
    def print_summary(self):
        """Print strategy summary."""
        metrics = self.get_metrics()
        
        print("\n" + "="*60)
        print("TOKEN UNLOCK ARBITRAGE - PERFORMANCE SUMMARY")
        print("="*60)
        
        if not metrics:
            print("No completed trades yet.")
            return
        
        print(f"\nTotal Trades: {metrics['total_trades']}")
        print(f"Win Rate: {metrics['win_rate']*100:.1f}%")
        print(f"Total Return: {metrics['total_return']*100:+.2f}%")
        print(f"Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"Max Drawdown: {metrics['max_drawdown']*100:.2f}%")
        print(f"\nAvg Trade PnL: ${metrics['avg_trade_pnl']:,.2f}")
        print(f"Avg Win: ${metrics['avg_win']:,.2f}")
        print(f"Avg Loss: ${metrics['avg_loss']:,.2f}")
        print(f"\nFinal Portfolio: ${metrics['current_portfolio']:,.2f}")
        print("="*60)


if __name__ == "__main__":
    # Quick test
    strategy = TokenUnlockStrategy()
    print("Token Unlock Arbitrage Strategy initialized")
    print(f"Min unlock size: {strategy.params['min_unlock_pct']}% of supply")
    print(f"Entry: {strategy.params['entry_days_before']} days before")
    print(f"Exit: {strategy.params['exit_days_after']} days after")
