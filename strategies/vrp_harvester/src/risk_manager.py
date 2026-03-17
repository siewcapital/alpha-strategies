"""
Risk Manager Module for VRP Harvester Strategy

Implements comprehensive risk management including:
- Position sizing (Kelly Criterion, fixed fractional)
- Portfolio-level risk controls
- Drawdown management
- Correlation monitoring
- Circuit breakers

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Current risk metrics snapshot"""
    timestamp: datetime
    portfolio_value: float
    gross_exposure: float
    net_exposure: float
    options_notional: float
    hedge_notional: float
    var_95: float
    expected_shortfall: float
    max_drawdown: float
    current_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float


class PositionSizer:
    """Position sizing calculators"""
    
    @staticmethod
    def kelly_criterion(win_rate: float, 
                       avg_win: float, 
                       avg_loss: float,
                       safety_factor: float = 0.5) -> float:
        """
        Calculate Kelly Criterion position size
        
        Kelly % = (Win Rate × Avg Win - Loss Rate × Avg Loss) / Avg Win
        
        Args:
            win_rate: Probability of winning (0-1)
            avg_win: Average winning trade return
            avg_loss: Average losing trade return (positive number)
            safety_factor: Fraction of full Kelly to use (0.5 = Half-Kelly)
            
        Returns:
            Optimal position size as fraction of capital
        """
        if avg_win <= 0 or avg_loss <= 0:
            return 0.01  # Minimum size if no data
        
        loss_rate = 1 - win_rate
        
        kelly = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
        kelly = max(0, min(0.5, kelly))  # Cap at 50%
        
        return kelly * safety_factor
    
    @staticmethod
    def fixed_fractional(account_value: float,
                        risk_per_trade: float,
                        max_loss_per_contract: float) -> int:
        """
        Calculate position size using fixed fractional method
        
        Args:
            account_value: Total account value
            risk_per_trade: Risk percentage per trade (e.g., 0.02 for 2%)
            max_loss_per_contract: Maximum loss per contract in dollars
            
        Returns:
            Number of contracts to trade
        """
        if max_loss_per_contract <= 0:
            return 0
        
        risk_amount = account_value * risk_per_trade
        contracts = int(risk_amount / max_loss_per_contract)
        
        return max(0, contracts)
    
    @staticmethod
    def volatility_scaled(account_value: float,
                         base_position: float,
                         current_volatility: float,
                         target_volatility: float = 0.50) -> float:
        """
        Scale position size inversely with volatility
        
        Args:
            account_value: Total account value
            base_position: Base position size
            current_volatility: Current volatility level
            target_volatility: Target volatility for scaling
            
        Returns:
            Adjusted position size
        """
        if current_volatility <= 0:
            return base_position
        
        vol_scalar = target_volatility / current_volatility
        scaled_position = base_position * vol_scalar
        
        return scaled_position
    
    @staticmethod
    def calculate_straddle_position_size(account_value: float,
                                        entry_premium: float,
                                        max_position_pct: float = 0.05,
                                        max_loss_multiple: float = 2.0) -> int:
        """
        Calculate number of straddle contracts based on risk limits
        
        Args:
            account_value: Total account value
            entry_premium: Premium collected per straddle
            max_position_pct: Max position as % of account
            max_loss_multiple: Max loss as multiple of premium (e.g., 2x)
            
        Returns:
            Number of straddles to sell
        """
        # Limit by max position size
        max_position_value = account_value * max_position_pct
        
        # Limit by max loss (stop loss × premium)
        max_loss_per_straddle = entry_premium * max_loss_multiple
        max_straddles_by_risk = int(account_value * 0.02 / max_loss_per_straddle)  # 2% risk per trade
        
        # Limit by position value
        max_straddles_by_value = int(max_position_value / entry_premium)
        
        # Take the minimum
        num_straddles = min(max_straddles_by_risk, max_straddles_by_value, 10)  # Cap at 10
        
        return max(1, num_straddles)


class RiskManager:
    """
    Comprehensive risk management for VRP Harvester strategy
    """
    
    def __init__(self, config: Dict):
        """
        Initialize risk manager
        
        Args:
            config: Risk management configuration
        """
        self.config = config
        
        # Position limits
        self.max_position_pct = config.get('max_position_pct', 0.05)
        self.max_portfolio_exposure = config.get('max_portfolio_exposure', 0.15)
        self.max_correlated_positions = config.get('max_correlated_positions', 3)
        
        # Drawdown controls
        self.max_drawdown_pct = config.get('max_drawdown_pct', 0.10)
        self.daily_loss_limit = config.get('daily_loss_limit', 0.02)
        self.weekly_loss_limit = config.get('weekly_loss_limit', 0.05)
        
        # Circuit breakers
        self.consecutive_loss_limit = config.get('consecutive_loss_limit', 3)
        self.vix_upper_limit = config.get('vix_upper_limit', 80)
        self.correlation_spike_threshold = config.get('correlation_spike_threshold', 0.90)
        
        # Tracking
        self.peak_portfolio_value = 0
        self.current_drawdown = 0
        self.daily_pnl = 0
        self.weekly_pnl = 0
        self.consecutive_losses = 0
        self.last_trade_date = datetime.now()
        self.trade_history: List[Dict] = []
        
        # State
        self.trading_halted = False
        self.halt_reason = None
        self.halt_time = None
        
        self.position_sizer = PositionSizer()
        
        logger.info("Risk Manager initialized")
    
    def can_enter_position(self,
                          account_value: float,
                          current_positions: int,
                          position_correlations: Dict[str, float],
                          dvol_index: float) -> Tuple[bool, str]:
        """
        Check if new position can be entered
        
        Returns:
            Tuple of (allowed, reason)
        """
        # Check if trading halted
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"
        
        # Check position limit
        if current_positions >= self.max_correlated_positions:
            return False, f"Max positions reached: {current_positions}"
        
        # Check portfolio exposure
        gross_exposure = self._calculate_gross_exposure(position_correlations)
        if gross_exposure > self.max_portfolio_exposure:
            return False, f"Max exposure reached: {gross_exposure:.1%}"
        
        # Check DVOL/VIX filter
        if dvol_index > self.vix_upper_limit:
            return False, f"DVOL too high: {dvol_index:.1f} > {self.vix_upper_limit}"
        
        # Check daily loss limit
        if self.daily_pnl < -account_value * self.daily_loss_limit:
            return False, f"Daily loss limit hit: ${self.daily_pnl:,.0f}"
        
        # Check consecutive losses
        if self.consecutive_losses >= self.consecutive_loss_limit:
            return False, f"Consecutive losses: {self.consecutive_losses}"
        
        return True, "OK"
    
    def check_drawdown(self, current_portfolio_value: float) -> Tuple[bool, str]:
        """
        Check drawdown conditions and update state
        
        Returns:
            Tuple of (halted, reason)
        """
        # Update peak
        if current_portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = current_portfolio_value
        
        # Calculate drawdown
        if self.peak_portfolio_value > 0:
            self.current_drawdown = (current_portfolio_value - self.peak_portfolio_value) / self.peak_portfolio_value
        
        # Check max drawdown
        if self.current_drawdown <= -self.max_drawdown_pct:
            self._halt_trading("MAX_DRAWDOWN", 
                              f"Max drawdown reached: {self.current_drawdown:.1%}")
            return True, self.halt_reason
        
        return False, "OK"
    
    def record_trade(self, trade_result: Dict):
        """
        Record trade result for risk tracking
        """
        pnl = trade_result.get('pnl', 0)
        
        self.trade_history.append({
            'timestamp': datetime.now(),
            'pnl': pnl,
            'asset': trade_result.get('asset'),
            'exit_reason': trade_result.get('exit_reason')
        })
        
        # Update consecutive losses
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        # Update daily/weekly P&L
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        
        logger.info(f"Trade recorded: PnL=${pnl:,.2f}, Consecutive losses: {self.consecutive_losses}")
    
    def calculate_position_size(self,
                               account_value: float,
                               entry_premium: float,
                               win_rate: float = 0.65,
                               avg_win: float = 0.30,
                               avg_loss: float = 0.60) -> int:
        """
        Calculate optimal position size using multiple methods
        
        Returns:
            Number of straddles to sell
        """
        # Method 1: Kelly Criterion
        kelly_size = self.position_sizer.kelly_criterion(
            win_rate, avg_win, avg_loss, safety_factor=0.5
        )
        
        # Method 2: Fixed Fractional
        fixed_size = self.position_sizer.fixed_fractional(
            account_value, 
            risk_per_trade=self.max_position_pct,
            max_loss_per_contract=entry_premium * 2.0
        )
        
        # Method 3: Conservative straddle sizing
        conservative_size = self.position_sizer.calculate_straddle_position_size(
            account_value, entry_premium, self.max_position_pct
        )
        
        # Take the minimum of all methods
        final_size = min(int(kelly_size * account_value / entry_premium), 
                        fixed_size, 
                        conservative_size)
        
        return max(1, final_size)
    
    def get_risk_metrics(self, portfolio_value: float) -> RiskMetrics:
        """
        Calculate current risk metrics
        """
        # Calculate VaR (simplified historical method)
        if len(self.trade_history) >= 20:
            pnls = [t['pnl'] for t in self.trade_history[-100:]]
            var_95 = np.percentile(pnls, 5)
            es = np.mean([p for p in pnls if p <= var_95]) if any(p <= var_95 for p in pnls) else var_95
        else:
            var_95 = -portfolio_value * 0.02
            es = -portfolio_value * 0.03
        
        # Calculate win rate
        if self.trade_history:
            wins = sum(1 for t in self.trade_history if t['pnl'] > 0)
            win_rate = wins / len(self.trade_history)
        else:
            win_rate = 0.5
        
        # Calculate profit factor
        if self.trade_history:
            gross_profit = sum(t['pnl'] for t in self.trade_history if t['pnl'] > 0)
            gross_loss = abs(sum(t['pnl'] for t in self.trade_history if t['pnl'] < 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 1.0
        else:
            profit_factor = 1.0
        
        return RiskMetrics(
            timestamp=datetime.now(),
            portfolio_value=portfolio_value,
            gross_exposure=self._calculate_gross_exposure({}),
            net_exposure=0,  # Should be delta-neutral
            options_notional=0,
            hedge_notional=0,
            var_95=var_95,
            expected_shortfall=es,
            max_drawdown=self.max_drawdown_pct,
            current_drawdown=self.current_drawdown,
            sharpe_ratio=0,  # Requires more data
            win_rate=win_rate,
            profit_factor=profit_factor
        )
    
    def reset_daily_stats(self):
        """Reset daily statistics (call at day end)"""
        self.daily_pnl = 0
        logger.info("Daily stats reset")
    
    def reset_weekly_stats(self):
        """Reset weekly statistics (call at week end)"""
        self.weekly_pnl = 0
        logger.info("Weekly stats reset")
    
    def resume_trading(self) -> bool:
        """
        Attempt to resume trading after halt
        
        Returns:
            True if trading resumed
        """
        if not self.trading_halted:
            return True
        
        # Check if conditions improved
        if self.halt_reason == "MAX_DRAWDOWN":
            # Require recovery of 50% of drawdown
            if self.current_drawdown >= -self.max_drawdown_pct * 0.5:
                self.trading_halted = False
                self.halt_reason = None
                logger.info("Trading resumed after drawdown recovery")
                return True
        
        elif self.halt_reason == "CONSECUTIVE_LOSSES":
            # Require a winning trade
            if self.consecutive_losses == 0:
                self.trading_halted = False
                self.halt_reason = None
                logger.info("Trading resumed after winning trade")
                return True
        
        return False
    
    def _calculate_gross_exposure(self, position_correlations: Dict[str, float]) -> float:
        """Calculate gross portfolio exposure"""
        # Simplified: count positions × weight
        num_positions = len(position_correlations)
        return num_positions * self.max_position_pct
    
    def _halt_trading(self, reason_code: str, reason_msg: str):
        """Halt trading"""
        self.trading_halted = True
        self.halt_reason = reason_msg
        self.halt_time = datetime.now()
        logger.warning(f"TRADING HALTED: {reason_msg}")
    
    def get_status(self) -> Dict:
        """Get current risk manager status"""
        return {
            'trading_halted': self.trading_halted,
            'halt_reason': self.halt_reason,
            'halt_time': self.halt_time,
            'current_drawdown': self.current_drawdown,
            'consecutive_losses': self.consecutive_losses,
            'daily_pnl': self.daily_pnl,
            'weekly_pnl': self.weekly_pnl,
            'total_trades': len(self.trade_history),
            'peak_portfolio_value': self.peak_portfolio_value
        }
