"""
Cross-Exchange Funding Rate Arbitrage - Risk Manager Module
Manages position sizing, drawdown controls, and risk limits.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, NamedTuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    # Position limits
    max_position_size_usd: float = 100000.0
    max_total_exposure_usd: float = 500000.0
    max_positions_per_symbol: int = 2
    max_total_positions: int = 10
    
    # Leverage limits
    max_leverage_long: float = 3.0
    max_leverage_short: float = 3.0
    
    # Drawdown controls
    max_daily_drawdown_pct: float = 0.02  # 2%
    max_total_drawdown_pct: float = 0.10  # 10%
    
    # Loss limits
    max_daily_loss_usd: float = 5000.0
    max_consecutive_losses: int = 3
    
    # Funding-specific limits
    max_funding_volatility_entry: float = 0.001  # 0.1%
    min_liquidation_buffer: float = 0.10  # 10% from liquidation
    
    # Exchange limits
    max_exposure_per_exchange_pct: float = 0.30  # 30% per exchange
    
    # Correlation limits
    max_correlation_similar_positions: float = 0.8


@dataclass
class PortfolioState:
    """Current portfolio state for risk calculations."""
    total_equity: float = 0.0
    available_margin: float = 0.0
    total_exposure: float = 0.0
    
    # P&L tracking
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    peak_equity: float = 0.0
    
    # Position tracking
    positions_by_symbol: Dict[str, List[Dict]] = field(default_factory=dict)
    positions_by_exchange: Dict[str, float] = field(default_factory=dict)
    
    # Loss tracking
    consecutive_losses: int = 0
    last_trade_pnl: float = 0.0
    
    @property
    def current_drawdown_pct(self) -> float:
        """Calculate current drawdown from peak."""
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.total_equity) / self.peak_equity
    
    @property
    def position_count(self) -> int:
        """Total number of positions."""
        return sum(len(positions) for positions in self.positions_by_symbol.values())
    
    @property
    def is_in_drawdown(self) -> bool:
        """Check if currently in drawdown."""
        return self.total_equity < self.peak_equity


class RiskManager:
    """
    Manages risk for cross-exchange funding arbitrage strategy.
    """
    
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.state = PortfolioState()
        self._trade_history: List[Dict] = []
        self._daily_stats: Dict[str, Dict] = {}
        self._circuit_breaker_triggered: bool = False
        
    def calculate_position_size(
        self,
        opportunity_score: float,
        confidence: float,
        funding_differential: float,
        symbol: str,
        long_exchange: str,
        short_exchange: str,
        base_size: float
    ) -> Tuple[float, RiskLevel, List[str]]:
        """
        Calculate position size with risk adjustments.
        
        Returns:
            (adjusted_size, risk_level, warnings)
        """
        warnings = []
        risk_level = RiskLevel.LOW
        
        # Start with base size
        size = base_size
        
        # Factor 1: Kelly Criterion adjustment based on confidence
        kelly_fraction = self._kelly_criterion(confidence)
        size *= kelly_fraction
        
        # Factor 2: Opportunity quality
        if opportunity_score > 0.2:
            size *= 1.2
            risk_level = RiskLevel.MEDIUM
        elif opportunity_score < 0.05:
            size *= 0.7
        
        # Factor 3: Portfolio heat check
        heat_factor = self._calculate_heat_factor()
        size *= heat_factor
        
        if heat_factor < 0.8:
            warnings.append(f"Portfolio heat reduced size by {(1-heat_factor)*100:.1f}%")
        
        # Factor 4: Drawdown adjustment
        if self.state.is_in_drawdown:
            dd_factor = self._drawdown_size_reduction()
            size *= dd_factor
            warnings.append(f"Drawdown adjustment: size reduced to {dd_factor*100:.0f}%")
            risk_level = RiskLevel.HIGH
        
        # Factor 5: Per-symbol position limit
        symbol_positions = self.state.positions_by_symbol.get(symbol, [])
        if len(symbol_positions) >= self.limits.max_positions_per_symbol:
            size = 0
            warnings.append(f"Max positions for {symbol} reached")
            risk_level = RiskLevel.CRITICAL
        
        # Factor 6: Exchange exposure limit
        total_exposure = (
            self.state.positions_by_exchange.get(long_exchange, 0) +
            self.state.positions_by_exchange.get(short_exchange, 0)
        )
        max_exchange_exposure = self.limits.max_total_exposure_usd * self.limits.max_exposure_per_exchange_pct
        
        if total_exposure + size > max_exchange_exposure:
            size = max(0, max_exchange_exposure - total_exposure)
            warnings.append(f"Exchange exposure limit cap applied")
        
        # Factor 7: Absolute position size limit
        size = min(size, self.limits.max_position_size_usd)
        
        # Factor 8: Circuit breaker check
        if self._circuit_breaker_triggered:
            size = 0
            warnings.append("CIRCUIT BREAKER ACTIVE - No new positions")
            risk_level = RiskLevel.CRITICAL
        
        # Final bounds check
        size = max(0, min(size, self.state.available_margin * 0.95))
        
        return size, risk_level, warnings
    
    def _kelly_criterion(self, confidence: float, payoff_ratio: float = 1.5) -> float:
        """
        Calculate Kelly Criterion fraction.
        
        f* = (p*b - q) / b
        where p = win probability (confidence), b = payoff ratio, q = 1-p
        """
        p = confidence
        q = 1 - p
        b = payoff_ratio
        
        kelly = (p * b - q) / b
        
        # Use half-Kelly for safety
        half_kelly = max(0, kelly / 2)
        
        # Cap at 50% of capital
        return min(half_kelly, 0.5)
    
    def _calculate_heat_factor(self) -> float:
        """
        Calculate portfolio heat factor.
        
        Reduces position size as portfolio approaches limits.
        """
        if self.limits.max_total_exposure_usd <= 0:
            return 1.0
        
        current_heat = self.state.total_exposure / self.limits.max_total_exposure_usd
        
        if current_heat < 0.5:
            return 1.0
        elif current_heat < 0.7:
            return 0.8
        elif current_heat < 0.85:
            return 0.6
        else:
            return 0.3
    
    def _drawdown_size_reduction(self) -> float:
        """
        Reduce position size based on current drawdown.
        
        Exponential reduction as drawdown deepens.
        """
        dd = self.state.current_drawdown_pct
        max_dd = self.limits.max_total_drawdown_pct
        
        if dd <= 0:
            return 1.0
        
        # Exponential decay: at max DD, size = 0
        reduction = np.exp(-3 * dd / max_dd)
        
        return max(0.1, reduction)  # Minimum 10% size
    
    def check_entry_permissions(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str,
        proposed_size: float
    ) -> Tuple[bool, List[str]]:
        """
        Check if new position entry is permitted.
        
        Returns:
            (is_permitted, reasons)
        """
        reasons = []
        
        # Check circuit breaker
        if self._circuit_breaker_triggered:
            return False, ["Circuit breaker is active"]
        
        # Check total position limit
        if self.state.position_count >= self.limits.max_total_positions:
            return False, [f"Max total positions ({self.limits.max_total_positions}) reached"]
        
        # Check daily loss limit
        if abs(self.state.daily_pnl) >= self.limits.max_daily_loss_usd:
            return False, [f"Daily loss limit (${self.limits.max_daily_loss_usd:,.2f}) reached"]
        
        # Check consecutive losses
        if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
            return False, [f"Max consecutive losses ({self.limits.max_consecutive_losses}) reached"]
        
        # Check drawdown limit
        if self.state.current_drawdown_pct >= self.limits.max_total_drawdown_pct:
            return False, [f"Max drawdown ({self.limits.max_total_drawdown_pct:.1%}) reached"]
        
        # Check available margin
        if proposed_size > self.state.available_margin * 0.95:
            return False, ["Insufficient available margin"]
        
        return True, []
    
    def check_exit_necessity(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str,
        liquidation_buffer_long: float,
        liquidation_buffer_short: float,
        unrealized_pnl: float,
        entry_time: datetime,
        current_time: datetime
    ) -> Tuple[bool, str, float]:
        """
        Check if position must be exited due to risk conditions.
        
        Returns:
            (should_exit, reason, exit_confidence)
        """
        # Check liquidation risk
        if liquidation_buffer_long < self.limits.min_liquidation_buffer:
            return True, f"Long liquidation buffer critical: {liquidation_buffer_long:.2%}", 1.0
        
        if liquidation_buffer_short < self.limits.min_liquidation_buffer:
            return True, f"Short liquidation buffer critical: {liquidation_buffer_short:.2%}", 1.0
        
        # Check if adding to daily loss beyond limit
        potential_daily_pnl = self.state.daily_pnl + unrealized_pnl
        if potential_daily_pnl < -self.limits.max_daily_loss_usd:
            return True, f"Daily loss limit would be exceeded", 0.95
        
        return False, "", 0.0
    
    def update_portfolio_state(
        self,
        total_equity: float,
        available_margin: float,
        total_exposure: float,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Update portfolio state and check circuit breakers."""
        self.state.total_equity = total_equity
        self.state.available_margin = available_margin
        self.state.total_exposure = total_exposure
        
        # Update peak equity
        if total_equity > self.state.peak_equity:
            self.state.peak_equity = total_equity
        
        # Check circuit breakers
        self._check_circuit_breakers(timestamp)
    
    def _check_circuit_breakers(self, timestamp: Optional[datetime] = None) -> None:
        """Check and trigger circuit breakers if needed."""
        timestamp = timestamp or datetime.now()
        
        # Daily loss circuit breaker
        if self.state.daily_pnl < -self.limits.max_daily_loss_usd:
            if not self._circuit_breaker_triggered:
                logger.critical(
                    f"DAILY LOSS CIRCUIT BREAKER TRIGGERED at {timestamp}: "
                    f"Daily PnL ${self.state.daily_pnl:,.2f}"
                )
                self._circuit_breaker_triggered = True
        
        # Drawdown circuit breaker
        if self.state.current_drawdown_pct > self.limits.max_total_drawdown_pct:
            if not self._circuit_breaker_triggered:
                logger.critical(
                    f"DRAWDOWN CIRCUIT BREAKER TRIGGERED at {timestamp}: "
                    f"Drawdown {self.state.current_drawdown_pct:.2%}"
                )
                self._circuit_breaker_triggered = True
        
        # Consecutive losses circuit breaker
        if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
            if not self._circuit_breaker_triggered:
                logger.critical(
                    f"CONSECUTIVE LOSS CIRCUIT BREAKER TRIGGERED at {timestamp}: "
                    f"{self.state.consecutive_losses} consecutive losses"
                )
                self._circuit_breaker_triggered = True
    
    def record_trade(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str,
        entry_time: datetime,
        exit_time: datetime,
        size_usd: float,
        realized_pnl: float,
        funding_earned: float,
        exit_reason: str
    ) -> None:
        """Record completed trade for risk tracking."""
        trade = {
            'symbol': symbol,
            'long_exchange': long_exchange,
            'short_exchange': short_exchange,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'duration_hours': (exit_time - entry_time).total_seconds() / 3600,
            'size_usd': size_usd,
            'realized_pnl': realized_pnl,
            'funding_earned': funding_earned,
            'total_pnl': realized_pnl + funding_earned,
            'exit_reason': exit_reason
        }
        
        self._trade_history.append(trade)
        
        # Update consecutive losses
        total_pnl = realized_pnl + funding_earned
        if total_pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        
        # Update daily P&L
        self.state.daily_pnl += total_pnl
        self.state.total_pnl += total_pnl
        
        logger.info(
            f"Trade recorded: {symbol} PnL=${total_pnl:,.2f} "
            f"(Funding: ${funding_earned:,.2f})"
        )
    
    def get_risk_report(self) -> Dict:
        """Generate comprehensive risk report."""
        if not self._trade_history:
            win_rate = 0.0
            avg_trade_pnl = 0.0
            profit_factor = 0.0
        else:
            wins = [t for t in self._trade_history if t['total_pnl'] > 0]
            losses = [t for t in self._trade_history if t['total_pnl'] <= 0]
            
            win_rate = len(wins) / len(self._trade_history) if self._trade_history else 0
            avg_trade_pnl = np.mean([t['total_pnl'] for t in self._trade_history])
            
            gross_profit = sum(t['total_pnl'] for t in wins) if wins else 0
            gross_loss = abs(sum(t['total_pnl'] for t in losses)) if losses else 1
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        return {
            'portfolio': {
                'total_equity': self.state.total_equity,
                'peak_equity': self.state.peak_equity,
                'current_drawdown_pct': self.state.current_drawdown_pct,
                'daily_pnl': self.state.daily_pnl,
                'total_pnl': self.state.total_pnl,
                'consecutive_losses': self.state.consecutive_losses,
                'position_count': self.state.position_count
            },
            'limits': {
                'max_drawdown_pct': self.limits.max_total_drawdown_pct,
                'max_daily_loss_usd': self.limits.max_daily_loss_usd,
                'max_positions': self.limits.max_total_positions
            },
            'circuit_breaker': self._circuit_breaker_triggered,
            'performance': {
                'total_trades': len(self._trade_history),
                'win_rate': win_rate,
                'avg_trade_pnl': avg_trade_pnl,
                'profit_factor': profit_factor
            }
        }
    
    def reset_daily_stats(self) -> None:
        """Reset daily statistics (call at market open/close)."""
        today = datetime.now().strftime('%Y-%m-%d')
        self._daily_stats[today] = {
            'daily_pnl': self.state.daily_pnl,
            'trades': len([t for t in self._trade_history 
                          if t['exit_time'].strftime('%Y-%m-%d') == today])
        }
        self.state.daily_pnl = 0.0
        
        # Reset circuit breaker if conditions permit
        if (self.state.current_drawdown_pct < self.limits.max_total_drawdown_pct * 0.5 and
            self.state.consecutive_losses == 0):
            self._circuit_breaker_triggered = False
            logger.info("Circuit breaker reset")
    
    def calculate_liquidation_price(
        self,
        entry_price: float,
        leverage: float,
        is_long: bool,
        maintenance_margin_rate: float = 0.005
    ) -> float:
        """
        Calculate liquidation price for a position.
        
        Simplified formula: Liquidation = Entry ± (Entry / Leverage) * (1 - MM)
        """
        if is_long:
            liq_price = entry_price * (1 - 1/leverage + maintenance_margin_rate)
        else:
            liq_price = entry_price * (1 + 1/leverage - maintenance_margin_rate)
        
        return liq_price
    
    def calculate_liquidation_buffer(
        self,
        current_price: float,
        liquidation_price: float,
        is_long: bool
    ) -> float:
        """Calculate distance to liquidation as percentage."""
        if is_long:
            buffer = (current_price - liquidation_price) / current_price
        else:
            buffer = (liquidation_price - current_price) / current_price
        
        return max(0, buffer)
