"""
Cross-Exchange Funding Rate Arbitrage - Signal Generator Module
Generates entry, exit, and position management signals.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, NamedTuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging

try:
    from src.indicators import FundingDifferential, FundingRate, OpportunityType
except ImportError:
    from indicators import FundingDifferential, FundingRate, OpportunityType

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Types of trading signals."""
    ENTER_LONG = "enter_long"
    ENTER_SHORT = "enter_short"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"
    REDUCE_SIZE = "reduce_size"
    INCREASE_SIZE = "increase_size"
    HOLD = "hold"


class ExitReason(Enum):
    """Reasons for position exit."""
    FUNDING_CONVERGENCE = "funding_convergence"
    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    TIME_STOP = "time_stop"
    LIQUIDATION_RISK = "liquidation_risk"
    FUNDING_REVERSAL = "funding_reversal"
    MAX_DRAWDOWN = "max_drawdown"
    MANUAL = "manual"


@dataclass
class Signal:
    """Represents a trading signal."""
    timestamp: datetime
    symbol: str
    signal_type: SignalType
    long_exchange: str
    short_exchange: str
    size_usd: float
    confidence: float
    expected_funding_diff: float
    exit_reason: Optional[ExitReason] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class PositionState:
    """Tracks the state of an active position."""
    symbol: str
    long_exchange: str
    short_exchange: str
    entry_time: datetime
    entry_funding_diff: float
    size_usd: float
    leverage_long: float
    leverage_short: float
    accumulated_funding: float = 0.0
    mark_price_long: float = 0.0
    mark_price_short: float = 0.0
    unrealized_pnl: float = 0.0
    
    # Risk metrics
    liquidation_buffer_long: float = 0.0  # Distance to liquidation
    liquidation_buffer_short: float = 0.0
    
    @property
    def duration_hours(self) -> float:
        """Calculate position duration in hours."""
        return (datetime.now() - self.entry_time).total_seconds() / 3600
    
    @property
    def total_pnl(self) -> float:
        """Total P&L including funding."""
        return self.unrealized_pnl + self.accumulated_funding


class SignalGenerator:
    """
    Generates trading signals for cross-exchange funding arbitrage.
    """
    
    def __init__(
        self,
        entry_threshold: float = 0.0002,  # 0.02% min differential
        exit_threshold: float = 0.00005,  # 0.005% convergence threshold
        profit_target_multiple: float = 3.0,  # Exit at 3x entry spread
        max_hold_hours: float = 72.0,  # Time stop
        max_funding_reversal: float = 0.0001,  # Exit if funding reverses by this much
        min_hold_periods: int = 2,  # Minimum funding periods to hold
    ):
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.profit_target_multiple = profit_target_multiple
        self.max_hold_hours = max_hold_hours
        self.max_funding_reversal = max_funding_reversal
        self.min_hold_periods = min_hold_periods
        
        self._positions: Dict[str, PositionState] = {}
        self._funding_periods_held: Dict[str, int] = {}
        
    def generate_entry_signals(
        self,
        opportunities: List[FundingDifferential],
        current_time: datetime,
        available_capital: float,
        max_positions: int = 5
    ) -> List[Signal]:
        """
        Generate entry signals from filtered opportunities.
        
        Args:
            opportunities: List of funding differentials
            current_time: Current timestamp
            available_capital: Available capital for new positions
            max_positions: Maximum number of concurrent positions
        
        Returns:
            List of entry signals
        """
        signals = []
        
        # Check position limit
        current_positions = len(self._positions)
        if current_positions >= max_positions:
            logger.debug(f"Max positions ({max_positions}) reached, skipping entry signals")
            return signals
        
        slots_available = max_positions - current_positions
        
        for opp in opportunities[:slots_available]:
            # Check if already in position for this pair
            position_key = f"{opp.symbol}:{opp.long_exchange}:{opp.short_exchange}"
            if position_key in self._positions:
                continue
            
            # Check entry threshold
            if abs(opp.differential) < self.entry_threshold:
                continue
            
            # Calculate position size
            size_usd = self._calculate_position_size(opp, available_capital)
            
            if size_usd <= 0:
                continue
            
            signal = Signal(
                timestamp=current_time,
                symbol=opp.symbol,
                signal_type=SignalType.ENTER_LONG,
                long_exchange=opp.long_exchange,
                short_exchange=opp.short_exchange,
                size_usd=size_usd,
                confidence=opp.confidence,
                expected_funding_diff=opp.differential,
                metadata={
                    'annualized_return': opp.annualized_diff,
                    'opportunity_score': opp.opportunity_score,
                    'long_funding': opp.long_funding,
                    'short_funding': opp.short_funding
                }
            )
            
            signals.append(signal)
            logger.info(
                f"Generated ENTRY signal for {opp.symbol}: "
                f"Long {opp.long_exchange} / Short {opp.short_exchange}, "
                f"Size: ${size_usd:,.2f}, Diff: {opp.differential:.4%}"
            )
        
        return signals
    
    def generate_exit_signals(
        self,
        current_rates: Dict[str, Dict[str, FundingRate]],
        current_time: datetime,
        position_states: Optional[Dict[str, PositionState]] = None
    ) -> List[Signal]:
        """
        Generate exit signals for active positions.
        
        Args:
            current_rates: Current funding rates by symbol and exchange
            current_time: Current timestamp
            position_states: Optional external position state
        
        Returns:
            List of exit signals
        """
        signals = []
        positions_to_check = position_states or self._positions
        
        for position_key, position in positions_to_check.items():
            signal = self._check_exit_conditions(position, current_rates, current_time)
            if signal:
                signals.append(signal)
        
        return signals
    
    def _check_exit_conditions(
        self,
        position: PositionState,
        current_rates: Dict[str, Dict[str, FundingRate]],
        current_time: datetime
    ) -> Optional[Signal]:
        """Check all exit conditions for a position."""
        
        symbol = position.symbol
        
        # Get current funding rates
        long_rate = None
        short_rate = None
        
        if symbol in current_rates:
            if position.long_exchange in current_rates[symbol]:
                long_rate = current_rates[symbol][position.long_exchange].funding_rate
            if position.short_exchange in current_rates[symbol]:
                short_rate = current_rates[symbol][position.short_exchange].funding_rate
        
        if long_rate is None or short_rate is None:
            logger.warning(f"Missing funding rates for {symbol}, cannot evaluate exit")
            return None
        
        current_diff = short_rate - long_rate
        entry_diff = position.entry_funding_diff
        
        # Track funding periods held
        position_key = f"{position.symbol}:{position.long_exchange}:{position.short_exchange}"
        periods_held = self._funding_periods_held.get(position_key, 0)
        
        # Check minimum hold period
        if periods_held < self.min_hold_periods:
            return None
        
        exit_reason = None
        exit_confidence = 1.0
        
        # Condition 1: Funding convergence
        if abs(current_diff) < self.exit_threshold:
            exit_reason = ExitReason.FUNDING_CONVERGENCE
            exit_confidence = 0.9
            logger.info(
                f"Exit trigger (Convergence) for {symbol}: "
                f"Current diff {current_diff:.4%} < threshold {self.exit_threshold:.4%}"
            )
        
        # Condition 2: Profit target (funding differential compressed significantly)
        elif entry_diff != 0 and abs(current_diff) < abs(entry_diff) / self.profit_target_multiple:
            exit_reason = ExitReason.PROFIT_TARGET
            exit_confidence = 0.85
            logger.info(
                f"Exit trigger (Profit Target) for {symbol}: "
                f"Diff compressed from {entry_diff:.4%} to {current_diff:.4%}"
            )
        
        # Condition 3: Funding reversal (adverse move)
        elif entry_diff > 0 and current_diff < entry_diff - self.max_funding_reversal:
            exit_reason = ExitReason.FUNDING_REVERSAL
            exit_confidence = 0.95
            logger.warning(
                f"Exit trigger (Reversal) for {symbol}: "
                f"Diff reversed from {entry_diff:.4%} to {current_diff:.4%}"
            )
        
        # Condition 4: Time stop
        elif position.duration_hours > self.max_hold_hours:
            exit_reason = ExitReason.TIME_STOP
            exit_confidence = 0.7
            logger.info(
                f"Exit trigger (Time Stop) for {symbol}: "
                f"Held for {position.duration_hours:.1f} hours"
            )
        
        # Condition 5: Liquidation risk
        elif (position.liquidation_buffer_long < 0.05 or 
              position.liquidation_buffer_short < 0.05):
            exit_reason = ExitReason.LIQUIDATION_RISK
            exit_confidence = 1.0
            logger.warning(
                f"Exit trigger (Liquidation Risk) for {symbol}: "
                f"Buffer Long: {position.liquidation_buffer_long:.2%}, "
                f"Buffer Short: {position.liquidation_buffer_short:.2%}"
            )
        
        if exit_reason:
            return Signal(
                timestamp=current_time,
                symbol=position.symbol,
                signal_type=SignalType.EXIT_LONG,  # Represents closing both legs
                long_exchange=position.long_exchange,
                short_exchange=position.short_exchange,
                size_usd=position.size_usd,
                confidence=exit_confidence,
                expected_funding_diff=current_diff,
                exit_reason=exit_reason,
                metadata={
                    'entry_funding_diff': entry_diff,
                    'current_funding_diff': current_diff,
                    'duration_hours': position.duration_hours,
                    'total_pnl': position.total_pnl,
                    'accumulated_funding': position.accumulated_funding
                }
            )
        
        return None
    
    def generate_position_adjustment_signals(
        self,
        position: PositionState,
        current_rates: Dict[str, Dict[str, FundingRate]],
        current_time: datetime
    ) -> List[Signal]:
        """
        Generate position size adjustment signals.
        
        Scenarios:
        - Increase size if opportunity improves
        - Decrease size if risk increases
        """
        signals = []
        
        symbol = position.symbol
        
        # Get current funding rates
        if symbol not in current_rates:
            return signals
        
        long_rate = current_rates[symbol].get(position.long_exchange)
        short_rate = current_rates[symbol].get(position.short_exchange)
        
        if long_rate is None or short_rate is None:
            return signals
        
        current_diff = short_rate.funding_rate - long_rate.funding_rate
        entry_diff = position.entry_funding_diff
        
        # Signal: Increase size if differential significantly improved
        if current_diff > entry_diff * 1.5 and current_diff > self.entry_threshold * 2:
            signal = Signal(
                timestamp=current_time,
                symbol=position.symbol,
                signal_type=SignalType.INCREASE_SIZE,
                long_exchange=position.long_exchange,
                short_exchange=position.short_exchange,
                size_usd=position.size_usd * 0.5,  # Add 50% more
                confidence=0.7,
                expected_funding_diff=current_diff,
                metadata={
                    'reason': 'improved_differential',
                    'entry_diff': entry_diff,
                    'current_diff': current_diff
                }
            )
            signals.append(signal)
        
        # Signal: Reduce size if differential deteriorating but not yet exit
        elif current_diff < entry_diff * 0.7 and current_diff > 0:
            signal = Signal(
                timestamp=current_time,
                symbol=position.symbol,
                signal_type=SignalType.REDUCE_SIZE,
                long_exchange=position.long_exchange,
                short_exchange=position.short_exchange,
                size_usd=position.size_usd * 0.5,  # Reduce by 50%
                confidence=0.6,
                expected_funding_diff=current_diff,
                metadata={
                    'reason': 'deteriorating_differential',
                    'entry_diff': entry_diff,
                    'current_diff': current_diff
                }
            )
            signals.append(signal)
        
        return signals
    
    def _calculate_position_size(
        self,
        opportunity: FundingDifferential,
        available_capital: float,
        max_position_pct: float = 0.2
    ) -> float:
        """
        Calculate optimal position size based on opportunity quality.
        
        Uses confidence-weighted sizing with maximum position limit.
        """
        # Base size: percentage of available capital
        base_size = available_capital * max_position_pct
        
        # Adjust by confidence
        confidence_adjusted = base_size * opportunity.confidence
        
        # Adjust by opportunity score (higher score = larger size)
        score_factor = min(opportunity.opportunity_score / 0.1, 2.0)  # Cap at 2x
        final_size = confidence_adjusted * score_factor
        
        # Ensure we don't exceed available capital
        return min(final_size, available_capital * 0.95)
    
    def register_position_entry(
        self,
        signal: Signal,
        leverage_long: float = 2.0,
        leverage_short: float = 2.0
    ) -> None:
        """Register a new position entry."""
        position_key = f"{signal.symbol}:{signal.long_exchange}:{signal.short_exchange}"
        
        self._positions[position_key] = PositionState(
            symbol=signal.symbol,
            long_exchange=signal.long_exchange,
            short_exchange=signal.short_exchange,
            entry_time=signal.timestamp,
            entry_funding_diff=signal.expected_funding_diff,
            size_usd=signal.size_usd,
            leverage_long=leverage_long,
            leverage_short=leverage_short
        )
        
        self._funding_periods_held[position_key] = 0
        
        logger.info(f"Registered new position: {position_key}")
    
    def register_position_exit(
        self,
        signal: Signal,
        realized_pnl: float = 0.0
    ) -> None:
        """Register a position exit."""
        position_key = f"{signal.symbol}:{signal.long_exchange}:{signal.short_exchange}"
        
        if position_key in self._positions:
            del self._positions[position_key]
        if position_key in self._funding_periods_held:
            del self._funding_periods_held[position_key]
        
        logger.info(
            f"Closed position {position_key}: "
            f"PnL: ${realized_pnl:,.2f}, Reason: {signal.exit_reason}"
        )
    
    def increment_funding_period(self) -> None:
        """Increment funding period counter for all positions."""
        for key in self._funding_periods_held:
            self._funding_periods_held[key] += 1
    
    def update_position_state(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str,
        mark_price_long: float,
        mark_price_short: float,
        liquidation_buffer_long: float,
        liquidation_buffer_short: float,
        funding_payment: float = 0.0
    ) -> None:
        """Update position state with latest data."""
        position_key = f"{symbol}:{long_exchange}:{short_exchange}"
        
        if position_key not in self._positions:
            return
        
        position = self._positions[position_key]
        position.mark_price_long = mark_price_long
        position.mark_price_short = mark_price_short
        position.liquidation_buffer_long = liquidation_buffer_long
        position.liquidation_buffer_short = liquidation_buffer_short
        
        # Update accumulated funding
        position.accumulated_funding += funding_payment
        
        # Calculate unrealized P&L from price divergence
        if position.mark_price_long > 0 and position.mark_price_short > 0:
            price_diff = position.mark_price_short - position.mark_price_long
            position.unrealized_pnl = price_diff * (position.size_usd / position.mark_price_long)
    
    def get_active_positions(self) -> Dict[str, PositionState]:
        """Get all active positions."""
        return self._positions.copy()
    
    def get_position_summary(self) -> Dict[str, any]:
        """Get summary statistics of active positions."""
        if not self._positions:
            return {
                'count': 0,
                'total_size': 0.0,
                'total_pnl': 0.0,
                'avg_duration': 0.0
            }
        
        total_size = sum(p.size_usd for p in self._positions.values())
        total_pnl = sum(p.total_pnl for p in self._positions.values())
        avg_duration = np.mean([p.duration_hours for p in self._positions.values()])
        
        return {
            'count': len(self._positions),
            'total_size': total_size,
            'total_pnl': total_pnl,
            'avg_duration': avg_duration
        }
