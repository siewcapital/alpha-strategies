"""
Main Strategy Orchestrator for Polymarket 5-Min BTC Signal Arbitrage

Ties together:
- SignalEngine: Multi-timeframe momentum analysis
- PositionSizer: Fractional Kelly position sizing
- RiskManager: Circuit breakers and capital protection
- LLM Filter: AI-augmented trade filtering

Based on Jung-Hua Liu's live trading research (March 2026).
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import logging
import json
from pathlib import Path

from .signal_engine import SignalEngine, SignalType, Direction, CompositeSignal
from .position_sizer import PositionSizer, PositionSize
from .risk_manager import RiskManager, RiskConfig, RiskState

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Record of a completed trade."""
    window_id: str
    signal_type: str
    direction: str
    entry_price: float
    size: float
    timestamp: datetime
    outcome: Optional[str] = None  # 'win', 'loss', 'pending'
    pnl: float = 0.0
    resolution_price: float = 0.0
    reasoning: str = ""


@dataclass
class StrategyState:
    """Current state of the strategy."""
    running: bool
    windows_processed: int
    signals_generated: int
    trades_executed: int
    trades_won: int
    trades_lost: int
    current_signal: Optional[CompositeSignal] = None
    risk_state: Optional[RiskState] = None


class PolymarketSignalStrategy:
    """
    Main orchestrator for Polymarket 5-minute BTC signal arbitrage.

    This strategy:
    1. Monitors BTC price and Polymarket order book
    2. Generates multi-timeframe momentum signals
    3. Applies 10-minute trend filter
    4. Sizes positions using fractional Kelly
    5. Filters through LLM (or hard rules)
    6. Executes trades on Polymarket CLOB
    7. Records outcomes and manages risk

    From paper findings:
    - v2 engine lost 49.5% ROI due to directional bias
    - v3 engine with trend filter improved by 7×
    - Win rates of 25-27% observed (below 53% breakeven)
    - Fee-adjusted minimum edge: ~3%
    """

    def __init__(
        self,
        starting_balance: float = 1000.0,
        signal_config: dict = None,
        position_config: dict = None,
        risk_config: dict = None,
        llm_filter_enabled: bool = False,  # Default off for backtest
        save_trades: bool = True,
        results_dir: str = None,
    ):
        """
        Initialize strategy.

        Args:
            starting_balance: Initial capital
            signal_config: Dict of signal engine parameters
            position_config: Dict of position sizer parameters
            risk_config: Dict of risk manager parameters
            llm_filter_enabled: Whether to use LLM filtering (default False)
            save_trades: Whether to save trade records
            results_dir: Directory for results
        """
        self.starting_balance = starting_balance
        self.llm_filter_enabled = llm_filter_enabled
        self.save_trades = save_trades
        self.results_dir = Path(results_dir) if results_dir else None

        # Initialize components
        self.signal_engine = SignalEngine(
            **(signal_config or {})
        )
        self.position_sizer = PositionSizer(
            **(position_config or {})
        )
        self.risk_manager = RiskManager(
            config=RiskConfig(
                starting_balance=starting_balance,
                **{k: v for k, v in (risk_config or {}).items()
                   if k in ['daily_loss_limit_pct', 'max_trades_per_session',
                           'circuit_breaker_enabled', 'min_balance_pct', 'max_position_pct']}
            )
        )

        # State
        self.state = StrategyState(
            running=False,
            windows_processed=0,
            signals_generated=0,
            trades_executed=0,
            trades_won=0,
            trades_lost=0,
        )
        self.trades = []
        self.recent_outcomes = []  # For LLM filter context

        # Price buffers for momentum calculation
        self.price_buffers = {
            30: [],
            60: [],
            120: [],
            240: [],
        }
        self.trend_prices = []
        self.current_window_id = None
        self.window_open_price = None

        logger.info(
            f"Strategy initialized: balance=${starting_balance:.2f}, "
            f"llm_filter={llm_filter_enabled}"
        )

    def process_market_data(
        self,
        btc_price: float,
        token_price: float,
        timestamp: datetime,
        orderbook: dict = None,
    ) -> tuple[Optional[CompositeSignal], Optional[PositionSize]]:
        """
        Process incoming market data and generate signals.

        Call this every tick (e.g., every 10 seconds).

        Args:
            btc_price: Current BTC/USD price
            token_price: Current Polymarket UP token price
            timestamp: Current timestamp
            orderbook: Optional order book data

        Returns:
            Tuple of (signal, position_size) if signal generated, else (None, None)
        """
        # Update price buffers
        self._update_price_buffers(btc_price, timestamp)

        # Check if new window
        window_id = self._get_window_id(timestamp)
        if window_id != self.current_window_id:
            self._start_new_window(window_id, btc_price, timestamp)

        # Calculate time remaining in window
        window_time_remaining = self._get_window_time_remaining(timestamp)

        # Check if token has adjusted (lagging)
        token_has_adjusted = self._check_token_adjustment(
            btc_price, self.window_open_price, token_price
        )

        # Generate signal
        signal = self.signal_engine.generate_signal(
            price_buffers=self.price_buffers,
            trend_prices=self.trend_prices,
            current_price=btc_price,
            window_open_price=self.window_open_price,
            current_token_price=token_price,
            token_has_adjusted=token_has_adjusted,
            window_time_remaining=window_time_remaining,
        )

        self.state.windows_processed += 1

        if signal.signal_type == SignalType.NO_SIGNAL:
            return None, None

        self.state.signals_generated += 1
        self.state.current_signal = signal

        # Check risk
        can_trade, reason = self.risk_manager.can_trade(
            window_id=window_id,
            proposed_size=0,  # Check without size first
        )

        if not can_trade:
            logger.info(f"Signal blocked by risk: {reason}")
            return signal, None

        # Size position
        position_size = self.position_sizer.calculate_position_size(
            confidence=signal.confidence,
            token_price=token_price,
            fee_adjusted_edge=signal.fee_adjusted_edge,
            budget=self.risk_manager.current_balance,
            consecutive_losses=self.risk_manager.consecutive_losses,
            starting_balance=self.risk_manager.starting_balance,
        )

        if position_size.size <= 0:
            logger.info(f"Position size 0: {position_size.reasoning}")
            return signal, None

        # Check size with risk
        can_trade, reason = self.risk_manager.can_trade(
            window_id=window_id,
            proposed_size=position_size.size,
        )

        if not can_trade:
            logger.info(f"Position blocked by risk: {reason}")
            return signal, None

        return signal, position_size

    def execute_trade(
        self,
        signal: CompositeSignal,
        position_size: PositionSize,
        window_id: str,
        timestamp: datetime,
    ) -> Trade:
        """
        Execute a trade based on signal and position size.

        Args:
            signal: Signal to trade on
            position_size: Calculated position size
            window_id: Window identifier
            timestamp: Execution timestamp

        Returns:
            Trade record
        """
        trade = Trade(
            window_id=window_id,
            signal_type=signal.signal_type.value,
            direction=signal.direction.value,
            entry_price=signal.token_price,
            size=position_size.size,
            timestamp=timestamp,
            reasoning=signal.reasoning,
        )

        # Record with risk manager
        self.risk_manager.record_trade(
            window_id=window_id,
            direction=signal.direction.value,
            size=position_size.size,
            entry_price=signal.token_price,
        )

        self.state.trades_executed += 1
        self.trades.append(trade)

        logger.info(
            f"TRADE EXECUTED: {signal.direction.value} "
            f"@{signal.token_price:.4f}, size=${position_size.size:.2f}"
        )

        return trade

    def record_resolution(
        self,
        window_id: str,
        won: bool,
        resolution_price: float,
        pnl: float,
    ):
        """
        Record the outcome of a trade.

        Args:
            window_id: Window that was traded
            won: Whether trade was a winner
            resolution_price: Resolution price from Polymarket
            pnl: Profit/loss amount
        """
        # Find trade
        trade = next((t for t in self.trades if t.window_id == window_id), None)
        if trade:
            trade.outcome = 'win' if won else 'loss'
            trade.pnl = pnl
            trade.resolution_price = resolution_price

        # Update risk manager
        self.risk_manager.record_outcome(
            window_id=window_id,
            won=won,
            pnl=pnl,
            resolution_price=resolution_price,
        )

        # Update state
        if won:
            self.state.trades_won += 1
        else:
            self.state.trades_lost += 1

        # Update recent outcomes
        direction = trade.direction if trade else 'unknown'
        self.recent_outcomes.append((direction, won))
        if len(self.recent_outcomes) > 8:
            self.recent_outcomes = self.recent_outcomes[-8:]

    def _update_price_buffers(self, price: float, timestamp: datetime):
        """Update rolling price buffers."""
        ts = timestamp.timestamp()

        for tf in self.price_buffers:
            self.price_buffers[tf].append((ts, price))
            # Prune old prices
            cutoff = ts - tf
            self.price_buffers[tf] = [
                (t, p) for t, p in self.price_buffers[tf] if t >= cutoff
            ]

        # Update trend prices (10-minute window)
        self.trend_prices.append((ts, price))
        trend_cutoff = ts - 600
        self.trend_prices = [
            (t, p) for t, p in self.trend_prices if t >= trend_cutoff
        ]

    def _get_window_id(self, timestamp: datetime) -> str:
        """Get 5-minute window ID from timestamp."""
        ts = timestamp.timestamp()
        window_start = int(ts // 300) * 300
        return f"btc-updown-5m-{window_start}"

    def _start_new_window(self, window_id: str, btc_price: float, timestamp: datetime):
        """Handle new 5-minute window start."""
        logger.debug(f"New window: {window_id}")
        self.current_window_id = window_id
        self.window_open_price = btc_price

    def _get_window_time_remaining(self, timestamp: datetime) -> int:
        """Get seconds remaining in current window."""
        ts = timestamp.timestamp()
        window_end = (int(ts // 300) + 1) * 300
        return max(0, int(window_end - ts))

    def _check_token_adjustment(
        self,
        current_btc: float,
        open_btc: float,
        token_price: float,
    ) -> bool:
        """
        Check if token price has adjusted to BTC move.

        From paper:
        - DISLOCATION fires when BTC moved but token hasn't adjusted
        - Token has NOT adjusted if: abs(btc_change) > 0.05% but token still near 0.50
        """
        if open_btc is None or open_btc == 0:
            return True  # Can't determine

        btc_change_pct = (current_btc - open_btc) / open_btc

        # Token has adjusted if:
        # 1. BTC moved significantly AND
        # 2. Token moved in expected direction
        # Token should be >0.52 for UP move or <0.48 for DOWN move

        if abs(btc_change_pct) < 0.0005:  # Less than 0.05% move
            return True  # No significant move

        expected_direction = 'up' if btc_change_pct > 0 else 'down'

        if expected_direction == 'up':
            return token_price > 0.52
        else:
            return token_price < 0.48

    def get_state(self) -> StrategyState:
        """Get current strategy state."""
        self.state.risk_state = self.risk_manager.get_state()
        return self.state

    def get_metrics(self) -> dict:
        """
        Calculate performance metrics.

        Returns:
            Dict of performance metrics
        """
        state = self.get_state()
        risk = self.risk_manager.get_state()

        total_trades = state.trades_won + state.trades_lost
        win_rate = state.trades_won / total_trades if total_trades > 0 else 0

        return {
            'starting_balance': self.starting_balance,
            'current_balance': risk.current_balance,
            'session_pnl': risk.session_pnl,
            'session_pnl_pct': risk.session_pnl_pct,
            'total_trades': total_trades,
            'trades_won': state.trades_won,
            'trades_lost': state.trades_lost,
            'win_rate': win_rate,
            'windows_processed': state.windows_processed,
            'signals_generated': state.signals_generated,
            'signal_rate': state.signals_generated / state.windows_processed if state.windows_processed > 0 else 0,
            'risk_level': risk.current_risk_level.value,
            'consecutive_wins': risk.consecutive_wins,
            'consecutive_losses': risk.consecutive_losses,
        }

    def save_results(self):
        """Save trade log and metrics to files."""
        if not self.save_trades or not self.results_dir:
            return

        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Save trades
        trades_file = self.results_dir / 'trades.csv'
        with open(trades_file, 'w') as f:
            f.write("window_id,signal_type,direction,entry_price,size,outcome,pnl,resolution_price,timestamp,reasoning\n")
            for t in self.trades:
                f.write(f"{t.window_id},{t.signal_type},{t.direction},{t.entry_price},"
                       f"{t.size},{t.outcome},{t.pnl},{t.resolution_price},{t.timestamp.isoformat()},{t.reasoning}\n")

        # Save metrics
        metrics_file = self.results_dir / 'metrics.json'
        metrics = self.get_metrics()
        metrics['recent_outcomes'] = [
            {'direction': d, 'won': w} for d, w in self.recent_outcomes
        ]
        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=2)

        logger.info(f"Results saved to {self.results_dir}")

    def get_risk_report(self) -> str:
        """Get risk management report."""
        return self.risk_manager.get_risk_report()


# =============================================================================
# Backtest Support
# =============================================================================

class BacktestRunner:
    """
    Backtest runner for the strategy.

    Simulates trading on historical data to evaluate strategy performance.
    """

    def __init__(
        self,
        strategy: PolymarketSignalStrategy,
        initial_balance: float = 1000.0,
    ):
        """
        Initialize backtest runner.

        Args:
            strategy: Strategy to backtest
            initial_balance: Starting balance
        """
        self.strategy = strategy
        self.initial_balance = initial_balance

    def run(
        self,
        btc_prices: list[float],
        timestamps: list[datetime],
        token_prices: list[float] = None,
        resolution_outcomes: list[bool] = None,
    ) -> dict:
        """
        Run backtest on historical data.

        Args:
            btc_prices: List of BTC prices (5-min windows)
            timestamps: Corresponding timestamps
            token_prices: Optional token prices (if None, generated synthetically)
            resolution_outcomes: Optional actual outcomes (if None, generated from BTC)

        Returns:
            Dict of backtest results
        """
        if len(btc_prices) != len(timestamps):
            raise ValueError("btc_prices and timestamps must have same length")

        # Generate synthetic token prices and outcomes if not provided
        if token_prices is None:
            token_prices = [0.5 + (p - btc_prices[0]) / btc_prices[0] * 10 for p in btc_prices]
            token_prices = [max(0.01, min(0.99, p)) for p in token_prices]

        if resolution_outcomes is None:
            resolution_outcomes = []
            for i in range(len(btc_prices)):
                if i == 0:
                    resolution_outcomes.append(False)
                else:
                    # Outcome = UP if BTC went up in window
                    outcome = btc_prices[i] >= btc_prices[i-1]
                    resolution_outcomes.append(outcome)

        # Run simulation
        equity_curve = [self.initial_balance]
        trades = []

        for i, (btc_price, ts) in enumerate(zip(btc_prices, timestamps)):
            token_price = token_prices[i]

            # Process market data
            signal, position = self.strategy.process_market_data(
                btc_price=btc_price,
                token_price=token_price,
                timestamp=ts,
            )

            # Execute trade if signal
            if signal and position and position.size > 0:
                window_id = self.strategy._get_window_id(ts)
                trade = self.strategy.execute_trade(
                    signal=signal,
                    position_size=position,
                    window_id=window_id,
                    timestamp=ts,
                )

                # Simulate resolution at next window
                if i + 1 < len(resolution_outcomes):
                    won = resolution_outcomes[i]
                    # P&L: win = size * (1 - entry_price), lose = -size * entry_price
                    if won:
                        pnl = position.size * (1 - trade.entry_price)
                    else:
                        pnl = -position.size * trade.entry_price

                    self.strategy.record_resolution(
                        window_id=window_id,
                        won=won,
                        resolution_price=1.0 if won else 0.0,
                        pnl=pnl,
                    )

                    equity_curve.append(self.strategy.risk_manager.current_balance)

        # Calculate metrics
        metrics = self.strategy.get_metrics()

        # Add backtest-specific metrics
        final_balance = equity_curve[-1]
        total_return = (final_balance - self.initial_balance) / self.initial_balance

        # Calculate Sharpe-like metric (simplified)
        returns = [equity_curve[i] / equity_curve[i-1] - 1 for i in range(1, len(equity_curve))]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 0
        sharpe = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0

        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0
        for balance in equity_curve:
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak
            if dd > max_dd:
                max_dd = dd

        metrics.update({
            'final_balance': final_balance,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd * 100,
            'num_windows': len(btc_prices),
            'equity_curve': equity_curve,
        })

        return metrics
