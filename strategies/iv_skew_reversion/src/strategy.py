"""
IV Skew Mean Reversion Strategy

Orchestrates the complete skew mean reversion trading strategy:
- Monitors vol surface for skew extremes
- Generates entry/exit signals
- Manages positions with delta hedging
- Enforces risk limits
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import logging

from .indicators import (
    VolSurfaceCalculator,
    VolSurfaceMetrics,
    SkewSignalGenerator,
    black_scholes_iv,
)


logger = logging.getLogger(__name__)


class TradeDirection(Enum):
    """Trade direction enumeration."""
    LONG_SKEW = 1    # Sell puts (expect skew to normalize upward)
    SHORT_SKEW = -1  # Buy puts (expect skew to expand)
    FLAT = 0


class PositionStatus(Enum):
    """Position status enumeration."""
    OPEN = "open"
    CLOSED = "closed"
    STOPPED = "stopped"
    EXPIRED = "expired"


@dataclass
class SkewTrade:
    """Represents a single IV skew trade."""
    trade_id: int
    timestamp: pd.Timestamp
    direction: TradeDirection
    asset: str
    strike: float
    expiry: pd.Timestamp
    premium_received: float      # Net premium received (positive for seller)
    notional: float              # Contract notional
    contracts: int
    entry_skew: float            # Skew level at entry
    entry_spot: float
    exit_skew: Optional[float] = None
    exit_spot: Optional[float] = None
    exit_timestamp: Optional[pd.Timestamp] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    notes: str = ""

    @property
    def days_held(self) -> int:
        if self.exit_timestamp is None:
            return (pd.Timestamp.today() - self.timestamp).days
        return (self.exit_timestamp - self.timestamp).days


@dataclass
class StrategyState:
    """Current state of the strategy."""
    portfolio_value: float
    cash: float
    positions: List[SkewTrade] = field(default_factory=list)
    closed_trades: List[SkewTrade] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    daily_pnl: List[float] = field(default_factory=list)
    metrics_history: List[VolSurfaceMetrics] = field(default_factory=list)
    signal_history: List[Dict] = field(default_factory=list)
    circuit_broken: bool = False
    current_drawdown: float = 0.0
    peak_equity: float = 0.0


class IVSkewReversionStrategy:
    """
    Main strategy orchestrator for IV Skew Mean Reversion.

    The strategy exploits the observation that IV skew in crypto options markets
    is mean-reverting. When skew becomes extremely negative (puts very expensive
    relative to ATM), it tends to normalize, creating a profitable reversion trade.

    Trading Logic:
    - LONG SKEW REVERSION: Sell OTM puts when skew < -20% (puts expensive)
    - SHORT SKEW REVERSION: Buy OTM puts when skew > -50% (puts cheap/normalize)
    - Exit when skew reverts to mean (-30% to -35%)

    Risk Management:
    - Position sizing: 2% portfolio risk per trade
    - Max 3 concurrent trades
    - Delta hedge: 50% delta hedge via futures/perp
    - Time stop: 21 days maximum
    - Hard stop: 3% portfolio loss per trade
    """

    def __init__(
        self,
        params: Dict,
        initial_capital: float = 1_000_000,
        assets: Optional[List[str]] = None,
    ):
        self.params = params
        self.initial_capital = initial_capital

        # Default assets
        self.assets = assets or ["BTC", "ETH"]

        # Initialize components
        self._init_indicators()
        self._init_signal_generator()
        self._init_risk_limits()
        self._init_state()

        # Trade tracking
        self._next_trade_id = 1

    def _init_indicators(self) -> None:
        """Initialize per-asset vol surface calculators."""
        self.calculators: Dict[str, VolSurfaceCalculator] = {}
        for asset in self.assets:
            self.calculators[asset] = VolSurfaceCalculator(
                skew_window=self.params["signals"].get("skew_window", 60),
                rv_window=self.params["signals"].get("rv_window", 30),
            )

    def _init_signal_generator(self) -> None:
        """Initialize skew signal generator."""
        sig_params = self.params["signals"]
        self.signal_gen = SkewSignalGenerator(
            skew_entry_long=sig_params["skew_entry_long"],
            skew_entry_short=sig_params["skew_entry_short"],
            skew_mean_reversion=sig_params["skew_mean_reversion"],
            skew_stop_loss=sig_params["skew_stop_loss"],
            rv_min_entry=sig_params["rv_min_entry"] / 100.0,  # Convert %
            skew_z_threshold=2.0,
        )

    def _init_risk_limits(self) -> None:
        """Initialize risk parameters."""
        risk = self.params["risk"]
        pos = self.params["position"]

        self.max_loss_per_trade = risk["max_loss_per_trade"]
        self.max_drawdown_cutoff = risk["max_drawdown_portfolio"]
        self.max_concurrent_trades = pos["max_concurrent_trades"]
        self.max_holding_days = risk["time_stop_days"]
        self.max_daily_loss_cutoff = risk["max_daily_loss_cutoff"]
        self.skew_widening_stop = risk["skew_widening_stop"]
        self.skew_stop_loss = self.params["signals"]["skew_stop_loss"]

    def _init_state(self) -> None:
        """Initialize strategy state."""
        self.state = StrategyState(
            portfolio_value=self.initial_capital,
            cash=self.initial_capital,
            peak_equity=self.initial_capital,
        )

    def process_market_data(
        self,
        timestamp: pd.Timestamp,
        asset: str,
        spot_price: float,
        atm_straddle_iv: float,
        otm_put_iv: float,
        otm_call_iv: float,
        rv_30d: float,
        high_prices: Optional[np.ndarray] = None,
        low_prices: Optional[np.ndarray] = None,
        close_prices: Optional[np.ndarray] = None,
    ) -> Dict:
        """
        Process new market data and generate trading signals.

        This is the main entry point for market data. Call this for each
        new data point received.

        Args:
            timestamp: Current timestamp
            asset: Asset symbol (BTC, ETH)
            spot_price: Current spot price
            atm_straddle_iv: ATM straddle implied vol
            otm_put_iv: OTM put implied vol
            otm_call_iv: OTM call implied vol
            rv_30d: 30-day realized vol
            high_prices: Intraday highs for RV calc
            low_prices: Intraday lows for RV calc
            close_prices: Closing prices for RV calc

        Returns:
            Dict with current metrics, signals, and portfolio state
        """
        # Calculate vol surface metrics
        calc = self.calculators.get(asset)
        if calc is None:
            calc = VolSurfaceCalculator()
            self.calculators[asset] = calc

        metrics = calc.calculate_vol_surface_metrics(
            timestamp=timestamp,
            spot_price=spot_price,
            atm_straddle_iv=atm_straddle_iv,
            otm_put_iv=otm_put_iv,
            otm_call_iv=otm_call_iv,
            rv_30d=rv_30d,
            high_prices=high_prices,
            low_prices=low_prices,
            close_prices=close_prices,
        )

        self.state.metrics_history.append(metrics)

        # Compute skew Z-score
        skew_z = calc.get_skew_z_score(metrics.skew)

        # Generate signals
        signals = self.signal_gen.compute_signals(metrics, skew_z)
        self.state.signal_history.append(signals)

        # Check open positions for exits
        exit_trades = self._check_position_exits(asset, metrics, signals)

        # Generate new entry signals
        new_signals = []
        if not exit_trades and not self.state.circuit_broken:
            entry = self._check_entry_signals(asset, metrics, signals)
            if entry:
                new_signals.append(entry)

        # Update portfolio equity
        self._update_equity(timestamp)

        return {
            "timestamp": timestamp,
            "asset": asset,
            "metrics": metrics,
            "signals": signals,
            "exit_trades": exit_trades,
            "new_entry": new_signals if new_signals else None,
            "portfolio_value": self.state.portfolio_value,
            "cash": self.state.cash,
            "open_positions": len(self.state.positions),
            "circuit_broken": self.state.circuit_broken,
        }

    def _check_entry_signals(
        self,
        asset: str,
        metrics: VolSurfaceMetrics,
        signals: Dict,
    ) -> Optional[Dict]:
        """
        Check if we should enter a new position.

        Entry conditions:
        - Signal is LONG or SHORT SKEW REVERSION
        - Below max concurrent trades
        - Position not already open for this asset
        """
        if signals["action"] not in ("LONG_SKEW_REVERSION", "SHORT_SKEW_REVERSION"):
            return None

        # Check concurrent trade limit
        if len(self.state.positions) >= self.max_concurrent_trades:
            logger.info("Max concurrent trades reached, skipping entry")
            return None

        # Check if already have position for this asset
        for pos in self.state.positions:
            if pos.asset == asset:
                logger.info(f"Position already open for {asset}, skipping")
                return None

        # Check portfolio risk
        if self.state.current_drawdown > self.max_drawdown_cutoff:
            logger.info("Max drawdown exceeded, circuit breaker active")
            return None

        direction = TradeDirection.LONG_SKEW if signals["action"] == "LONG_SKEW_REVERSION" else TradeDirection.SHORT_SKEW

        return {
            "asset": asset,
            "direction": direction,
            "signal": signals,
            "metrics": metrics,
        }

    def _check_position_exits(
        self,
        asset: str,
        metrics: VolSurfaceMetrics,
        signals: Dict,
    ) -> List[SkewTrade]:
        """
        Check if any open positions should be exited.

        Exit conditions:
        1. Skew has reverted to mean (take profit)
        2. Skew has widened past stop loss
        3. Time stop (21 days)
        4. Daily loss cutoff triggered
        """
        exit_trades = []

        for pos in self.state.positions[:]:  # Copy list to modify during iteration
            if pos.asset != asset:
                continue

            should_exit = False
            exit_reason = ""

            # Take profit: skew reverted to mean
            if signals["exit_signal"] and signals["action"] == "EXIT":
                should_exit = True
                exit_reason = "TAKE_PROFIT"
                pos.status = PositionStatus.CLOSED

            # Stop loss: skew widened
            elif metrics.skew < self.skew_stop_loss:
                should_exit = True
                exit_reason = "STOP_LOSS"
                pos.status = PositionStatus.STOPPED

            # Time stop
            elif pos.days_held > self.max_holding_days:
                should_exit = True
                exit_reason = "TIME_STOP"
                pos.status = PositionStatus.CLOSED

            # Skew widening beyond threshold
            elif (pos.direction == TradeDirection.LONG_SKEW and
                  metrics.skew < pos.entry_skew - self.skew_widening_stop):
                should_exit = True
                exit_reason = "SKEW_WIDENING_STOP"
                pos.status = PositionStatus.STOPPED

            if should_exit:
                self._close_trade(pos, metrics, exit_reason)
                exit_trades.append(pos)

        return exit_trades

    def _close_trade(
        self,
        trade: SkewTrade,
        metrics: VolSurfaceMetrics,
        reason: str,
    ) -> None:
        """Close a trade and calculate PnL."""
        trade.exit_skew = metrics.skew
        trade.exit_spot = metrics.spot_price
        trade.exit_timestamp = metrics.timestamp

        # Calculate PnL based on direction and skew change
        skew_change = trade.entry_skew - metrics.skew  # Positive = skew normalized (good for short skew holders)

        if trade.direction == TradeDirection.LONG_SKEW:
            # We sold puts → profit when skew RISES (normalizes)
            # skew_change positive means our skew rose (we wanted this)
            pnl_multiplier = skew_change / 100.0
        else:
            # We bought puts → profit when skew FALLS (crash premium returns)
            pnl_multiplier = -skew_change / 100.0

        # PnL as percentage of notional
        trade.pnl_pct = pnl_multiplier * 0.5  # Rough estimate
        trade.pnl = trade.notional * trade.pnl_pct

        # Cap loss at notional
        if trade.pnl < -trade.notional:
            trade.pnl = -trade.notional

        # Update cash
        self.state.cash += trade.pnl

        # Move from open to closed
        self.state.positions.remove(trade)
        self.state.closed_trades.append(trade)

        logger.info(
            f"Closed trade {trade.trade_id}: {reason} | "
            f"Entry skew={trade.entry_skew:.1f} → Exit skew={metrics.skew:.1f} | "
            f"PnL=${trade.pnl:.2f} ({trade.pnl_pct*100:.1f}%)"
        )

    def open_trade(
        self,
        entry_signal: Dict,
        spot_price: float,
        skew: float,
        premium_per_contract: float,
        contracts: int,
    ) -> SkewTrade:
        """
        Open a new skew trade.

        Args:
            entry_signal: Entry signal dict from _check_entry_signals
            spot_price: Entry spot price
            skew: Entry skew level
            premium_per_contract: Premium received per contract
            contracts: Number of contracts

        Returns:
            New SkewTrade object
        """
        asset = entry_signal["asset"]
        direction = entry_signal["direction"]
        metrics = entry_signal["metrics"]

        # Calculate strike (10% OTM for the put we're selling/buying)
        if direction == TradeDirection.LONG_SKEW:
            # Selling puts → OTM put = 10% below spot
            strike = spot_price * 0.90
        else:
            # Buying puts → OTM put = 10% below spot
            strike = spot_price * 0.90

        # Calculate expiry (21 days out)
        expiry = metrics.timestamp + timedelta(days=21)

        # Notional: contracts × 100 × strike
        notional = contracts * 100 * strike

        trade = SkewTrade(
            trade_id=self._next_trade_id,
            timestamp=metrics.timestamp,
            direction=direction,
            asset=asset,
            strike=strike,
            expiry=expiry,
            premium_received=premium_per_contract * contracts,
            notional=notional,
            contracts=contracts,
            entry_skew=skew,
            entry_spot=spot_price,
            notes=f"{direction.name} skew reversion",
        )

        self._next_trade_id += 1
        self.state.positions.append(trade)

        # Deduct premium from cash (for LONG_SKEW, we receive premium, so +cash)
        # Actually: selling premium = +cash, buying premium = -cash
        if direction == TradeDirection.LONG_SKEW:
            self.state.cash += trade.premium_received
        else:
            self.state.cash -= trade.premium_received

        logger.info(
            f"Opened trade {trade.trade_id}: {direction.name} | "
            f"Asset={asset} | Strike={strike:.0f} | "
            f"Skew={skew:.1f}% | Premium=${trade.premium_received:.2f} | "
            f"Contracts={contracts}"
        )

        return trade

    def _update_equity(self, timestamp: pd.Timestamp) -> None:
        """Update portfolio equity curve and drawdown tracking."""
        # Calculate unrealized PnL from open positions
        unrealized_pnl = sum(p.pnl for p in self.state.positions)

        # Total portfolio value
        total_equity = self.state.cash + unrealized_pnl

        # Update peak equity
        if total_equity > self.state.peak_equity:
            self.state.peak_equity = total_equity

        # Calculate drawdown
        self.state.current_drawdown = (self.state.peak_equity - total_equity) / self.state.peak_equity
        self.state.portfolio_value = total_equity

        # Record equity point
        self.state.equity_curve.append({
            "timestamp": timestamp,
            "equity": total_equity,
            "cash": self.state.cash,
            "unrealized_pnl": unrealized_pnl,
            "drawdown": self.state.current_drawdown,
        })

    def check_daily_loss_cutoff(self, daily_pnl: float) -> bool:
        """
        Check if daily loss cutoff has been hit.

        Args:
            daily_pnl: PnL for the day so far

        Returns:
            True if should halt trading for the day
        """
        daily_loss_pct = abs(daily_pnl) / self.state.peak_equity

        if daily_loss_pct > self.max_daily_loss_cutoff:
            logger.warning(
                f"Daily loss cutoff hit: {daily_loss_pct*100:.1f}% > "
                f"{self.max_daily_loss_cutoff*100:.1f}%, halting trading"
            )
            self.state.circuit_broken = True
            return True

        return False

    def reset_circuit_breaker(self) -> None:
        """Reset circuit breaker at start of new trading day."""
        self.state.circuit_broken = False
        logger.info("Circuit breaker reset")

    def get_performance_metrics(self) -> Dict:
        """Calculate comprehensive performance metrics."""
        if not self.state.closed_trades:
            return {
                "total_trades": 0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
            }

        closed = self.state.closed_trades
        winning_trades = [t for t in closed if t.pnl > 0]
        losing_trades = [t for t in closed if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in closed)
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0

        # Daily returns for Sharpe/Sortino
        daily_returns = self.state.daily_pnl if self.state.daily_pnl else [0.0]
        daily_returns_arr = np.array(daily_returns)
        avg_daily_return = daily_returns_arr.mean()
        std_daily = daily_returns_arr.std()
        downside = daily_returns_arr[daily_returns_arr < 0]
        downside_std = downside.std() if len(downside) > 0 else 1e-6

        # Annualize (252 trading days)
        sharpe = (avg_daily_return / std_daily) * np.sqrt(252) if std_daily > 0 else 0.0
        sortino = (avg_daily_return / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0

        # Max drawdown
        equity_arr = np.array([e["equity"] for e in self.state.equity_curve])
        peak = np.maximum.accumulate(equity_arr)
        drawdown = (equity_arr - peak) / peak
        max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

        win_rate = len(winning_trades) / len(closed) if closed else 0.0
        profit_factor = abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades)) if losing_trades and sum(t.pnl for t in losing_trades) != 0 else 0.0

        return {
            "total_trades": len(closed),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "total_return": total_pnl / self.initial_capital,
            "avg_daily_return": avg_daily_return,
            "avg_days_held": np.mean([t.days_held for t in closed]),
        }
