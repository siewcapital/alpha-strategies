"""
Risk Manager for Options Dispersion Trading Strategy
Handles position sizing, greek limits, and risk controls
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class PositionStatus(Enum):
    NO_POSITION = 0
    LONG_DISPERSION = 1  # Short index vol, long single vol
    SHORT_DISPERSION = -1  # Long index vol, short single vol


@dataclass
class Greeks:
    """Container for option Greeks"""
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    
    def __add__(self, other):
        return Greeks(
            delta=self.delta + other.delta,
            gamma=self.gamma + other.gamma,
            theta=self.theta + other.theta,
            vega=self.vega + other.vega,
            rho=self.rho + other.rho
        )
    
    def __mul__(self, scalar):
        return Greeks(
            delta=self.delta * scalar,
            gamma=self.gamma * scalar,
            theta=self.theta * scalar,
            vega=self.vega * scalar,
            rho=self.rho * scalar
        )


@dataclass
class Position:
    """Represents an option position"""
    underlying: str
    option_type: str  # 'call' or 'put'
    strike: float
    expiration: pd.Timestamp
    quantity: int  # Positive for long, negative for short
    entry_price: float
    entry_date: pd.Timestamp
    greeks: Greeks = None
    
    def __post_init__(self):
        if self.greeks is None:
            self.greeks = Greeks()


class RiskManager:
    """
    Manages risk for the dispersion trading strategy
    """
    
    def __init__(
        self,
        portfolio_value: float,
        target_vega_exposure: float = 0.001,
        max_vega_exposure: float = 0.005,
        max_delta_exposure: float = 0.10,
        max_gamma_exposure: float = 0.001,
        max_loss_per_trade: float = 0.02,
        max_correlation_exposure: float = 0.01,
        stop_correlation_move: float = 3.0
    ):
        self.portfolio_value = portfolio_value
        self.target_vega_exposure = target_vega_exposure
        self.max_vega_exposure = max_vega_exposure
        self.max_delta_exposure = max_delta_exposure
        self.max_gamma_exposure = max_gamma_exposure
        self.max_loss_per_trade = max_loss_per_trade
        self.max_correlation_exposure = max_correlation_exposure
        self.stop_correlation_move = stop_correlation_move
        
        self.positions: List[Position] = []
        self.position_history: List[Dict] = []
        self.trade_pnl: List[Dict] = []
        
        self.entry_correlation: Optional[float] = None
        self.entry_zscore: Optional[float] = None
        self.holding_days: int = 0
        self.max_holding_days: int = 30
        
    def calculate_portfolio_greeks(self) -> Greeks:
        """Calculate total portfolio Greeks"""
        total = Greeks()
        for pos in self.positions:
            multiplier = pos.quantity
            total = total + (pos.greeks * multiplier)
        return total
    
    def calculate_notional_exposure(self) -> Dict[str, float]:
        """Calculate notional exposure by underlying"""
        exposures = {}
        for pos in self.positions:
            notional = pos.quantity * pos.strike  # Simplified
            if pos.underlying not in exposures:
                exposures[pos.underlying] = 0
            exposures[pos.underlying] += notional
        return exposures
    
    def check_greek_limits(self) -> Tuple[bool, Dict]:
        """
        Check if current Greeks are within limits
        """
        greeks = self.calculate_portfolio_greeks()
        
        checks = {
            'delta': abs(greeks.delta) < self.max_delta_exposure * self.portfolio_value,
            'gamma': abs(greeks.gamma) < self.max_gamma_exposure * self.portfolio_value,
            'vega': abs(greeks.vega) < self.max_vega_exposure * self.portfolio_value,
        }
        
        all_pass = all(checks.values())
        return all_pass, checks
    
    def calculate_position_size(
        self,
        index_vega: float,
        avg_constituent_vega: float,
        signal_type: str
    ) -> Dict[str, int]:
        """
        Calculate position sizes for index and constituents
        
        Returns number of contracts for each leg
        """
        target_vega = self.target_vega_exposure * self.portfolio_value
        
        # Index position (short)
        index_contracts = int(target_vega / (index_vega * 100))  # Options are 100 shares
        
        # Constituent positions (long) - spread across basket
        # Each constituent gets proportional weight
        n_constituents = 30  # Typical number
        constituent_contracts_per = int(
            (target_vega / n_constituents) / (avg_constituent_vega * 100)
        )
        
        if signal_type == 'SHORT_DISPERSION':
            # Reverse the signs
            index_contracts = -index_contracts
            constituent_contracts_per = -constituent_contracts_per
            
        return {
            'index_contracts': index_contracts,
            'constituent_contracts_per': constituent_contracts_per
        }
    
    def check_entry_conditions(
        self,
        implied_correlation: float,
        correlation_zscore: float,
        vix: float,
        current_positions: List[Position]
    ) -> Tuple[bool, str]:
        """
        Check if entry conditions are met
        """
        # Check if already in position
        if len(current_positions) > 0:
            return False, "already_in_position"
        
        # Check Greek limits
        greeks_ok, greek_checks = self.check_greek_limits()
        if not greeks_ok:
            return False, f"greek_limits: {greek_checks}"
        
        # Check if we have enough capital
        available_capital = self.portfolio_value * 0.2  # 20% max per trade
        if available_capital < 10000:  # Minimum $10k per trade
            return False, "insufficient_capital"
        
        return True, "ok"
    
    def check_exit_conditions(
        self,
        current_correlation: float,
        current_zscore: float,
        unrealized_pnl: float,
        days_in_trade: int
    ) -> Tuple[bool, str]:
        """
        Check if exit conditions are triggered
        """
        # Time stop
        if days_in_trade >= self.max_holding_days:
            return True, "time_stop"
        
        # Stop loss on correlation move
        if self.entry_zscore is not None:
            zscore_move = abs(current_zscore - self.entry_zscore)
            if zscore_move > self.stop_correlation_move:
                return True, "correlation_stop"
        
        # P&L stop loss
        pnl_pct = unrealized_pnl / self.portfolio_value
        if pnl_pct < -self.max_loss_per_trade:
            return True, "stop_loss"
        
        return False, "hold"
    
    def calculate_margin_requirement(
        self,
        positions: List[Position],
        index_price: float
    ) -> float:
        """
        Calculate approximate margin requirement
        Simplified calculation - real margin is more complex
        """
        margin = 0.0
        
        for pos in positions:
            if pos.quantity < 0:  # Short options
                # Simplified margin: 20% of underlying + premium
                notional = abs(pos.quantity) * index_price * 100
                margin += notional * 0.20
            else:  # Long options - just premium paid
                margin += abs(pos.quantity) * pos.entry_price * 100
        
        return margin
    
    def update_portfolio_value(self, new_value: float):
        """Update portfolio value (for P&L tracking)"""
        self.portfolio_value = new_value
    
    def record_trade(
        self,
        action: str,  # 'entry' or 'exit'
        position_type: str,
        timestamp: pd.Timestamp,
        pnl: float = 0.0,
        greeks: Optional[Greeks] = None
    ):
        """Record trade for analysis"""
        self.position_history.append({
            'action': action,
            'position_type': position_type,
            'timestamp': timestamp,
            'pnl': pnl,
            'portfolio_value': self.portfolio_value,
            'greeks': greeks.__dict__ if greeks else {}
        })
        
        if action == 'exit':
            self.trade_pnl.append({
                'timestamp': timestamp,
                'pnl': pnl,
                'position_type': position_type,
                'holding_days': self.holding_days
            })
            self.holding_days = 0
    
    def reset_position_tracking(self):
        """Reset tracking for new position"""
        self.entry_correlation = None
        self.entry_zscore = None
        self.holding_days = 0
        self.positions = []
    
    def increment_holding_days(self):
        """Increment holding days counter"""
        self.holding_days += 1
    
    def get_risk_report(self) -> Dict:
        """Generate current risk report"""
        greeks = self.calculate_portfolio_greeks()
        
        return {
            'portfolio_value': self.portfolio_value,
            'total_positions': len(self.positions),
            'greeks': {
                'delta': greeks.delta,
                'gamma': greeks.gamma,
                'theta': greeks.theta,
                'vega': greeks.vega
            },
            'greek_limits': {
                'delta_limit': self.max_delta_exposure * self.portfolio_value,
                'gamma_limit': self.max_gamma_exposure * self.portfolio_value,
                'vega_limit': self.max_vega_exposure * self.portfolio_value
            },
            'holding_days': self.holding_days,
            'entry_correlation': self.entry_correlation,
            'entry_zscore': self.entry_zscore
        }
