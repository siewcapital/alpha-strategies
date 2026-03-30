"""
strategy.py - Main strategy orchestrator for Multi-Factor Regime-Adaptive strategy.

Ties together:
- Regime detection (indicators.py)
- Factor signals (factor_signals.py)
- Risk management (risk_manager.py)

Provides a clean interface for backtesting and live trading.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

from .indicators import (
    adx, rsi, atr, atr_percentile, regime_score, regime_label
)
from .factor_signals import (
    all_factor_signals, regime_weights, composite_score
)
from .risk_manager import RiskManager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Regime(Enum):
    """Market regime labels."""
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOL = "HIGH_VOL"
    CALM = "CALM"
    UNKNOWN = "UNKNOWN"


@dataclass
class Position:
    """Represents an active position."""
    asset: str
    direction: int          # +1 long, -1 short
    entry_price: float
    size: float              # Dollar value
    entry_time: int          # Bar index
    entry_regime: str
    stops_triggered: List[str] = field(default_factory=list)
    
    def current_pnl(self, current_price: float) -> float:
        """Calculate current PnL."""
        if self.direction > 0:
            return (current_price - self.entry_price) / self.entry_price * self.size
        else:
            return (self.entry_price - current_price) / self.entry_price * self.size
    
    def current_return(self, current_price: float) -> float:
        """Calculate current return fraction."""
        if self.size == 0:
            return 0.0
        return self.current_pnl(current_price) / abs(self.size)


@dataclass
class Trade:
    """Record of a completed trade."""
    asset: str
    direction: int
    entry_price: float
    exit_price: float
    size: float
    entry_time: int
    exit_time: int
    pnl: float
    return_pct: float
    exit_reason: str
    regime: str
    hold_days: int


@dataclass
class StrategySignal:
    """Output signal from the strategy."""
    asset: str
    direction: int           # +1, -1, or 0
    confidence: float         # 0 to 1
    composite_score: float    # -1 to 1
    regime: str
    factor_breakdown: Dict[str, float]
    timestamp: int


class MultiFactorRegimeStrategy:
    """
    Multi-factor regime-adaptive trading strategy.
    
    Core logic:
    1. Detect market regime (TRENDING, RANGING, HIGH_VOL, CALM)
    2. Calculate factor signals (TF, MR, VB, MOM)
    3. Weight factors by regime
    4. Generate composite signal
    5. Size position using risk manager
    6. Monitor for exits
    
    Key features:
    - Adaptive factor weighting based on regime
    - Kelly-based position sizing with vol adjustment
    - Circuit breakers for drawdown protection
    - Multi-asset portfolio with correlation checks
    """
    
    def __init__(
        self,
        # Regime detection params
        adx_period: int = 14,
        rsi_period: int = 14,
        atr_period: int = 14,
        atr_percentile_period: int = 100,
        
        # Factor params
        tf_fast: int = 20,
        tf_slow: int = 50,
        mr_period: int = 20,
        mr_z_threshold: float = 2.0,
        vb_period: int = 20,
        vb_threshold: float = 2.0,
        mom_short: int = 10,
        mom_long: int = 30,
        
        # Signal thresholds
        signal_threshold: float = 0.3,    # Min composite score for entry
        stop_loss_atr: float = 2.0,       # ATR multiples for stop
        trailing_stop_atr: float = 1.5,   # ATR multiples for trailing stop
        time_stop_bars: int = 10,         # Max bars to hold
        
        # Risk params
        max_kelly: float = 0.25,
        max_position_pct: float = 0.20,
        max_leverage: float = 3.0,
        max_drawdown: float = 0.20,
        win_rate: float = 0.55,
        avg_win: float = 0.02,
        avg_loss: float = 0.01,
        
        # Portfolio params
        max_assets: int = 5,
        rebalance_frequency: int = 1,   # Rebalance every N bars
    ):
        # Regime detection
        self.adx_period = adx_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_percentile_period = atr_percentile_period
        
        # Factor params
        self.tf_fast = tf_fast
        self.tf_slow = tf_slow
        self.mr_period = mr_period
        self.mr_z_threshold = mr_z_threshold
        self.vb_period = vb_period
        self.vb_threshold = vb_threshold
        self.mom_short = mom_short
        self.mom_long = mom_long
        
        # Signal params
        self.signal_threshold = signal_threshold
        self.stop_loss_atr = stop_loss_atr
        self.trailing_stop_atr = trailing_stop_atr
        self.time_stop_bars = time_stop_bars
        
        # Risk manager
        self.risk_manager = RiskManager(
            max_kelly_fraction=max_kelly,
            max_position_pct=max_position_pct,
            max_leverage=max_leverage,
            max_drawdown_cutoff=max_drawdown
        )
        
        # Portfolio params
        self.max_assets = max_assets
        self.rebalance_frequency = rebalance_frequency
        
        # Historical params for Kelly
        self.win_rate = win_rate
        self.avg_win = avg_win
        self.avg_loss = avg_loss
        
        # State
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.signals: List[StrategySignal] = []
        self.bar_count = 0
        
        # Cached indicators (for efficiency)
        self._cache: Dict[str, Any] = {}
    
    def _update_cache(self, highs: np.ndarray, lows: np.ndarray,
                      closes: np.ndarray) -> None:
        """Pre-calculate all indicators for efficiency."""
        adx_vals, plus_di, minus_di = adx(highs, lows, closes, self.adx_period)
        rsi_vals = rsi(closes, self.rsi_period)
        atr_vals = atr(highs, lows, closes, self.atr_period)
        atr_pct = atr_percentile(atr_vals, self.atr_percentile_period)
        
        self._cache = {
            "adx": adx_vals,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "rsi": rsi_vals,
            "atr": atr_vals,
            "atr_pct": atr_pct,
            "regime_score": regime_score(adx_vals, rsi_vals, atr_pct),
            "regime_label": regime_label(adx_vals, rsi_vals, atr_pct),
            "factor_signals": all_factor_signals(highs, lows, closes)
        }
    
    def detect_regime(self) -> str:
        """
        Get current market regime.
        
        Returns:
            One of "TRENDING", "RANGING", "HIGH_VOL", "CALM", "UNKNOWN"
        """
        return self._cache.get("regime_label", np.array(["UNKNOWN"]))[self.bar_count]
    
    def generate_signal(self, highs: np.ndarray, lows: np.ndarray,
                        closes: np.ndarray, 
                        asset: str) -> StrategySignal:
        """
        Generate trading signal for an asset.
        
        Args:
            highs, lows, closes: OHLC arrays (assumed to include current bar)
            asset: Asset name
            
        Returns:
            StrategySignal with direction, confidence, regime info
        """
        # Update cache
        self._update_cache(highs, lows, closes)
        
        regime = self.detect_regime()
        weights = regime_weights(regime)
        
        # Get composite score at current bar
        composite, breakdown = composite_score(
            self._cache["factor_signals"],
            weights,
            self.bar_count
        )
        
        # Determine direction
        if abs(composite) < self.signal_threshold:
            direction = 0
        else:
            direction = 1 if composite > 0 else -1
        
        confidence = abs(composite)
        
        signal = StrategySignal(
            asset=asset,
            direction=direction,
            confidence=confidence,
            composite_score=composite,
            regime=regime,
            factor_breakdown=breakdown,
            timestamp=self.bar_count
        )
        
        self.signals.append(signal)
        
        return signal
    
    def should_enter(self, signal: StrategySignal) -> bool:
        """
        Check if we should enter a position based on signal.
        
        Conditions:
        1. Signal direction is not neutral
        2. No existing position in this asset
        3. Below max assets
        4. Trading allowed by risk manager
        """
        if signal.direction == 0:
            return False
        
        if signal.asset in self.positions:
            return False
        
        if len(self.positions) >= self.max_assets:
            return False
        
        allowed, reason = self.risk_manager.is_trading_allowed()
        return allowed
    
    def should_exit(self, position: Position, highs: np.ndarray, lows: np.ndarray,
                   closes: np.ndarray) -> Tuple[bool, str]:
        """
        Check if we should exit a position.
        
        Exit reasons:
        1. Stop loss triggered (ATR-based)
        2. Trailing stop triggered
        3. Time stop reached
        4. Opposite signal
        5. Regime change
        """
        current_price = closes[self.bar_count]
        atr_val = self._cache["atr"][self.bar_count]
        
        # Stop loss
        if atr_val > 0:
            stop_distance = atr_val * self.stop_loss_atr
            if position.direction > 0:  # Long
                if current_price < position.entry_price - stop_distance:
                    return True, "STOP_LOSS"
            else:  # Short
                if current_price > position.entry_price + stop_distance:
                    return True, "STOP_LOSS"
        
        # Trailing stop (only after profit)
        if position.size > 0:
            pnl = position.current_pnl(current_price)
            if pnl > 0:
                trail_distance = atr_val * self.trailing_stop_atr
                if position.direction > 0:  # Long
                    if current_price < position.entry_price + pnl / position.size - trail_distance:
                        return True, "TRAILING_STOP"
                else:  # Short
                    if current_price > position.entry_price - pnl / position.size + trail_distance:
                        return True, "TRAILING_STOP"
        
        # Time stop
        bars_held = self.bar_count - position.entry_time
        if bars_held >= self.time_stop_bars:
            return True, "TIME_STOP"
        
        # Opposite signal
        regime = self.detect_regime()
        if regime != position.entry_regime:
            # Significant regime change - might want to exit
            # But not automatic unless opposite signal
            pass
        
        return False, ""
    
    def enter_position(self, signal: StrategySignal,
                      highs: np.ndarray, lows: np.ndarray,
                      closes: np.ndarray) -> Optional[Position]:
        """
        Enter a new position based on signal.
        
        Args:
            signal: StrategySignal from generate_signal()
            highs, lows, closes: OHLC arrays
            
        Returns:
            Position object, or None if not entered
        """
        if not self.should_enter(signal):
            return None
        
        current_price = closes[self.bar_count]
        atr_val = self._cache["atr"][self.bar_count]
        
        # Calculate realized vol (annualized)
        returns = np.diff(closes) / closes[:-1]
        realized_vol = np.std(returns[-self.risk_manager.vol_lookback:]) * np.sqrt(252) \
                        if len(returns) >= self.risk_manager.vol_lookback else 0.15
        
        # Calculate position size
        position_value, breakdown = self.risk_manager.calculate_position_size(
            capital=self.risk_manager.current_capital,
            price=current_price,
            signal_strength=signal.confidence,
            direction=signal.direction,
            realized_vol=realized_vol,
            historical_win_rate=self.win_rate,
            historical_avg_win=self.avg_win,
            historical_avg_loss=self.avg_loss
        )
        
        if position_value <= 0:
            logger.info(f"Position size is zero or negative, skipping entry")
            return None
        
        position = Position(
            asset=signal.asset,
            direction=signal.direction,
            entry_price=current_price,
            size=abs(position_value),
            entry_time=self.bar_count,
            entry_regime=signal.regime
        )
        
        self.positions[signal.asset] = position
        
        logger.info(
            f"ENTER {signal.asset}: {signal.direction} "
            f"@ {current_price:.4f}, size=${position_value:.2f}, "
            f"regime={signal.regime}, score={signal.composite_score:.3f}"
        )
        
        return position
    
    def exit_position(self, position: Position,
                     highs: np.ndarray, lows: np.ndarray,
                     closes: np.ndarray,
                     reason: str) -> Trade:
        """
        Exit an existing position.
        
        Args:
            position: Position to close
            highs, lows, closes: OHLC arrays
            reason: Exit reason string
            
        Returns:
            Trade record
        """
        current_price = closes[self.bar_count]
        bars_held = self.bar_count - position.entry_time
        
        pnl = position.current_pnl(current_price)
        return_pct = pnl / position.size if position.size > 0 else 0
        
        trade = Trade(
            asset=position.asset,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=current_price,
            size=position.size,
            entry_time=position.entry_time,
            exit_time=self.bar_count,
            pnl=pnl,
            return_pct=return_pct,
            exit_reason=reason,
            regime=position.entry_regime,
            hold_days=bars_held
        )
        
        self.trades.append(trade)
        
        # Update risk manager
        self.risk_manager.record_trade_result(position.asset, return_pct)
        
        # Update capital
        self.risk_manager.update_capital(
            self.risk_manager.current_capital + pnl
        )
        
        # Remove position
        del self.positions[position.asset]
        
        logger.info(
            f"EXIT {position.asset}: {reason} "
            f"@ {current_price:.4f}, pnl=${pnl:.2f}, "
            f"return={return_pct:.2%}, bars={bars_held}"
        )
        
        return trade
    
    def on_bar(self, highs: np.ndarray, lows: np.ndarray,
               closes: np.ndarray, assets: List[str]) -> List[Trade]:
        """
        Process a new bar of data.
        
        This is the main method called each time step.
        
        Args:
            highs, lows, closes: OHLC arrays for each asset
            assets: List of asset names
            
        Returns:
            List of completed trades this bar
        """
        completed_trades = []
        
        # Update bar count (last index)
        self.bar_count = len(closes[0]) - 1 if isinstance(closes, list) else len(closes) - 1
        
        # Check existing positions for exits
        for asset in list(self.positions.keys()):
            position = self.positions[asset]
            
            # Get the OHLC for this specific asset
            asset_idx = assets.index(asset) if isinstance(closes, list) else 0
            asset_highs = closes if not isinstance(closes, list) else highs[asset_idx]
            asset_lows = closes if not isinstance(closes, list) else lows[asset_idx]
            asset_closes = closes if not isinstance(closes, list) else closes[asset_idx]
            
            should_exit, reason = self.should_exit(
                position, asset_highs, asset_lows, asset_closes
            )
            
            if should_exit:
                trade = self.exit_position(
                    position, asset_highs, asset_lows, asset_closes, reason
                )
                completed_trades.append(trade)
        
        # Generate signals for assets without positions
        for asset in assets:
            if asset in self.positions:
                continue
            
            # Get OHLC for this asset
            asset_idx = assets.index(asset) if isinstance(closes, list) else 0
            asset_highs = closes if not isinstance(closes, list) else highs[asset_idx]
            asset_lows = closes if not isinstance(closes, list) else lows[asset_idx]
            asset_closes = closes if not isinstance(closes, list) else closes[asset_idx]
            
            # Generate signal
            signal = self.generate_signal(asset_highs, asset_lows, asset_closes, asset)
            
            # Try to enter
            self.enter_position(signal, asset_highs, asset_lows, asset_closes)
        
        # Rebalance check
        if self.bar_count % self.rebalance_frequency == 0:
            self._rebalance(closes, assets)
        
        return completed_trades
    
    def _rebalance(self, closes: np.ndarray, assets: List[str]) -> None:
        """
        Rebalance positions based on current signals.
        
        Called periodically to adjust position sizes.
        """
        # For now, just log rebalance opportunity
        pass
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current strategy performance metrics.
        
        Returns:
            Dictionary of metrics
        """
        if not self.trades:
            return {
                "total_trades": 0,
                "open_positions": len(self.positions),
                "current_capital": self.risk_manager.current_capital
            }
        
        pnls = [t.pnl for t in self.trades]
        returns = [t.return_pct for t in self.trades]
        
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        return {
            "total_trades": len(self.trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(self.trades) if self.trades else 0,
            "total_pnl": sum(pnls),
            "avg_win": np.mean(wins) if wins else 0,
            "avg_loss": np.mean(losses) if losses else 0,
            "largest_win": max(pnls) if pnls else 0,
            "largest_loss": min(pnls) if pnls else 0,
            "open_positions": len(self.positions),
            "current_capital": self.risk_manager.current_capital,
            "current_drawdown": self.risk_manager.current_drawdown
        }
    
    def reset(self) -> None:
        """Reset strategy state for fresh backtest."""
        self.positions = {}
        self.trades = []
        self.signals = []
        self.bar_count = 0
        self._cache = {}
        self.risk_manager = RiskManager(
            max_kelly_fraction=self.risk_manager.max_kelly_fraction,
            max_position_pct=self.risk_manager.max_position_pct,
            max_leverage=self.risk_manager.max_leverage,
            max_drawdown_cutoff=self.risk_manager.max_drawdown_cutoff
        )
