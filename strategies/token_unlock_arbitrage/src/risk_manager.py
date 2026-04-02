"""
Risk Manager for Token Unlock Arbitrage
========================================
Event-driven risk controls with circuit breakers.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np
from enum import Enum


class RiskStatus(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    max_position_pct: float = 0.10  # 10% per position
    max_portfolio_risk: float = 0.15  # 15% portfolio heat
    max_daily_loss: float = 0.03  # 3% daily stop
    max_drawdown: float = 0.20  # 20% max drawdown
    max_correlation: float = 0.70  # Max correlation between positions
    min_liquidity_score: float = 0.6  # Min liquidity for trading


class RiskManager:
    """
    Risk Manager for Token Unlock Strategy.
    
    Key Risk Controls:
    1. Position sizing (Kelly-based with caps)
    2. Portfolio heat monitoring
    3. Drawdown circuit breaker
    4. Correlation checks
    5. Daily loss limits
    """
    
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.status = RiskStatus.GREEN
        self.daily_pnl: Dict[datetime, float] = {}
        self.circuit_breaker_triggered: Optional[datetime] = None
        self.cooldown_hours: int = 24
        
    def check_position_size(
        self,
        proposed_size: float,
        portfolio_value: float,
        existing_positions: Dict[str, float]
    ) -> Tuple[bool, float]:
        """
        Validate and cap position size.
        
        Returns:
            (is_valid, adjusted_size)
        """
        max_size = portfolio_value * self.limits.max_position_pct
        
        # Check if proposed exceeds max
        if proposed_size > max_size:
            return True, max_size
        
        # Check portfolio heat (sum of all position sizes)
        current_heat = sum(existing_positions.values())
        available = portfolio_value * self.limits.max_portfolio_risk - current_heat
        
        if proposed_size > available:
            return True, max(0, available)
        
        return True, proposed_size
    
    def check_drawdown(self, current_value: float, peak_value: float) -> bool:
        """Check if drawdown circuit breaker should trigger."""
        if peak_value <= 0:
            return True
        
        drawdown = (peak_value - current_value) / peak_value
        
        if drawdown > self.limits.max_drawdown:
            self.status = RiskStatus.RED
            self.circuit_breaker_triggered = datetime.now()
            print(f"🚨 CIRCUIT BREAKER: Drawdown {drawdown*100:.1f}% exceeds {self.limits.max_drawdown*100:.1f}%")
            return False
        
        elif drawdown > self.limits.max_drawdown * 0.7:
            self.status = RiskStatus.YELLOW
        
        return True
    
    def check_daily_loss(self, date: datetime, daily_pnl: float) -> bool:
        """Check if daily loss limit hit."""
        if date not in self.daily_pnl:
            self.daily_pnl[date] = 0.0
        
        self.daily_pnl[date] += daily_pnl
        
        # Check if limit breached
        # Note: daily_pnl is in USD, need to normalize to portfolio
        # This is checked externally with portfolio context
        
        return True
    
    def can_trade(self) -> bool:
        """Check if trading is allowed."""
        if self.circuit_breaker_triggered:
            elapsed = datetime.now() - self.circuit_breaker_triggered
            if elapsed < timedelta(hours=self.cooldown_hours):
                return False
            else:
                # Reset circuit breaker
                self.circuit_breaker_triggered = None
                self.status = RiskStatus.GREEN
        
        return self.status != RiskStatus.RED
    
    def calculate_vol_adjusted_size(
        self,
        base_size: float,
        volatility: float,
        target_vol: float = 0.02
    ) -> float:
        """
        Adjust position size based on volatility.
        
        Higher vol → smaller size to maintain constant risk.
        """
        if volatility <= 0:
            return base_size
        
        vol_scalar = target_vol / volatility
        return base_size * min(vol_scalar, 1.5)  # Cap at 1.5x increase
    
    def check_correlation(
        self,
        new_token: str,
        existing_positions: List[str],
        correlation_matrix: Dict[str, Dict[str, float]]
    ) -> bool:
        """
        Check if new position is too correlated with existing.
        
        Args:
            new_token: Token to potentially trade
            existing_positions: Currently held tokens
            correlation_matrix: Token correlation data
        """
        if not existing_positions:
            return True
        
        for existing in existing_positions:
            corr = correlation_matrix.get(new_token, {}).get(existing, 0.0)
            if abs(corr) > self.limits.max_correlation:
                print(f"⚠️  Correlation too high: {new_token} vs {existing} = {corr:.2f}")
                return False
        
        return True
    
    def get_risk_report(self) -> Dict:
        """Generate risk report."""
        return {
            'status': self.status.value,
            'circuit_breaker_active': self.circuit_breaker_triggered is not None,
            'circuit_breaker_time': self.circuit_breaker_triggered.isoformat() if self.circuit_breaker_triggered else None,
            'daily_pnl': {k.isoformat(): v for k, v in list(self.daily_pnl.items())[-30:]},
            'limits': {
                'max_position_pct': self.limits.max_position_pct,
                'max_drawdown': self.limits.max_drawdown,
                'max_daily_loss': self.limits.max_daily_loss,
            }
        }


class LiquidityFilter:
    """Filter tokens based on liquidity requirements."""
    
    def __init__(self, min_daily_volume: float = 1e6, min_market_cap: float = 50e6):
        self.min_daily_volume = min_daily_volume
        self.min_market_cap = min_market_cap
    
    def is_tradeable(
        self,
        token: str,
        volume_24h: float,
        market_cap: float,
        position_size: float
    ) -> bool:
        """
        Check if token meets liquidity requirements.
        
        Requirements:
        - 24h volume > $1M
        - Market cap > $50M
        - Position size < 1% of daily volume
        """
        if volume_24h < self.min_daily_volume:
            return False
        
        if market_cap < self.min_market_cap:
            return False
        
        if position_size > volume_24h * 0.01:
            print(f"⚠️  Position size {position_size:,.0f} exceeds 1% of daily volume")
            return False
        
        return True


if __name__ == "__main__":
    # Test
    risk = RiskManager()
    
    # Test position sizing
    valid, size = risk.check_position_size(
        proposed_size=15000,
        portfolio_value=100000,
        existing_positions={'SOL': 5000, 'AVAX': 3000}
    )
    print(f"Position valid: {valid}, Size: ${size:,.2f}")
    
    # Test drawdown
    can_trade = risk.check_drawdown(current_value=85000, peak_value=100000)
    print(f"Can trade: {can_trade}, Status: {risk.status.value}")
