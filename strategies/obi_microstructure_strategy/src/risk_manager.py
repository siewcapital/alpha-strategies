"""
Risk Manager module for Order Book Imbalance strategy.

Implements position sizing, drawdown controls, and risk limits.

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from collections import deque
import logging

logger = logging.getLogger(__name__)


class RiskStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    HALTED = "halted"


@dataclass
class RiskMetrics:
    """Current risk metrics."""
    daily_pnl: float
    daily_drawdown: float
    max_drawdown: float
    current_exposure: float
    consecutive_losses: int
    trades_today: int
    volatility_regime: str
    status: RiskStatus


@dataclass
class PositionSizing:
    """Position sizing parameters."""
    size_pct: float  # Position size as % of portfolio
    leverage: float
    max_position_value: float
    reason: str


class RiskManager:
    """
    Comprehensive risk management for OBI strategy.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize risk manager.
        
        Args:
            config: Risk configuration
        """
        self.config = config
        
        # Limits
        self.daily_loss_limit = config.get('daily_loss_limit', 0.01)  # 1%
        self.hourly_loss_limit = config.get('hourly_loss_limit', 0.005)  # 0.5%
        self.max_drawdown_limit = config.get('max_drawdown_limit', 0.04)  # 4%
        self.max_consecutive_losses = config.get('max_consecutive_losses', 5)
        self.max_daily_trades = config.get('max_daily_trades', 200)
        
        # Position sizing
        self.base_position_pct = config.get('base_position_pct', 0.01)  # 1%
        self.max_position_pct = config.get('max_position_pct', 0.015)  # 1.5%
        self.volatility_scale_factor = config.get('volatility_scale_factor', 0.5)
        
        # Cooldowns
        self.cooldown_after_loss_seconds = config.get('cooldown_after_loss_seconds', 60)
        self.cooldown_after_limit_seconds = config.get('cooldown_after_limit_seconds', 300)
        
        # State tracking
        self.daily_pnl = 0.0
        self.hourly_pnl = 0.0
        self.peak_equity = 0.0
        self.current_drawdown = 0.0
        self.max_drawdown = 0.0
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.trades_today = 0
        self.last_trade_time: Optional[pd.Timestamp] = None
        self.cooldown_until: Optional[pd.Timestamp] = None
        
        # Trade history
        self.trade_history: deque = deque(maxlen=1000)
        self.hourly_trades: deque = deque(maxlen=100)
        
        # Status
        self.status = RiskStatus.OK
        self.halt_reason: Optional[str] = None
        
    def update_equity(self, current_equity: float, timestamp: pd.Timestamp):
        """
        Update equity and calculate drawdown.
        
        Args:
            current_equity: Current portfolio value
            timestamp: Current timestamp
        """
        if self.peak_equity == 0:
            self.peak_equity = current_equity
        
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        self.current_drawdown = (self.peak_equity - current_equity) / self.peak_equity
        self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
        
        # Check drawdown limit
        if self.current_drawdown >= self.max_drawdown_limit:
            self._halt("Max drawdown limit reached", timestamp)
    
    def record_trade(self, pnl: float, timestamp: pd.Timestamp):
        """
        Record trade P&L and update risk metrics.
        
        Args:
            pnl: Trade P&L (positive = win, negative = loss)
            timestamp: Trade timestamp
        """
        self.trade_history.append({'pnl': pnl, 'timestamp': timestamp})
        self.hourly_trades.append({'pnl': pnl, 'timestamp': timestamp})
        self.trades_today += 1
        
        self.daily_pnl += pnl
        self.hourly_pnl += pnl
        self.last_trade_time = timestamp
        
        # Update consecutive counters
        if pnl > 0:
            self.consecutive_losses = 0
            self.consecutive_wins += 1
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            
            # Check consecutive loss limit
            if self.consecutive_losses >= self.max_consecutive_losses:
                self._enter_cooldown(
                    f"Max consecutive losses ({self.max_consecutive_losses})",
                    timestamp,
                    self.cooldown_after_loss_seconds
                )
        
        # Check daily loss limit
        if self.daily_pnl <= -self.daily_loss_limit:
            self._halt("Daily loss limit reached", timestamp)
        
        # Check hourly loss limit
        if self.hourly_pnl <= -self.hourly_loss_limit:
            self._enter_cooldown(
                "Hourly loss limit reached",
                timestamp,
                self.cooldown_after_limit_seconds
            )
        
        # Check max daily trades
        if self.trades_today >= self.max_daily_trades:
            self._halt("Max daily trades reached", timestamp)
    
    def _enter_cooldown(self, reason: str, timestamp: pd.Timestamp, 
                       duration_seconds: int):
        """
        Enter cooldown period.
        
        Args:
            reason: Reason for cooldown
            timestamp: Current timestamp
            duration_seconds: Cooldown duration
        """
        self.cooldown_until = timestamp + pd.Timedelta(seconds=duration_seconds)
        self.status = RiskStatus.WARNING
        logger.warning(f"Risk cooldown: {reason} until {self.cooldown_until}")
    
    def _halt(self, reason: str, timestamp: pd.Timestamp):
        """
        Halt trading.
        
        Args:
            reason: Reason for halt
            timestamp: Current timestamp
        """
        self.status = RiskStatus.HALTED
        self.halt_reason = reason
        self.cooldown_until = timestamp + pd.Timedelta(
            seconds=self.cooldown_after_limit_seconds * 2
        )
        logger.error(f"Trading HALTED: {reason}")
    
    def reset_daily(self, timestamp: pd.Timestamp):
        """
        Reset daily counters.
        
        Args:
            timestamp: Current timestamp (to check if new day)
        """
        if self.trade_history:
            last_trade_date = self.trade_history[-1]['timestamp'].date()
            current_date = timestamp.date()
            
            if current_date != last_trade_date:
                self.daily_pnl = 0.0
                self.trades_today = 0
                self.status = RiskStatus.OK if self.status != RiskStatus.HALTED else self.status
                logger.info("Daily counters reset")
    
    def reset_hourly(self, timestamp: pd.Timestamp):
        """
        Reset hourly P&L.
        
        Args:
            timestamp: Current timestamp
        """
        # Filter to trades in last hour
        one_hour_ago = timestamp - pd.Timedelta(hours=1)
        recent_trades = [t for t in self.hourly_trades 
                        if t['timestamp'] > one_hour_ago]
        self.hourly_pnl = sum(t['pnl'] for t in recent_trades)
    
    def can_trade(self, timestamp: pd.Timestamp) -> Tuple[bool, str]:
        """
        Check if trading is allowed.
        
        Args:
            timestamp: Current timestamp
            
        Returns:
            Tuple of (can_trade, reason)
        """
        # Reset daily/hourly if needed
        self.reset_daily(timestamp)
        self.reset_hourly(timestamp)
        
        # Check cooldown
        if self.cooldown_until and timestamp < self.cooldown_until:
            remaining = (self.cooldown_until - timestamp).total_seconds()
            return False, f"In cooldown: {remaining:.0f}s remaining"
        
        # Check status
        if self.status == RiskStatus.HALTED:
            return False, f"Trading halted: {self.halt_reason}"
        
        return True, "OK"
    
    def calculate_position_size(self, 
                               confidence: float,
                               obi_magnitude: float,
                               current_volatility: float,
                               avg_volatility: float) -> PositionSizing:
        """
        Calculate position size based on risk parameters.
        
        Args:
            confidence: Signal confidence [0, 1]
            obi_magnitude: Absolute OBI value [0, 1]
            current_volatility: Current realized volatility
            avg_volatility: Average realized volatility
            
        Returns:
            Position sizing parameters
        """
        # Base size
        size = self.base_position_pct
        
        # Scale by confidence
        size *= (0.5 + 0.5 * confidence)  # 0.5x to 1x based on confidence
        
        # Scale by OBI magnitude (stronger signals = larger size)
        if obi_magnitude > 0.6:
            size *= 1.5  # Increase for very strong imbalances
            reason = "Strong OBI magnitude (>0.6)"
        else:
            reason = "Base position size"
        
        # Volatility adjustment
        if current_volatility > avg_volatility * 2:
            size *= self.volatility_scale_factor
            reason += f", reduced due to high volatility ({current_volatility:.2f}x)"
        
        # Apply limits
        size = min(size, self.max_position_pct)
        
        return PositionSizing(
            size_pct=size,
            leverage=1.0,
            max_position_value=size,  # As fraction of portfolio
            reason=reason
        )
    
    def get_risk_metrics(self) -> RiskMetrics:
        """
        Get current risk metrics.
        
        Returns:
            RiskMetrics object
        """
        # Determine volatility regime
        if len(self.trade_history) >= 20:
            recent_pnls = [t['pnl'] for t in list(self.trade_history)[-20:]]
            vol = np.std(recent_pnls) * np.sqrt(252)  # Annualized
            
            if vol < 0.1:
                vol_regime = "low"
            elif vol < 0.25:
                vol_regime = "normal"
            else:
                vol_regime = "high"
        else:
            vol_regime = "unknown"
        
        return RiskMetrics(
            daily_pnl=self.daily_pnl,
            daily_drawdown=self.current_drawdown,
            max_drawdown=self.max_drawdown,
            current_exposure=0.0,  # Updated by position manager
            consecutive_losses=self.consecutive_losses,
            trades_today=self.trades_today,
            volatility_regime=vol_regime,
            status=self.status
        )
    
    def get_trade_statistics(self) -> Dict[str, Any]:
        """
        Get trade statistics.
        
        Returns:
            Dictionary of statistics
        """
        if not self.trade_history:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'avg_pnl': 0.0,
                'sharpe': 0.0
            }
        
        trades = list(self.trade_history)
        pnls = [t['pnl'] for t in trades]
        
        wins = sum(1 for p in pnls if p > 0)
        total = len(pnls)
        
        win_rate = wins / total if total > 0 else 0.0
        avg_pnl = np.mean(pnls)
        
        # Calculate Sharpe (assuming daily frequency adjustment needed)
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = avg_pnl / np.std(pnls) * np.sqrt(252)
        else:
            sharpe = 0.0
        
        return {
            'total_trades': total,
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'sharpe': sharpe,
            'max_consecutive_losses': self.consecutive_losses,
            'max_consecutive_wins': self.consecutive_wins,
            'daily_pnl': self.daily_pnl
        }
