"""
Risk Manager for Funding Rate Arbitrage

Handles position sizing, risk limits, and drawdown protection.

Author: ATLAS (Siew's Capital)
Date: 2026-03-24
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from strategy import Position

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    max_portfolio_risk: float = 0.10  # Max 10% portfolio at risk
    max_position_size: float = 0.15  # Max 15% in single position
    max_leverage: float = 3.0  # Max 3x leverage
    max_drawdown: float = 0.05  # Max 5% drawdown before stop
    min_margin_ratio: float = 0.30  # Min 30% margin buffer
    max_correlation: float = 0.70  # Max correlation between positions


@dataclass
class RiskMetrics:
    """Current risk metrics."""
    portfolio_value: float
    positions_value: float
    available_capital: float
    current_drawdown: float
    margin_utilization: float
    largest_position: float
    correlation_exposure: float


class RiskManager:
    """
    Risk management for funding rate arbitrage strategy.
    
    Responsibilities:
    - Position sizing
    - Risk limit enforcement
    - Drawdown monitoring
    - Correlation checks
    """
    
    def __init__(self, config: dict, initial_capital: float):
        """
        Initialize risk manager.
        
        Args:
            config: Configuration dict
            initial_capital: Starting capital
        """
        self.config = config
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        self.risk_limits = RiskLimits(
            max_portfolio_risk=config.get("risk", {}).get("max_drawdown_stop", 0.10),
            max_position_size=config.get("risk", {}).get("max_single_asset_exposure", 0.15),
            max_leverage=config.get("strategy", {}).get("max_leverage", 3.0),
            max_drawdown=config.get("risk", {}).get("max_drawdown_stop", 0.05),
            min_margin_ratio=config.get("risk", {}).get("min_margin_buffer", 0.30),
            max_correlation=config.get("risk", {}).get("correlation_threshold", 0.70)
        )
        
        # Trade history for metrics
        self.trade_history: List[dict] = []
        
        logger.info(f"Risk Manager initialized with capital: ${initial_capital:,.2f}")
    
    def calculate_position_size(
        self,
        opportunity_return: float,
        volatility: float = 0.02,
        confidence: float = 0.95
    ) -> float:
        """
        Calculate optimal position size using Kelly Criterion.
        
        Args:
            opportunity_return: Expected annual return (decimal)
            volatility: Expected volatility (decimal)
            confidence: Confidence level for sizing
            
        Returns:
            Optimal position size as fraction of capital
        """
        # Kelly Criterion: f* = (bp - q) / b
        # Where b = odds, p = win probability, q = loss probability
        
        # Simplified: use expected return / volatility as edge proxy
        if volatility == 0:
            return 0
        
        edge = opportunity_return / volatility
        
        # Convert to position size
        kelly_size = edge / self.risk_limits.max_leverage
        
        # Apply fractional Kelly (more conservative)
        fractional_kelly = 0.25  # Use 25% of full Kelly
        size = kelly_size * fractional_kelly
        
        # Apply limits
        size = min(size, self.risk_limits.max_position_size)
        size = max(size, 0.01)  # Min 1% of portfolio
        
        return size
    
    def check_risk_limits(
        self,
        positions: Dict[str, Position],
        new_position_size: float,
        symbol: str
    ) -> tuple[bool, str]:
        """
        Check if position meets risk limits.
        
        Args:
            positions: Current positions
            new_position_size: Size of new position
            symbol: Trading symbol
            
        Returns:
            Tuple of (allowed, reason)
        """
        # Check max positions
        max_positions = self.config.get("strategy", {}).get("max_concurrent_positions", 5)
        if len(positions) >= max_positions:
            return False, f"Max positions ({max_positions}) reached"
        
        # Check single position size
        if new_position_size > self.risk_limits.max_position_size:
            return False, f"Position size {new_position_size:.2%} exceeds max {self.risk_limits.max_position_size:.2%}"
        
        # Check total exposure
        current_exposure = sum(p.margin_used for p in positions.values()) / self.current_capital
        total_exposure = current_exposure + new_position_size
        
        if total_exposure > self.risk_limits.max_portfolio_risk:
            return False, f"Total exposure {total_exposure:.2%} exceeds max {self.risk_limits.max_portfolio_risk:.2%}"
        
        # Check correlation (simplified - would need real correlation matrix)
        # For now, check if we already have position in correlated asset class
        # (e.g., multiple DeFi tokens)
        
        return True, "OK"
    
    def check_drawdown(self) -> tuple[bool, str]:
        """
        Check if portfolio is in drawdown.
        
        Returns:
            Tuple of (in_drawdown, message)
        """
        if self.current_capital < self.peak_capital:
            drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
            
            if drawdown > self.risk_limits.max_drawdown:
                return True, f"Max drawdown exceeded: {drawdown:.2%} > {self.risk_limits.max_drawdown:.2%}"
        
        return False, "OK"
    
    def update_capital(self, pnl: float):
        """
        Update capital after PnL realization.
        
        Args:
            pnl: Profit or loss
        """
        self.current_capital += pnl
        
        # Update peak
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
    
    def get_risk_metrics(
        self,
        positions: Dict[str, Position]
    ) -> RiskMetrics:
        """
        Calculate current risk metrics.
        
        Args:
            positions: Current positions
            
        Returns:
            RiskMetrics object
        """
        positions_value = sum(
            p.size * p.entry_long_price for p in positions.values()
        )
        
        available = self.current_capital - sum(
            p.margin_used for p in positions.values()
        )
        
        drawdown = (
            (self.peak_capital - self.current_capital) / self.peak_capital
            if self.peak_capital > 0 else 0
        )
        
        margin_used = sum(p.margin_used for p in positions.values())
        margin_utilization = margin_used / self.current_capital if self.current_capital > 0 else 0
        
        largest = max((p.margin_used for p in positions.values()), default=0)
        largest_pct = largest / self.current_capital if self.current_capital > 0 else 0
        
        # Simplified correlation exposure
        # In production, would calculate actual correlation matrix
        correlation_exposure = len(positions) / self.config.get("strategy", {}).get("max_concurrent_positions", 5)
        
        return RiskMetrics(
            portfolio_value=self.current_capital,
            positions_value=positions_value,
            available_capital=available,
            current_drawdown=drawdown,
            margin_utilization=margin_utilization,
            largest_position=largest_pct,
            correlation_exposure=correlation_exposure
        )
    
    def should_emergency_exit(
        self,
        positions: Dict[str, Position]
    ) -> tuple[bool, List[str]]:
        """
        Check if emergency exit is needed.
        
        Args:
            positions: Current positions
            
        Returns:
            Tuple of (emergency_exit, symbols_to_close)
        """
        # Check drawdown
        in_dd, msg = self.check_drawdown()
        if in_dd:
            logger.warning(f"Emergency exit triggered: {msg}")
            return True, list(positions.keys())
        
        # Check margin utilization
        metrics = self.get_risk_metrics(positions)
        if metrics.margin_utilization > 0.90:
            logger.warning("Emergency exit: Margin utilization > 90%")
            return True, list(positions.keys())
        
        return False, []
    
    def record_trade(self, trade: dict):
        """
        Record trade for analytics.
        
        Args:
            trade: Trade details
        """
        trade["timestamp"] = datetime.now()
        self.trade_history.append(trade)
    
    def get_performance_stats(self) -> dict:
        """
        Get performance statistics.
        
        Returns:
            Dict of performance metrics
        """
        if not self.trade_history:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "avg_profit": 0,
                "avg_loss": 0
            }
        
        wins = [t["pnl"] for t in self.trade_history if t["pnl"] > 0]
        losses = [t["pnl"] for t in self.trade_history if t["pnl"] <= 0]
        
        return {
            "total_trades": len(self.trade_history),
            "win_rate": len(wins) / len(self.trade_history) if self.trade_history else 0,
            "avg_profit": np.mean(wins) if wins else 0,
            "avg_loss": np.mean(losses) if losses else 0,
            "total_pnl": sum(t["pnl"] for t in self.trade_history),
            "current_drawdown": (self.peak_capital - self.current_capital) / self.peak_capital if self.peak_capital > 0 else 0
        }
    
    def reset(self):
        """Reset risk manager state."""
        self.current_capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.trade_history = []
        logger.info("Risk Manager state reset")
