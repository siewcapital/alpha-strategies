"""
StatArb Alpha: Risk Management Module
This module handles position sizing and drawdown limits.
"""

import numpy as np

class RiskManager:
    def __init__(self, max_risk_per_trade: float = 0.01, daily_drawdown_limit: float = 0.02, total_drawdown_limit: float = 0.10):
        """
        :param max_risk_per_trade: Max % of portfolio to risk per trade.
        :param daily_drawdown_limit: Daily loss limit.
        :param total_drawdown_limit: Total loss limit.
        """
        self.max_risk_per_trade = max_risk_per_trade
        self.daily_drawdown_limit = daily_drawdown_limit
        self.total_drawdown_limit = total_drawdown_limit
        self.current_portfolio_value = 100000.0  # Initial portfolio
        self.daily_starting_value = 100000.0
        self.daily_loss = 0.0

    def calculate_position_size(self, current_z: float, volatility: float) -> float:
        """
        Calculate the size of the position (e.g., $ value).
        Using a simple volatility-adjusted sizing.
        :param current_z: The Z-score of the spread.
        :param volatility: The volatility of the spread.
        """
        # Adjusted size: Size increases with Z-score (more extreme divergence)
        # but decreases with volatility (more risk).
        # Cap at max_risk_per_trade.
        base_size = self.current_portfolio_value * self.max_risk_per_trade
        vol_adj_size = base_size / volatility if volatility > 0 else base_size
        return min(vol_adj_size * abs(current_z), self.current_portfolio_value * 0.1)

    def check_drawdown_limit(self, current_value: float) -> bool:
        """
        Check if the strategy should halt due to drawdown limits.
        """
        # Daily drawdown
        daily_dd = (self.daily_starting_value - current_value) / self.daily_starting_value
        if daily_dd >= self.daily_drawdown_limit:
            return True
            
        # Total drawdown
        total_dd = (100000.0 - current_value) / 100000.0
        if total_dd >= self.total_drawdown_limit:
            return True
            
        return False

    def update_portfolio(self, pnl: float):
        """Update the current portfolio value and daily loss."""
        self.current_portfolio_value += pnl
        self.daily_loss += pnl

    def reset_daily(self):
        """Reset daily tracking variables."""
        self.daily_starting_value = self.current_portfolio_value
        self.daily_loss = 0.0
