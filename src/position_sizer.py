"""
Position Sizing Module using Fractional Kelly Criterion

Implements optimal bet sizing for Polymarket binary options based on
Kelly criterion theory and practical implementation guidelines.

References:
- Kelly Jr., J.L. "A new interpretation of information rate" (1956)
- Carta and Conversano "Practical implementation of the Kelly criterion" (2020)
"""

from dataclasses import dataclass
from typing import Optional
import math
import logging

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Calculated position size with full breakdown."""
    size: float
    kelly_fraction: float
    edge: float
    kelly_bet: float
    size_factor: float
    reasoning: str


class PositionSizer:
    """
    Fractional Kelly position sizer for binary options.

    Uses the Kelly criterion to determine optimal bet size, with:
    1. Quarter-Kelly cap (max 25% of full Kelly) for safety
    2. Dynamic size_factor based on conviction level
    3. Minimum edge threshold to avoid negative edge bets
    4. Consecutive loss adjustment
    """

    def __init__(
        self,
        kelly_fraction: float = 0.25,
        size_factor_high: float = 1.0,
        size_factor_low: float = 0.5,
        min_edge_for_trade: float = 0.03,
        min_edge_after_losses: float = 0.05,
        consecutive_loss_threshold: int = 3,
    ):
        """
        Initialize position sizer.

        Args:
            kelly_fraction: Maximum Kelly fraction to use (0.25 = quarter-Kelly)
            size_factor_high: Size multiplier for high conviction signals
            size_factor_low: Size multiplier for low conviction signals
            min_edge_for_trade: Minimum edge required to place any bet
            min_edge_after_losses: Minimum edge after consecutive losses
            consecutive_loss_threshold: Number of losses before stricter edge req
        """
        self.kelly_fraction = kelly_fraction
        self.size_factor_high = size_factor_high
        self.size_factor_low = size_factor_low
        self.min_edge_for_trade = min_edge_for_trade
        self.min_edge_after_losses = min_edge_after_losses
        self.consecutive_loss_threshold = consecutive_loss_threshold

        logger.info(
            f"PositionSizer initialized: kelly_fraction={kelly_fraction}, "
            f"min_edge={min_edge_for_trade}"
        )

    def compute_kelly_bet(
        self,
        edge: float,
        win_prob: float,
    ) -> float:
        """
        Compute full Kelly bet size as fraction of bankroll.

        Kelly formula for binary outcome:
        kelly = (p * b - q) / b
              = (p * (1 - p) - q) / (1 - p)
              = (p - q) / (1 - p)
              = edge / (1 - p)

        Where:
        - p = probability of winning
        - q = probability of losing = 1 - p
        - b = net odds received on winning bet (for binary, b = 1)

        For binary options (win $1 or lose $1):
        kelly = edge / (1 - token_price)

        Args:
            edge: Estimated edge (fair_prob - token_price)
            win_prob: Estimated win probability (token_price is inverse)

        Returns:
            Full Kelly bet size as fraction of bankroll
        """
        # For binary options where token pays $1 on win:
        # edge = win_prob - token_price
        # kelly ≈ edge / (1 - token_price)

        if win_prob <= 0 or win_prob >= 1:
            return 0.0

        # Alternative: direct edge-based formula
        # kelly = edge / (1 - token_price) where token_price represents loss amt
        # But simpler: kelly = edge / variance

        # For even-odds binary bet:
        # kelly = 2p - 1 (this is for simple win/lose 1 unit)

        # Our edge-based approach:
        # We have edge = fair_prob - token_price
        # And we expect to win fair_prob of the time

        # Kelly for binary with edge:
        # f* = (bp - q) / b where b = 1 (even odds), p = win prob, q = 1-p
        # f* = p - q = p - (1-p) = 2p - 1
        # But we need to adjust for our edge calculation

        # Using the formula from Carta and Conversano (2020):
        # kelly = edge / (1 - token_price)
        # where edge = confidence - token_price

        # This makes sense: with no edge (edge=0), kelly=0
        # With positive edge, kelly grows proportionally

        if edge <= 0:
            return 0.0

        # Max reasonable Kelly is 0.25 (quarter-Kelly)
        max_kelly = self.kelly_fraction

        # Using edge-based formula
        # Kelly = edge / (1 - p) where p = probability of winning
        # But we have edge = p - q where q = 1-p
        # So Kelly = (p - q) / q = (2p - 1) / (1-p)

        # Let's use the simpler confidence-based approach
        # Since edge = confidence - token_price already incorporates edge

        # Kelly = edge / variance
        # For binary: variance = p * (1-p) * b^2 = p(1-p)
        # Kelly ≈ edge / p(1-p)

        # But simpler still: scale edge to Kelly
        p = win_prob
        q = 1 - p

        if p <= 0.5:
            # No positive edge expected
            return 0.0

        # Full Kelly for binary options
        # f* = (bp - q) / b = (p - q) / 1 = 2p - 1
        kelly = 2 * p - 1

        # Adjust for our edge calculation
        # We want to reward higher edge
        edge_adjustment = 1 + edge
        kelly = kelly * edge_adjustment

        # Cap at max Kelly fraction
        kelly = min(kelly, max_kelly)

        # Don't bet if Kelly is negative or too small
        if kelly <= 0:
            return 0.0

        return kelly

    def determine_size_factor(
        self,
        confidence: float,
        edge: float,
        consecutive_losses: int,
        cash_balance: float,
        starting_balance: float,
    ) -> float:
        """
        Determine size factor based on conviction and risk state.

        Args:
            confidence: Signal confidence (0-1)
            edge: Estimated edge
            consecutive_losses: Current consecutive loss streak
            cash_balance: Current cash balance
            starting_balance: Starting balance for session

        Returns:
            Size factor (0.5 for low conviction, 1.0 for high)
        """
        size_factor = self.size_factor_high

        # Reduce size after losses
        if consecutive_losses >= self.consecutive_loss_threshold:
            size_factor *= 0.5
            logger.info(f"Reducing size factor to {size_factor} after {consecutive_losses} losses")

        # Reduce if cash is low
        cash_pct = cash_balance / starting_balance if starting_balance > 0 else 1.0
        if cash_pct < 0.5:
            size_factor *= 0.75
            logger.info(f"Reducing size factor to {size_factor}: cash only {cash_pct:.1%} of starting")

        # Boost for high confidence
        if confidence > 0.7:
            size_factor *= 1.1  # Slight boost for high conviction

        return size_factor

    def calculate_position_size(
        self,
        confidence: float,
        token_price: float,
        fee_adjusted_edge: float,
        budget: float,
        consecutive_losses: int = 0,
        starting_balance: float = None,
        size_factor_override: float = None,
    ) -> PositionSize:
        """
        Calculate optimal position size for a trade.

        Main entry point for position sizing. Combines Kelly criterion
        with practical adjustments for risk management.

        Formula:
        size = budget × min(kelly, 0.25) × size_factor

        Args:
            confidence: Signal confidence (0-1)
            token_price: Current token price (0-1)
            fee_adjusted_edge: Edge after fees (positive = advantage)
            budget: Available budget for this trade
            consecutive_losses: Current loss streak
            starting_balance: Original starting balance
            size_factor_override: Override size factor (for testing)

        Returns:
            PositionSize with full breakdown
        """
        if starting_balance is None:
            starting_balance = budget

        # Check minimum edge threshold
        min_edge = self.min_edge_for_trade
        if consecutive_losses >= self.consecutive_loss_threshold:
            min_edge = self.min_edge_after_losses

        if fee_adjusted_edge < min_edge:
            return PositionSize(
                size=0.0,
                kelly_fraction=self.kelly_fraction,
                edge=fee_adjusted_edge,
                kelly_bet=0.0,
                size_factor=0.0,
                reasoning=f"Edge {fee_adjusted_edge:.4f} below minimum {min_edge:.4f}",
            )

        # Calculate Kelly bet
        # For binary option: fair probability is our edge indicator
        win_prob = min(token_price + fee_adjusted_edge, 0.99)
        kelly_bet = self.compute_kelly_bet(fee_adjusted_edge, win_prob)

        if kelly_bet <= 0:
            return PositionSize(
                size=0.0,
                kelly_fraction=self.kelly_fraction,
                edge=fee_adjusted_edge,
                kelly_bet=0.0,
                size_factor=0.0,
                reasoning="Kelly bet calculated as 0 or negative",
            )

        # Determine size factor
        size_factor = size_factor_override
        if size_factor is None:
            size_factor = self.determine_size_factor(
                confidence=confidence,
                edge=fee_adjusted_edge,
                consecutive_losses=consecutive_losses,
                cash_balance=budget,
                starting_balance=starting_balance,
            )

        # Final position size
        # Apply Kelly cap (already done in compute_kelly_bet)
        kelly_capped = min(kelly_bet, self.kelly_fraction)

        # Size = budget × Kelly × size_factor
        size = budget * kelly_capped * size_factor

        # Sanity check: don't bet more than 50% of budget in one trade
        max_position_pct = 0.50
        max_size = budget * max_position_pct
        if size > max_size:
            logger.warning(f"Position size {size:.2f} exceeds max {max_size:.2f}, capping")
            size = max_size

        # Minimum bet size (avoid dust)
        min_bet = 1.0
        if size < min_bet:
            return PositionSize(
                size=0.0,
                kelly_fraction=self.kelly_fraction,
                edge=fee_adjusted_edge,
                kelly_bet=kelly_bet,
                size_factor=size_factor,
                reasoning=f"Calculated size {size:.2f} below minimum {min_bet}",
            )

        return PositionSize(
            size=size,
            kelly_fraction=self.kelly_fraction,
            edge=fee_adjusted_edge,
            kelly_bet=kelly_bet,
            size_factor=size_factor,
            reasoning=f"Kelly={kelly_capped:.4f}, size_factor={size_factor:.2f}, budget={budget:.2f}",
        )

    def calculate_position_size_simple(
        self,
        confidence: float,
        token_price: float,
        budget: float,
        max_position_pct: float = 0.25,
    ) -> float:
        """
        Simplified position sizing for quick calculations.

        Useful for backtesting or when edge estimates are uncertain.

        Args:
            confidence: Signal confidence (0-1)
            token_price: Current token price (0-1)
            budget: Available budget
            max_position_pct: Maximum % of budget to risk (default 25%)

        Returns:
            Position size
        """
        # Simple approach: size = budget × confidence × (1 - token_price)
        # This weights by conviction and limits exposure on uncertain bets

        position_pct = confidence * (1 - token_price) * max_position_pct
        size = budget * position_pct

        # Cap at max position
        max_size = budget * max_position_pct
        return min(size, max_size)
