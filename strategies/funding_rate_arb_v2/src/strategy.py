"""
Funding Rate Arbitrage Strategy V2

Production-ready implementation of cross-exchange funding rate arbitrage
with predictive modeling and strict risk controls.

Author: ATLAS
Date: March 30, 2026
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import yaml

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Types of trading signals."""
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT = "exit"
    HOLD = "hold"


class PositionSide(Enum):
    """Position side."""
    LONG = "long"
    SHORT = "short"


@dataclass
class FundingPrediction:
    """Predicted funding rate for next interval."""
    exchange: str
    symbol: str
    predicted_rate: float
    confidence: float  # 0-1
    persistence_score: float  # Mean reversion half-life indicator
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "predicted_rate": self.predicted_rate,
            "confidence": self.confidence,
            "persistence_score": self.persistence_score,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class FundingOpportunity:
    """Cross-exchange funding rate opportunity."""
    symbol: str
    long_exchange: str
    short_exchange: str
    long_funding: FundingPrediction
    short_funding: FundingPrediction
    spread_annualized: float
    entry_threshold_met: bool
    timestamp: datetime
    
    @property
    def spread_8h(self) -> float:
        """Raw 8-hour funding spread."""
        return self.short_funding.predicted_rate - self.long_funding.predicted_rate
    
    @property
    def persistence_min(self) -> float:
        """Minimum persistence score between exchanges."""
        return min(self.long_funding.persistence_score, self.short_funding.persistence_score)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "long_exchange": self.long_exchange,
            "short_exchange": self.short_exchange,
            "long_funding": self.long_funding.to_dict(),
            "short_funding": self.short_funding.to_dict(),
            "spread_annualized": self.spread_annualized,
            "spread_8h": self.spread_8h,
            "entry_threshold_met": self.entry_threshold_met,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class Signal:
    """Trading signal with metadata."""
    signal_type: SignalType
    symbol: str
    exchange: str
    side: PositionSide
    size_usd: float
    leverage: float
    confidence: float
    expected_funding: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "side": self.side.value,
            "size_usd": self.size_usd,
            "leverage": self.leverage,
            "confidence": self.confidence,
            "expected_funding": self.expected_funding,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class Position:
    """Active position tracking."""
    position_id: str
    symbol: str
    long_exchange: str
    short_exchange: str
    long_size_usd: float
    short_size_usd: float
    leverage: float
    entry_time: datetime
    entry_spread: float
    current_pnl: float = 0.0
    funding_earned: float = 0.0
    status: str = "open"
    
    @property
    def notional_exposure(self) -> float:
        """Total notional exposure (should be ~0 for delta-neutral)."""
        return abs(self.long_size_usd - self.short_size_usd)
    
    @property
    def hold_time_hours(self) -> float:
        """Hours since entry."""
        return (datetime.utcnow() - self.entry_time).total_seconds() / 3600


@dataclass
class Portfolio:
    """Portfolio state tracking."""
    cash: float
    positions: List[Position] = field(default_factory=list)
    exchange_balances: Dict[str, float] = field(default_factory=dict)
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    
    @property
    def total_exposure(self) -> float:
        """Total notional exposure across all positions."""
        return sum(p.long_size_usd + p.short_size_usd for p in self.positions)
    
    @property
    def margin_utilization(self) -> float:
        """Percentage of capital deployed."""
        if self.cash <= 0:
            return 1.0
        return self.total_exposure / (self.cash + self.total_exposure)


class FundingAnalyzer:
    """
    Analyzes funding rates and predicts next-period funding using
    Ornstein-Uhlenbeck process for mean reversion modeling.
    """
    
    def __init__(self, lookback_window: int = 30, min_observations: int = 10):
        self.lookback_window = lookback_window
        self.min_observations = min_observations
        self.funding_history: Dict[Tuple[str, str], pd.Series] = {}
        
    def update_funding_history(self, exchange: str, symbol: str, 
                               timestamp: datetime, funding_rate: float):
        """Update funding rate history for an exchange-symbol pair."""
        key = (exchange, symbol)
        
        if key not in self.funding_history:
            self.funding_history[key] = pd.Series(dtype=float)
        
        self.funding_history[key][timestamp] = funding_rate
        
        # Keep only lookback window
        cutoff = timestamp - timedelta(days=self.lookback_window)
        self.funding_history[key] = self.funding_history[key][
            self.funding_history[key].index > cutoff
        ]
    
    def calculate_persistence(self, funding_series: pd.Series) -> float:
        """
        Calculate funding rate persistence using AR(1) coefficient.
        Higher values indicate slower mean reversion (more persistent).
        
        Returns persistence score between 0 and 1.
        """
        if len(funding_series) < self.min_observations:
            return 0.5  # Neutral default
        
        # Calculate AR(1) coefficient
        y = funding_series.values[1:]
        x = funding_series.values[:-1]
        
        # Add constant for regression
        x_with_const = np.column_stack([np.ones(len(x)), x])
        
        try:
            beta = np.linalg.lstsq(x_with_const, y, rcond=None)[0]
            ar_coeff = beta[1]
            
            # Convert to persistence score (0-1)
            # AR(1) near 1 = high persistence, near 0 = low persistence
            persistence = max(0.0, min(1.0, ar_coeff))
            return persistence
        except (np.linalg.LinAlgError, ValueError):
            return 0.5
    
    def estimate_ou_parameters(self, funding_series: pd.Series) -> Tuple[float, float, float]:
        """
        Estimate Ornstein-Uhlenbeck parameters using least squares.
        
        dX(t) = θ(μ - X(t))dt + σdW(t)
        
        Returns: (theta, mu, sigma)
        """
        if len(funding_series) < self.min_observations:
            return 0.1, 0.0, 0.01  # Default parameters
        
        dt = 1.0  # Assume uniform spacing
        x = funding_series.values[:-1]
        y = funding_series.values[1:]
        
        # Linear regression: y = a + b*x
        x_with_const = np.column_stack([np.ones(len(x)), x])
        
        try:
            beta = np.linalg.lstsq(x_with_const, y, rcond=None)[0]
            a, b = beta[0], beta[1]
            
            # Convert to OU parameters
            theta = -np.log(b) / dt if b > 0 else 0.1
            mu = a / (1 - b) if b != 1 else 0.0
            
            # Estimate sigma from residuals
            residuals = y - (a + b * x)
            sigma = np.std(residuals) / np.sqrt(dt) if len(residuals) > 1 else 0.01
            
            return theta, mu, sigma
        except (np.linalg.LinAlgError, ValueError):
            return 0.1, 0.0, 0.01
    
    def predict_funding_rate(self, exchange: str, symbol: str,
                            current_premium: Optional[float] = None) -> FundingPrediction:
        """
        Predict funding rate for next interval using OU process.
        
        Args:
            exchange: Exchange name
            symbol: Trading pair symbol
            current_premium: Current premium index (if available)
            
        Returns:
            FundingPrediction with predicted rate and confidence
        """
        key = (exchange, symbol)
        
        if key not in self.funding_history or len(self.funding_history[key]) < 3:
            # Not enough history, use neutral prediction
            return FundingPrediction(
                exchange=exchange,
                symbol=symbol,
                predicted_rate=0.0,
                confidence=0.3,
                persistence_score=0.5,
                timestamp=datetime.utcnow()
            )
        
        funding_series = self.funding_history[key]
        current_funding = funding_series.iloc[-1]
        
        # Estimate OU parameters
        theta, mu, sigma = self.estimate_ou_parameters(funding_series)
        
        # Calculate persistence score
        persistence = self.calculate_persistence(funding_series)
        
        # OU prediction: E[X(t+1)] = X(t) * exp(-θ) + μ * (1 - exp(-θ))
        dt = 1.0
        mean_reversion_factor = np.exp(-theta * dt)
        predicted_funding = current_funding * mean_reversion_factor + mu * (1 - mean_reversion_factor)
        
        # Incorporate premium if available (strong signal for next funding)
        if current_premium is not None:
            # Premium typically has 0.7-0.9 correlation with next funding
            premium_weight = 0.3
            predicted_funding = (1 - premium_weight) * predicted_funding + premium_weight * current_premium
            confidence = 0.7 + 0.2 * persistence
        else:
            confidence = 0.5 + 0.3 * persistence
        
        return FundingPrediction(
            exchange=exchange,
            symbol=symbol,
            predicted_rate=predicted_funding,
            confidence=min(0.95, confidence),
            persistence_score=persistence,
            timestamp=datetime.utcnow()
        )
    
    def calculate_cross_exchange_spread(self, predictions: List[FundingPrediction],
                                       min_annualized_spread: float = 0.15) -> List[FundingOpportunity]:
        """
        Calculate funding rate spreads between exchanges.
        
        Args:
            predictions: List of funding predictions across exchanges
            min_annualized_spread: Minimum annualized spread to consider (as decimal)
            
        Returns:
            List of funding opportunities sorted by spread
        """
        opportunities = []
        
        # Group by symbol
        by_symbol: Dict[str, List[FundingPrediction]] = {}
        for pred in predictions:
            if pred.symbol not in by_symbol:
                by_symbol[pred.symbol] = []
            by_symbol[pred.symbol].append(pred)
        
        # Calculate all pairwise spreads
        for symbol, preds in by_symbol.items():
            if len(preds) < 2:
                continue
            
            for i, pred_i in enumerate(preds):
                for pred_j in preds[i+1:]:
                    # Calculate spread in both directions
                    spread_ij = pred_j.predicted_rate - pred_i.predicted_rate
                    spread_ji = -spread_ij
                    
                    # Annualize (3 periods per day * 365 days)
                    annualized_ij = spread_ij * 3 * 365
                    annualized_ji = spread_ji * 3 * 365
                    
                    # Create opportunity if spread exceeds threshold
                    if annualized_ij > min_annualized_spread:
                        opportunities.append(FundingOpportunity(
                            symbol=symbol,
                            long_exchange=pred_i.exchange,
                            short_exchange=pred_j.exchange,
                            long_funding=pred_i,
                            short_funding=pred_j,
                            spread_annualized=annualized_ij,
                            entry_threshold_met=True,
                            timestamp=datetime.utcnow()
                        ))
                    
                    if annualized_ji > min_annualized_spread:
                        opportunities.append(FundingOpportunity(
                            symbol=symbol,
                            long_exchange=pred_j.exchange,
                            short_exchange=pred_i.exchange,
                            long_funding=pred_j,
                            short_funding=pred_i,
                            spread_annualized=annualized_ji,
                            entry_threshold_met=True,
                            timestamp=datetime.utcnow()
                        ))
        
        # Sort by spread descending
        opportunities.sort(key=lambda x: x.spread_annualized, reverse=True)
        return opportunities


class SignalGenerator:
    """
    Generates entry and exit signals based on funding analysis.
    Implements the predictive funding arbitrage logic.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.entry_threshold = config.get("entry_threshold", 0.15)  # 15% annualized
        self.exit_threshold = config.get("exit_threshold", 0.05)    # 5% annualized
        self.min_persistence = config.get("min_persistence", 0.7)
        self.max_hold_hours = config.get("max_hold_hours", 48)
        self.flip_threshold = config.get("flip_threshold", 0.3)
        
        # Track recent funding flips for risk management
        self.funding_flip_history: Dict[str, List[datetime]] = {}
    
    def generate_entry_signals(self, opportunities: List[FundingOpportunity],
                              portfolio: Portfolio) -> List[Signal]:
        """
        Generate entry signals from funding opportunities.
        
        Entry criteria (ALL must be met):
        1. Predicted spread > entry_threshold (annualized)
        2. Persistence score > min_persistence
        3. Not already in position for this symbol
        4. Portfolio heat < max utilization
        """
        signals = []
        
        # Check if we're already at position limits
        active_symbols = {p.symbol for p in portfolio.positions if p.status == "open"}
        max_positions = self.config.get("max_positions", 5)
        
        if len(active_symbols) >= max_positions:
            logger.info(f"At max positions ({max_positions}), skipping entry signals")
            return signals
        
        max_utilization = self.config.get("max_utilization", 0.5)
        if portfolio.margin_utilization > max_utilization:
            logger.info(f"Margin utilization {portfolio.margin_utilization:.2%} > {max_utilization:.2%}, skipping entries")
            return signals
        
        for opp in opportunities:
            # Skip if already in position for this symbol
            if opp.symbol in active_symbols:
                continue
            
            # Entry criteria check
            if not self._check_entry_criteria(opp):
                continue
            
            # Calculate position size
            position_size = self._calculate_position_size(opp, portfolio)
            
            if position_size <= 0:
                continue
            
            # Generate entry signals (both legs)
            leverage = self.config.get("default_leverage", 2.0)
            
            # Long leg
            signals.append(Signal(
                signal_type=SignalType.ENTRY_LONG,
                symbol=opp.symbol,
                exchange=opp.long_exchange,
                side=PositionSide.LONG,
                size_usd=position_size,
                leverage=leverage,
                confidence=opp.long_funding.confidence,
                expected_funding=opp.long_funding.predicted_rate,
                metadata={
                    "opportunity": opp.to_dict(),
                    "leg": "long",
                    "spread_annualized": opp.spread_annualized
                }
            ))
            
            # Short leg
            signals.append(Signal(
                signal_type=SignalType.ENTRY_SHORT,
                symbol=opp.symbol,
                exchange=opp.short_exchange,
                side=PositionSide.SHORT,
                size_usd=position_size,
                leverage=leverage,
                confidence=opp.short_funding.confidence,
                expected_funding=opp.short_funding.predicted_rate,
                metadata={
                    "opportunity": opp.to_dict(),
                    "leg": "short",
                    "spread_annualized": opp.spread_annualized
                }
            ))
            
            # Track this symbol as having active signals
            active_symbols.add(opp.symbol)
            
            # Check position limit again
            if len(active_symbols) >= max_positions:
                break
        
        return signals
    
    def _check_entry_criteria(self, opportunity: FundingOpportunity) -> bool:
        """Check if opportunity meets all entry criteria."""
        # 1. Spread threshold
        if opportunity.spread_annualized < self.entry_threshold:
            return False
        
        # 2. Persistence score
        if opportunity.persistence_min < self.min_persistence:
            logger.debug(f"Persistence {opportunity.persistence_min:.2f} < {self.min_persistence}")
            return False
        
        # 3. Funding flip risk check
        flip_risk = self._estimate_flip_risk(opportunity)
        if flip_risk > self.flip_threshold:
            logger.debug(f"Flip risk {flip_risk:.2f} > threshold {self.flip_threshold}")
            return False
        
        return True
    
    def _estimate_flip_risk(self, opportunity: FundingOpportunity) -> float:
        """
        Estimate probability of funding rate flipping against position.
        """
        # Simple heuristic based on distance from zero and volatility
        long_rate = opportunity.long_funding.predicted_rate
        short_rate = opportunity.short_funding.predicted_rate
        
        # If long funding is very negative, less risk of flip
        # If long funding is near zero, higher flip risk
        long_flip_prob = stats.norm.cdf(0, loc=long_rate, scale=abs(long_rate) + 0.0001)
        
        # If short funding is very positive, less risk of flip
        short_flip_prob = 1 - stats.norm.cdf(0, loc=short_rate, scale=abs(short_rate) + 0.0001)
        
        # Combined flip risk
        return max(long_flip_prob, short_flip_prob)
    
    def _calculate_position_size(self, opportunity: FundingOpportunity,
                                portfolio: Portfolio) -> float:
        """
        Calculate position size using Kelly Criterion with safety factor.
        """
        # Base position size from config
        max_position_usd = self.config.get("max_position_usd", 50000)
        min_position_usd = self.config.get("min_position_usd", 5000)
        
        # Kelly fraction (simplified)
        # Edge = expected spread, Variance = funding volatility
        edge = opportunity.spread_annualized
        variance = (1 - opportunity.persistence_min) * 0.1  # Higher persistence = lower variance
        
        if variance == 0:
            kelly_fraction = 0.1  # Conservative default
        else:
            kelly_fraction = edge / variance
        
        # Half-Kelly safety factor
        kelly_fraction *= 0.5
        
        # Clamp Kelly fraction
        kelly_fraction = max(0.05, min(0.25, kelly_fraction))
        
        # Calculate position size
        position_size = portfolio.cash * kelly_fraction
        
        # Apply min/max constraints
        position_size = max(min_position_usd, min(max_position_usd, position_size))
        
        # Check available margin
        available_margin = portfolio.cash * (1 - portfolio.margin_utilization)
        max_leverage = self.config.get("default_leverage", 2.0)
        max_size_from_margin = available_margin * max_leverage * 0.5  # Conservative
        
        position_size = min(position_size, max_size_from_margin)
        
        return position_size
    
    def generate_exit_signals(self, positions: List[Position],
                             current_predictions: Dict[Tuple[str, str], FundingPrediction]) -> List[Signal]:
        """
        Generate exit signals for open positions.
        
        Exit criteria (ANY triggers exit):
        1. Spread converged below exit_threshold
        2. Funding flip detected
        3. Time stop exceeded (max_hold_hours)
        4. Liquidation risk elevated
        """
        signals = []
        
        for position in positions:
            if position.status != "open":
                continue
            
            # Get current predictions for both legs
            long_key = (position.long_exchange, position.symbol)
            short_key = (position.short_exchange, position.symbol)
            
            if long_key not in current_predictions or short_key not in current_predictions:
                logger.warning(f"Missing predictions for position {position.position_id}")
                continue
            
            long_pred = current_predictions[long_key]
            short_pred = current_predictions[short_key]
            
            # Calculate current spread
            current_spread = (short_pred.predicted_rate - long_pred.predicted_rate) * 3 * 365
            
            # Check exit conditions
            should_exit = False
            exit_reason = ""
            
            # 1. Spread convergence
            if current_spread < self.exit_threshold:
                should_exit = True
                exit_reason = "spread_convergence"
            
            # 2. Funding flip
            elif long_pred.predicted_rate > short_pred.predicted_rate:
                should_exit = True
                exit_reason = "funding_flip"
            
            # 3. Time stop
            elif position.hold_time_hours > self.max_hold_hours:
                should_exit = True
                exit_reason = "time_stop"
            
            # 4. Low persistence (funding becoming unstable)
            elif min(long_pred.persistence_score, short_pred.persistence_score) < 0.3:
                should_exit = True
                exit_reason = "low_persistence"
            
            if should_exit:
                # Generate exit signals for both legs
                signals.append(Signal(
                    signal_type=SignalType.EXIT,
                    symbol=position.symbol,
                    exchange=position.long_exchange,
                    side=PositionSide.LONG,
                    size_usd=position.long_size_usd,
                    leverage=position.leverage,
                    confidence=1.0,
                    expected_funding=long_pred.predicted_rate,
                    metadata={
                        "position_id": position.position_id,
                        "exit_reason": exit_reason,
                        "hold_time_hours": position.hold_time_hours,
                        "current_spread": current_spread,
                        "leg": "long"
                    }
                ))
                
                signals.append(Signal(
                    signal_type=SignalType.EXIT,
                    symbol=position.symbol,
                    exchange=position.short_exchange,
                    side=PositionSide.SHORT,
                    size_usd=position.short_size_usd,
                    leverage=position.leverage,
                    confidence=1.0,
                    expected_funding=short_pred.predicted_rate,
                    metadata={
                        "position_id": position.position_id,
                        "exit_reason": exit_reason,
                        "hold_time_hours": position.hold_time_hours,
                        "current_spread": current_spread,
                        "leg": "short"
                    }
                ))
        
        return signals


class RiskManager:
    """
    Manages portfolio-level risk limits and circuit breakers.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_drawdown = config.get("max_drawdown", 0.10)
        self.daily_loss_limit = config.get("daily_loss_limit", 0.03)
        self.max_consecutive_losses = config.get("max_consecutive_losses", 3)
        
        # Track state
        self.consecutive_losses = 0
        self.daily_pnl_history: List[Tuple[datetime, float]] = []
        self.peak_value = 0.0
        self.current_drawdown = 0.0
        self.circuit_breaker_triggered = False
    
    def check_risk_limits(self, portfolio: Portfolio) -> Dict[str, Any]:
        """
        Check all risk limits and return status.
        """
        status = {
            "can_trade": True,
            "alerts": [],
            "circuit_breaker": False
        }
        
        # Update daily PnL tracking
        self._update_daily_pnl(portfolio)
        
        # Check drawdown
        current_value = portfolio.cash + portfolio.total_pnl
        if current_value > self.peak_value:
            self.peak_value = current_value
        
        self.current_drawdown = (self.peak_value - current_value) / self.peak_value if self.peak_value > 0 else 0
        
        if self.current_drawdown > self.max_drawdown:
            status["can_trade"] = False
            status["circuit_breaker"] = True
            status["alerts"].append(f"Max drawdown {self.current_drawdown:.2%} exceeded")
            self.circuit_breaker_triggered = True
        
        # Check daily loss
        today_pnl = sum(pnl for date, pnl in self.daily_pnl_history 
                       if date.date() == datetime.utcnow().date())
        
        if today_pnl < -portfolio.cash * self.daily_loss_limit:
            status["can_trade"] = False
            status["circuit_breaker"] = True
            status["alerts"].append(f"Daily loss limit exceeded: {today_pnl:,.2f}")
        
        # Check consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            status["alerts"].append(f"Max consecutive losses ({self.max_consecutive_losses}) reached")
        
        return status
    
    def _update_daily_pnl(self, portfolio: Portfolio):
        """Update daily PnL history."""
        today = datetime.utcnow().date()
        
        # Remove old entries (keep last 30 days)
        cutoff = datetime.utcnow() - timedelta(days=30)
        self.daily_pnl_history = [(d, p) for d, p in self.daily_pnl_history if d > cutoff]
        
        # Add current PnL
        self.daily_pnl_history.append((datetime.utcnow(), portfolio.daily_pnl))
    
    def record_trade_result(self, pnl: float):
        """Record trade result for consecutive loss tracking."""
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
    
    def reset_circuit_breaker(self):
        """Reset circuit breaker (manual override)."""
        self.circuit_breaker_triggered = False
        self.consecutive_losses = 0
        self.current_drawdown = 0


class FundingArbitrageStrategy:
    """
    Main strategy orchestrator for funding rate arbitrage.
    Coordinates funding analysis, signal generation, and risk management.
    """
    
    def __init__(self, config_path: Optional[str] = None, config: Optional[Dict] = None):
        """
        Initialize strategy with configuration.
        
        Args:
            config_path: Path to YAML config file
            config: Direct config dictionary (overrides file)
        """
        if config:
            self.config = config
        elif config_path:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        else:
            self.config = self._default_config()
        
        # Initialize components
        self.funding_analyzer = FundingAnalyzer(
            lookback_window=self.config.get("lookback_window", 30)
        )
        self.signal_generator = SignalGenerator(self.config)
        self.risk_manager = RiskManager(self.config)
        
        # Portfolio state
        self.portfolio = Portfolio(
            cash=self.config.get("initial_capital", 100000),
            exchange_balances={}
        )
        
        # Current predictions cache
        self.current_predictions: Dict[Tuple[str, str], FundingPrediction] = {}
        
        logger.info("FundingArbitrageStrategy initialized")
    
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration."""
        return {
            "initial_capital": 100000,
            "entry_threshold": 0.15,  # 15% annualized
            "exit_threshold": 0.05,   # 5% annualized
            "min_persistence": 0.7,
            "max_positions": 5,
            "max_position_usd": 50000,
            "min_position_usd": 5000,
            "default_leverage": 2.0,
            "max_utilization": 0.5,
            "max_hold_hours": 48,
            "flip_threshold": 0.3,
            "lookback_window": 30,
            "max_drawdown": 0.10,
            "daily_loss_limit": 0.03,
            "max_consecutive_losses": 3
        }
    
    def update_funding_data(self, funding_data: List[Dict[str, Any]]):
        """
        Update funding data from exchanges.
        
        Args:
            funding_data: List of dicts with keys: exchange, symbol, timestamp, funding_rate
        """
        for data in funding_data:
            self.funding_analyzer.update_funding_history(
                exchange=data["exchange"],
                symbol=data["symbol"],
                timestamp=pd.to_datetime(data["timestamp"]),
                funding_rate=data["funding_rate"]
            )
    
    def generate_predictions(self, exchanges: List[str], symbols: List[str],
                            premium_data: Optional[Dict] = None) -> List[FundingPrediction]:
        """
        Generate funding predictions for all exchange-symbol pairs.
        
        Args:
            exchanges: List of exchange names
            symbols: List of trading pair symbols
            premium_data: Optional dict of current premium indices
            
        Returns:
            List of FundingPrediction objects
        """
        predictions = []
        
        for exchange in exchanges:
            for symbol in symbols:
                premium = premium_data.get((exchange, symbol)) if premium_data else None
                
                pred = self.funding_analyzer.predict_funding_rate(exchange, symbol, premium)
                predictions.append(pred)
                
                # Cache prediction
                self.current_predictions[(exchange, symbol)] = pred
        
        return predictions
    
    def find_opportunities(self, predictions: List[FundingPrediction]) -> List[FundingOpportunity]:
        """
        Find cross-exchange funding opportunities.
        
        Args:
            predictions: List of funding predictions
            
        Returns:
            List of FundingOpportunity objects
        """
        min_spread = self.config.get("entry_threshold", 0.15)
        return self.funding_analyzer.calculate_cross_exchange_spread(predictions, min_spread)
    
    def generate_signals(self) -> List[Signal]:
        """
        Generate all trading signals (entries and exits).
        
        Returns:
            List of Signal objects
        """
        signals = []
        
        # Check risk limits first
        risk_status = self.risk_manager.check_risk_limits(self.portfolio)
        if not risk_status["can_trade"]:
            logger.warning(f"Trading halted: {risk_status['alerts']}")
            # Only generate exit signals
            exit_signals = self.signal_generator.generate_exit_signals(
                self.portfolio.positions, self.current_predictions
            )
            return exit_signals
        
        # Generate exit signals for existing positions
        exit_signals = self.signal_generator.generate_exit_signals(
            self.portfolio.positions, self.current_predictions
        )
        signals.extend(exit_signals)
        
        # Generate entry signals from opportunities
        opportunities = self.find_opportunities(list(self.current_predictions.values()))
        entry_signals = self.signal_generator.generate_entry_signals(opportunities, self.portfolio)
        signals.extend(entry_signals)
        
        return signals
    
    def execute_signal(self, signal: Signal) -> Optional[Dict[str, Any]]:
        """
        Execute a trading signal (placeholder for actual execution).
        
        In production, this would connect to exchange APIs via CCXT.
        
        Args:
            signal: Signal to execute
            
        Returns:
            Execution result dict or None
        """
        logger.info(f"Executing signal: {signal.signal_type.value} {signal.side.value} "
                   f"{signal.size_usd:,.2f} {signal.symbol} on {signal.exchange}")
        
        # Placeholder execution result
        return {
            "signal": signal.to_dict(),
            "status": "simulated",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def run_cycle(self, funding_data: List[Dict[str, Any]], 
                 exchanges: List[str], symbols: List[str]) -> Dict[str, Any]:
        """
        Run a full strategy cycle.
        
        Args:
            funding_data: Latest funding rate data
            exchanges: List of exchanges to monitor
            symbols: List of symbols to trade
            
        Returns:
            Cycle results summary
        """
        # Update funding data
        self.update_funding_data(funding_data)
        
        # Generate predictions
        predictions = self.generate_predictions(exchanges, symbols)
        
        # Generate signals
        signals = self.generate_signals()
        
        # Execute signals (in production)
        executions = []
        for signal in signals:
            result = self.execute_signal(signal)
            if result:
                executions.append(result)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "predictions_count": len(predictions),
            "opportunities_count": len(self.find_opportunities(predictions)),
            "signals_generated": len(signals),
            "signals": [s.to_dict() for s in signals],
            "executions": executions,
            "portfolio": {
                "cash": self.portfolio.cash,
                "positions_count": len(self.portfolio.positions),
                "margin_utilization": self.portfolio.margin_utilization,
                "total_pnl": self.portfolio.total_pnl
            }
        }


if __name__ == "__main__":
    # Example usage
    strategy = FundingArbitrageStrategy()
    
    # Simulate funding data
    funding_data = [
        {"exchange": "binance", "symbol": "BTCUSDT", "timestamp": "2026-03-30T00:00:00Z", "funding_rate": 0.0001},
        {"exchange": "bybit", "symbol": "BTCUSDT", "timestamp": "2026-03-30T00:00:00Z", "funding_rate": 0.0003},
        {"exchange": "binance", "symbol": "ETHUSDT", "timestamp": "2026-03-30T00:00:00Z", "funding_rate": -0.0002},
        {"exchange": "bybit", "symbol": "ETHUSDT", "timestamp": "2026-03-30T00:00:00Z", "funding_rate": 0.0001},
    ]
    
    result = strategy.run_cycle(
        funding_data=funding_data,
        exchanges=["binance", "bybit"],
        symbols=["BTCUSDT", "ETHUSDT"]
    )
    
    print(f"Generated {result['signals_generated']} signals")
    print(f"Opportunities found: {result['opportunities_count']}")
