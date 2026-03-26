"""
Risk Manager for Polymarket 5-Minute BTC Signal Arbitrage

Implements circuit breakers, position limits, and capital protection rules
based on the v3 engine improvements from live trading sessions.

Key improvements from paper:
1. 10-minute trend filter eliminated directional bias
2. Raised thresholds reduced trade frequency by 73%
3. Capital preservation rules
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Overall risk assessment."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskState:
    """Current state of risk management."""
    starting_balance: float
    current_balance: float
    session_pnl: float
    session_pnl_pct: float
    daily_loss_pct: float
    trades_today: int
    consecutive_wins: int
    consecutive_losses: int
    current_risk_level: RiskLevel
    circuit_breaker_triggered: bool
    blocked_until: Optional[datetime] = None
    reason: str = ""


@dataclass
class RiskConfig:
    """Configuration for risk management."""
    starting_balance: float = 1000.0
    daily_loss_limit_pct: float = 0.20  # 20% max daily loss
    max_trades_per_session: int = 50
    max_trades_per_window: int = 1  # No duplicate bets
    circuit_breaker_enabled: bool = True
    min_balance_pct: float = 0.30  # Stop if cash < 30% of starting
    max_position_pct: float = 0.25  # Max 25% of balance per trade


class RiskManager:
    """
    Comprehensive risk manager for Polymarket trading.

    Implements:
    1. Circuit breakers (daily loss, max trades)
    2. Position limits (no duplicates, max size)
    3. Capital preservation (min balance, drawdown limits)
    4. Consecutive loss tracking
    5. Risk level assessment
    """

    def __init__(self, config: RiskConfig = None):
        """
        Initialize risk manager.

        Args:
            config: Risk configuration parameters
        """
        self.config = config or RiskConfig()
        self._reset()

    def _reset(self):
        """Reset internal state for new session."""
        self.starting_balance = self.config.starting_balance
        self.current_balance = self.config.starting_balance
        self.session_pnl = 0.0
        self.session_pnl_pct = 0.0
        self.daily_loss_pct = 0.0
        self.trades_today = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.circuit_breaker_triggered = False
        self.blocked_until = None
        self.traded_windows = set()  # Track windows we've bet on

    def get_state(self) -> RiskState:
        """Get current risk state."""
        return RiskState(
            starting_balance=self.starting_balance,
            current_balance=self.current_balance,
            session_pnl=self.session_pnl,
            session_pnl_pct=self.session_pnl_pct,
            daily_loss_pct=self.daily_loss_pct,
            trades_today=self.trades_today,
            consecutive_wins=self.consecutive_wins,
            consecutive_losses=self.consecutive_losses,
            current_risk_level=self._assess_risk_level(),
            circuit_breaker_triggered=self.circuit_breaker_triggered,
            blocked_until=self.blocked_until,
        )

    def _assess_risk_level(self) -> RiskLevel:
        """Assess current risk level based on state."""
        balance_pct = self.current_balance / self.starting_balance
        daily_loss = 1.0 - balance_pct

        if self.circuit_breaker_triggered:
            return RiskLevel.CRITICAL
        elif daily_loss > 0.50:
            return RiskLevel.HIGH
        elif daily_loss > 0.30:
            return RiskLevel.MEDIUM
        elif daily_loss > 0.20:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def can_trade(
        self,
        window_id: str = None,
        proposed_size: float = 0.0,
    ) -> tuple[bool, str]:
        """
        Check if trading is allowed under current risk state.

        Args:
            window_id: Unique identifier for 5-minute window
            proposed_size: Size of proposed trade

        Returns:
            Tuple of (allowed, reason)
        """
        # Check circuit breaker
        if self.circuit_breaker_triggered:
            return False, "Circuit breaker triggered"

        # Check blocked status
        if self.blocked_until and datetime.now() < self.blocked_until:
            remaining = (self.blocked_until - datetime.now()).seconds
            return False, f"Blocked for {remaining}s"

        # Check max trades
        if self.trades_today >= self.config.max_trades_per_session:
            return False, f"Max trades ({self.config.max_trades_per_session}) reached"

        # Check duplicate window
        if window_id and self.traded_windows:
            if window_id in self.traded_windows:
                return False, f"Already traded on window {window_id}"

        # Check position size
        max_position = self.current_balance * self.config.max_position_pct
        if proposed_size > max_position:
            return False, f"Size {proposed_size:.2f} exceeds max {max_position:.2f}"

        # Check min balance
        balance_pct = self.current_balance / self.starting_balance
        if balance_pct < self.config.min_balance_pct:
            return False, f"Balance {balance_pct:.1%} below minimum {self.config.min_balance_pct:.1%}"

        # Check daily loss limit
        if self.daily_loss_pct > self.config.daily_loss_limit_pct:
            return False, f"Daily loss {self.daily_loss_pct:.1%} exceeds limit {self.config.daily_loss_limit_pct:.1%}"

        return True, "OK"

    def record_trade(
        self,
        window_id: str,
        direction: str,
        size: float,
        entry_price: float,
    ):
        """
        Record that a trade was executed.

        Args:
            window_id: Window identifier
            direction: 'up' or 'down'
            size: Position size
            entry_price: Entry price
        """
        self.traded_windows.add(window_id)
        self.trades_today += 1
        logger.info(
            f"Trade recorded: {direction} @{entry_price:.4f}, size={size:.2f}, "
            f"window={window_id}, trades_today={self.trades_today}"
        )

    def record_outcome(
        self,
        window_id: str,
        won: bool,
        pnl: float,
        resolution_price: float,
    ):
        """
        Record trade outcome and update risk state.

        Args:
            window_id: Window identifier
            won: Whether trade was a winner
            pnl: Profit/loss amount
            resolution_price: Resolution price from Polymarket
        """
        self.current_balance += pnl
        self.session_pnl += pnl
        self.session_pnl_pct = self.session_pnl / self.starting_balance
        self.daily_loss_pct = max(0, -self.session_pnl) / self.starting_balance

        if won:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            logger.info(f"WIN: +${pnl:.2f}, balance=${self.current_balance:.2f}, streak={self.consecutive_wins}")
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            logger.info(f"LOSS: ${pnl:.2f}, balance=${self.current_balance:.2f}, streak={self.consecutive_losses}")

        # Check circuit breaker conditions
        if self.config.circuit_breaker_enabled:
            self._check_circuit_breakers()

    def _check_circuit_breakers(self):
        """Check and trigger circuit breakers if needed."""
        balance_pct = self.current_balance / self.starting_balance

        # Daily loss circuit breaker
        if self.daily_loss_pct >= self.config.daily_loss_limit_pct:
            self.circuit_breaker_triggered = True
            self.blocked_until = None  # Block until manually reset
            logger.warning(
                f"CIRCUIT BREAKER: Daily loss {self.daily_loss_pct:.1%} exceeds "
                f"limit {self.config.daily_loss_limit_pct:.1%}"
            )

        # Balance circuit breaker
        if balance_pct < 0.20:
            self.circuit_breaker_triggered = True
            logger.warning(
                f"CIRCUIT BREAKER: Balance {balance_pct:.1%} critically low"
            )

        # Max trades circuit breaker
        if self.trades_today >= self.config.max_trades_per_session:
            logger.info(
                f"Max trades reached: {self.trades_today}/{self.config.max_trades_per_session}"
            )

    def get_risk_report(self) -> str:
        """
        Generate human-readable risk report.

        Returns:
            Formatted risk status string
        """
        state = self.get_state()
        balance_pct = state.current_balance / state.starting_balance

        report = f"""
=== RISK REPORT ===
Starting Balance: ${state.starting_balance:.2f}
Current Balance:  ${state.current_balance:.2f}
Session P&L:       ${state.session_pnl:+.2f} ({state.session_pnl_pct:+.2%})
Balance %:         {balance_pct:.1%}

Daily Loss:        {state.daily_loss_pct:.1%} (limit: {self.config.daily_loss_limit_pct:.1%})
Trades Today:      {state.trades_today}
Max Trades:        {self.config.max_trades_per_session}

Consecutive Wins:  {state.consecutive_wins}
Consecutive Losses: {state.consecutive_losses}

Risk Level:        {state.current_risk_level.value.upper()}
Circuit Breaker:   {'TRIGGERED' if state.circuit_breaker_triggered else 'OK'}
"""
        return report

    def reset_for_new_day(self):
        """Reset daily counters."""
        self.daily_loss_pct = 0.0
        self.trades_today = 0
        self.traded_windows.clear()
        logger.info("Risk manager reset for new day")


class TrendFilter:
    """
    10-minute trend filter to eliminate directional bias.

    From paper v3 engine:
    - Hard rule: DISLOCATION signals opposing 10-minute trend are blocked unconditionally
    - When composite momentum direction opposes trend, confidence is halved
    """

    def __init__(self, window_seconds: int = 600):
        """
        Initialize trend filter.

        Args:
            window_seconds: Window for trend calculation (default 600s = 10 min)
        """
        self.window_seconds = window_seconds
        self.price_history = []

    def add_price(self, price: float, timestamp: float):
        """Add price observation."""
        self.price_history.append((timestamp, price))
        self._prune_old_prices(timestamp)

    def _prune_old_prices(self, current_time: float):
        """Remove prices outside window."""
        cutoff = current_time - self.window_seconds
        self.price_history = [
            (ts, p) for ts, p in self.price_history
            if ts >= cutoff
        ]

    def get_trend(self) -> tuple[str, float]:
        """
        Get current trend direction and strength.

        Returns:
            Tuple of (direction: 'up'/'down'/'none', strength: float)
        """
        if len(self.price_history) < 2:
            return 'none', 0.0

        prices = [p for _, p in self.price_history]
        return self._compute_trend_from_prices(prices)

    def _compute_trend_from_prices(self, prices: list[float]) -> tuple[str, float]:
        """
        Compute trend from price list.

        Uses simple linear regression slope.

        Args:
            prices: List of prices

        Returns:
            Tuple of (direction, strength)
        """
        if len(prices) < 2:
            return 'none', 0.0

        n = len(prices)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(prices) / n

        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, prices))
        denominator = sum((xi - x_mean) ** 2 for xi in x)

        if denominator == 0:
            return 'none', 0.0

        slope = numerator / denominator
        mean_price = y_mean

        # Normalize slope
        normalized_slope = slope / mean_price if mean_price > 0 else 0.0

        if normalized_slope > 0.0001:  # Threshold for "up"
            direction = 'up'
        elif normalized_slope < -0.0001:
            direction = 'down'
        else:
            direction = 'none'

        strength = abs(normalized_slope)
        return direction, strength

    def check_alignment(self, signal_direction: str) -> tuple[bool, float]:
        """
        Check if signal aligns with trend.

        Args:
            signal_direction: Direction of signal ('up', 'down', 'none')

        Returns:
            Tuple of (aligned, confidence_multiplier)
        """
        trend, strength = self.get_trend()

        if trend == 'none':
            # No trend - allow signal, don't penalize
            return True, 1.0

        if signal_direction == trend:
            # Signal aligns with trend - full confidence
            return True, 1.0
        else:
            # Signal opposes trend - block DISLOCATION, halve confidence for others
            return False, 0.5
