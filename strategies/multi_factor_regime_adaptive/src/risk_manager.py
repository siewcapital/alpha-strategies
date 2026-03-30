"""
risk_manager.py - Position sizing and risk management for multi-factor strategy.

Provides:
- Kelly criterion position sizing
- Volatility-adjusted position sizing
- Drawdown-based risk reduction
- Circuit breakers for extreme events
- Correlation-based portfolio concentration checks
"""

import numpy as np
from typing import Dict, List, Optional, Tuple


class RiskManager:
    """
    Risk manager for multi-factor regime-adaptive strategy.
    
    Features:
    - Kelly fraction-based position sizing
    - Max drawdown circuit breaker
    - Max position concentration limits
    - Max leverage limits
    - Volatility-adjusted sizing
    """
    
    def __init__(
        self,
        max_kelly_fraction: float = 0.25,  # Cap Kelly at 25% (conservative)
        max_position_pct: float = 0.20,     # Max 20% in one asset
        max_leverage: float = 3.0,          # Max 3x leverage
        max_portfolio_vol: float = 0.30,    # Max 30% annualized portfolio vol
        max_drawdown_cutoff: float = 0.20,  # Stop trading at 20% drawdown
        vol_lookback: int = 20,             # Days for vol calculation
        correlation_threshold: float = 0.7  # Max correlation between positions
    ):
        self.max_kelly_fraction = max_kelly_fraction
        self.max_position_pct = max_position_pct
        self.max_leverage = max_leverage
        self.max_portfolio_vol = max_portfolio_vol
        self.max_drawdown_cutoff = max_drawdown_cutoff
        self.vol_lookback = vol_lookback
        self.correlation_threshold = correlation_threshold
        
        # State
        self.current_capital = 1.0  # Normalized to 1.0
        self.peak_capital = 1.0
        self.current_drawdown = 0.0
        
        # Track positions for correlation check
        self.position_returns: Dict[str, List[float]] = {}
        
        # Circuit breaker state
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
    
    def update_capital(self, new_capital: float) -> None:
        """
        Update capital tracking for drawdown calculation.
        
        Args:
            new_capital: New total portfolio value (normalized)
        """
        self.current_capital = new_capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital
        
        self.current_drawdown = (self.peak_capital - new_capital) / self.peak_capital
        
        # Check circuit breaker
        if self.current_drawdown > self.max_drawdown_cutoff:
            self.circuit_breaker_active = True
            self.circuit_breaker_reason = f"Max drawdown {self.current_drawdown:.1%} exceeded cutoff"
    
    def reset_circuit_breaker(self) -> None:
        """Reset circuit breaker if drawdown recovers."""
        if self.current_drawdown < self.max_drawdown_cutoff * 0.5:
            self.circuit_breaker_active = False
            self.circuit_breaker_reason = ""
    
    def is_trading_allowed(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed (no circuit breakers active).
        
        Returns:
            (allowed, reason)
        """
        if self.circuit_breaker_active:
            return False, self.circuit_breaker_reason
        return True, ""
    
    def kelly_fraction(self, win_rate: float, avg_win: float, 
                       avg_loss: float) -> float:
        """
        Calculate Kelly criterion position size.
        
        Kelly % = W - (1-W)/R
        where W = win rate, R = win/loss ratio
        
        Capped at max_kelly_fraction for safety.
        
        Args:
            win_rate: Historical win rate (0 to 1)
            avg_win: Average winning return (positive)
            avg_loss: Average losing return (positive)
            
        Returns:
            Kelly fraction (0 to 1)
        """
        if avg_loss == 0 or win_rate == 0:
            return 0.0
        
        win_loss_ratio = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / win_loss_ratio)
        
        # Cap Kelly
        kelly = min(kelly, self.max_kelly_fraction)
        kelly = max(kelly, 0.0)
        
        return kelly
    
    def volatility_adjusted_size(self, target_vol: float,
                                  realized_vol: float,
                                  base_size: float) -> float:
        """
        Scale position size inversely to volatility.
        
        Higher vol = smaller position to keep portfolio vol constant.
        
        Args:
            target_vol: Target annualized volatility
            realized_vol: Current realized volatility
            base_size: Base position size
            
        Returns:
            Adjusted position size
        """
        if realized_vol == 0:
            return base_size
        
        # Volatility targeting: vol_scaled_size = base * (target_vol / realized_vol)
        vol_ratio = target_vol / realized_vol
        
        # Cap the ratio to prevent enormous positions in low-vol regimes
        vol_ratio = min(vol_ratio, 3.0)
        
        return base_size * vol_ratio
    
    def max_position_size(self, capital: float, price: float) -> float:
        """
        Calculate maximum position size based on portfolio concentration rules.
        
        Args:
            capital: Available capital
            price: Asset price
            
        Returns:
            Maximum number of units to buy
        """
        max_dollar_position = capital * self.max_position_pct
        return max_dollar_position / price if price > 0 else 0
    
    def check_correlation(self, new_asset_returns: np.ndarray,
                          existing_returns: Dict[str, np.ndarray]) -> float:
        """
        Check if new asset is too correlated with existing positions.
        
        Returns:
            Maximum correlation with any existing position (0 to 1)
        """
        if not existing_returns:
            return 0.0
        
        max_corr = 0.0
        for asset_name, returns in existing_returns.items():
            # Align lengths
            min_len = min(len(new_asset_returns), len(returns))
            if min_len < 10:  # Need at least 10 data points
                continue
            
            corr = np.corrcoef(new_asset_returns[-min_len:], 
                               returns[-min_len:])[0, 1]
            if not np.isnan(corr):
                max_corr = max(max_corr, abs(corr))
        
        return max_corr
    
    def calculate_position_size(
        self,
        capital: float,
        price: float,
        signal_strength: float,  # Composite score magnitude (0 to 1)
        direction: int,         # +1 for long, -1 for short
        realized_vol: float,
        historical_win_rate: float = 0.55,
        historical_avg_win: float = 0.02,
        historical_avg_loss: float = 0.01
    ) -> Tuple[float, Dict[str, float]]:
        """
        Calculate final position size with all risk controls.
        
        Args:
            capital: Available capital
            price: Current price
            signal_strength: Confidence in signal (0 to 1)
            direction: +1 long, -1 short
            realized_vol: Current realized volatility
            historical_win_rate: From backtest
            historical_avg_win: From backtest
            historical_avg_loss: From backtest
            
        Returns:
            (position_size_in_dollars, sizing_breakdown)
        """
        breakdown = {}
        
        # Check circuit breaker
        allowed, reason = self.is_trading_allowed()
        if not allowed:
            return 0.0, {"circuit_breaker": 0.0, "reason": reason}
        
        # 1. Kelly-based size
        kelly = self.kelly_fraction(historical_win_rate, 
                                    historical_avg_win, 
                                    historical_avg_loss)
        kelly_position = capital * kelly
        breakdown["kelly"] = kelly
        
        # 2. Signal strength adjustment
        # Only full Kelly when signal is strong; reduce for weak signals
        signal_adjusted = kelly_position * signal_strength
        breakdown["signal_strength"] = signal_strength
        
        # 3. Volatility adjustment
        target_vol = self.max_portfolio_vol / np.sqrt(252)  # Daily target
        vol_adjusted = self.volatility_adjusted_size(
            target_vol, realized_vol, signal_adjusted
        )
        breakdown["vol_adjustment"] = vol_adjusted / signal_adjusted if signal_adjusted > 0 else 0
        
        # 4. Max position concentration
        max_position = self.max_position_size(capital, price)
        max_position_value = max_position * price
        breakdown["max_concentration"] = max_position_value
        
        # 5. Apply leverage cap
        leverage_adjusted = min(vol_adjusted, capital * self.max_leverage)
        breakdown["leverage_capped"] = leverage_adjusted / vol_adjusted if vol_adjusted > 0 else 0
        
        # 6. Final size is the minimum of all constraints
        final_size = min(
            vol_adjusted,
            max_position_value,
            leverage_adjusted
        )
        
        breakdown["final"] = final_size
        
        return final_size * direction, breakdown
    
    def record_trade_result(self, asset: str, trade_return: float) -> None:
        """
        Record a trade result for ongoing risk calculations.
        
        Args:
            asset: Asset name
            trade_return: Return from the trade (positive = win)
        """
        if asset not in self.position_returns:
            self.position_returns[asset] = []
        self.position_returns[asset].append(trade_return)
        
        # Keep only last 100 trades per asset
        if len(self.position_returns[asset]) > 100:
            self.position_returns[asset] = self.position_returns[asset][-100:]
    
    def get_portfolio_metrics(self) -> Dict[str, float]:
        """
        Get current portfolio risk metrics.
        
        Returns:
            Dictionary of risk metrics
        """
        return {
            "current_capital": self.current_capital,
            "peak_capital": self.peak_capital,
            "current_drawdown": self.current_drawdown,
            "circuit_breaker_active": float(self.circuit_breaker_active),
            "num_assets_tracked": len(self.position_returns)
        }
    
    def hard_stop_check(self, current_capital: float) -> Tuple[bool, str]:
        """
        Check if we should hard stop (emergency exit all positions).
        
        Args:
            current_capital: Current portfolio value
            
        Returns:
            (should_stop, reason)
        """
        drawdown = (self.peak_capital - current_capital) / self.peak_capital
        
        if drawdown > 0.50:  # 50% drawdown - catastrophic
            return True, "CATASTROPHIC DRAWDDOWN: 50%+ loss"
        
        if current_capital < 0.25:  # Lost 75% of capital
            return True, "CAPITAL DEPLETED: Less than 25% remaining"
        
        return False, ""
