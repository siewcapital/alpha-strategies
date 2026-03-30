"""
Funding Rate Arbitrage Strategy

This strategy exploits funding rate differentials between cryptocurrency perpetual
futures contracts across different exchanges.

The strategy operates in two modes:
1. Spot-to-Perpetual: Buy spot, short perpetual, collect funding
2. Cross-Exchange: Long on low-funding exchange, short on high-funding exchange

Author: ATLAS (Siew's Capital)
Date: 2026-03-24
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import yaml

logger = logging.getLogger(__name__)


class PositionSide(Enum):
    """Position side enumeration."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class SignalType(Enum):
    """Signal type enumeration."""
    ENTER_LONG = "enter_long"  # Long low-funding, short high-funding
    EXIT = "exit"
    HOLD = "hold"


@dataclass
class FundingRate:
    """Funding rate data for a perpetual contract."""
    exchange: str
    symbol: str
    rate: float  # Current funding rate (as decimal, e.g., 0.0001 = 0.01%)
    next_settle: datetime  # Next funding settlement time
    mark_price: float
    index_price: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage opportunity."""
    long_exchange: str
    short_exchange: str
    symbol: str
    long_rate: float  # Funding rate on long side
    short_rate: float  # Funding rate on short side
    rate_diff: float  # Differential (positive = long receives, short pays)
    expected_annual_return: float
    mark_price_long: float
    mark_price_short: float
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Calculate expected annual return after costs."""
        # Funding settles 3 times daily (every 8 hours)
        periods_per_day = 3
        periods_per_year = periods_per_day * 365
        
        # Gross return
        gross_return = self.rate_diff * periods_per_year
        
        # Costs: approximately 0.1% per trade + 0.05% slippage
        total_costs = 0.0015
        
        self.expected_annual_return = gross_return - total_costs


@dataclass
class Position:
    """Represents an active arbitrage position."""
    symbol: str
    long_exchange: str
    short_exchange: str
    size: float  # Position size in base currency
    entry_long_rate: float
    entry_short_rate: float
    entry_time: datetime
    entry_long_price: float
    entry_short_price: float
    margin_used: float
    leverage: float
    
    def days_held(self) -> float:
        """Calculate days since entry."""
        return (datetime.now() - self.entry_time).total_seconds() / 86400
    
    def current_pnl(self, current_long_rate: float, current_short_rate: float) -> float:
        """Calculate current PnL including funding received/paid."""
        days = self.days_held()
        periods = days * 3  # 3 funding periods per day
        
        # Funding received on long position
        long_funding = self.size * self.entry_long_rate * periods
        
        # Funding paid on short position (negative rate means shorts receive)
        # If short rate is positive, we pay; if negative, we receive
        short_funding = self.size * self.entry_short_rate * periods
        
        return long_funding + short_funding


class FundingRateArbitrageStrategy:
    """
    Main strategy class for funding rate arbitrage.
    
    This strategy monitors funding rates across multiple exchanges and identifies
    opportunities where the rate differential exceeds the minimum threshold.
    """
    
    def __init__(self, config_path: str = "config/params.yaml"):
        """Initialize the strategy with configuration."""
        self.config = self._load_config(config_path)
        self.positions: Dict[str, Position] = {}
        self.signals_generated = []
        self.total_pnl = 0.0
        
        # Strategy parameters
        self.min_funding_diff = self.config["strategy"]["min_funding_diff"]
        self.min_expected_return = self.config["strategy"]["min_expected_arb_return"]
        self.max_leverage = self.config["strategy"]["max_leverage"]
        self.max_position_size = self.config["strategy"]["max_position_size"]
        self.max_concurrent = self.config["strategy"]["max_concurrent_positions"]
        self.max_holding_period = self.config["strategy"]["max_holding_period"]
        
        # Risk parameters
        self.max_drawdown_stop = self.config["risk"]["max_drawdown_stop"]
        self.min_margin_buffer = self.config["risk"]["min_margin_buffer"]
        
        # Cost parameters
        self.maker_fee = self.config["costs"]["maker_fee"]
        self.taker_fee = self.config["costs"]["taker_fee"]
        self.slippage = self.config["costs"]["expected_slippage"]
        self.borrowing_rate = self.config["costs"]["borrowing_rate"]
        
        logger.info("Funding Rate Arbitrage Strategy initialized")
        logger.info(f"Min funding diff: {self.min_funding_diff:.4%}")
        logger.info(f"Min expected return: {self.min_expected_return:.2%}")
    
    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"Config file {config_path} not found, using defaults")
            return self._default_config()
    
    def _default_config(self) -> dict:
        """Return default configuration."""
        return {
            "strategy": {
                "min_funding_diff": 0.0001,
                "min_expected_arb_return": 0.05,
                "max_leverage": 2.5,
                "max_position_size": 0.10,
                "max_concurrent_positions": 5,
                "rebalance_interval": 300,
                "max_holding_period": 604800
            },
            "risk": {
                "max_drawdown_stop": 0.05,
                "min_margin_buffer": 0.50,
                "max_single_asset_exposure": 0.15,
                "correlation_threshold": 0.70
            },
            "costs": {
                "maker_fee": 0.0004,
                "taker_fee": 0.0006,
                "expected_slippage": 0.0005,
                "borrowing_rate": 0.08
            }
        }
    
    def scan_opportunities(
        self, 
        funding_data: Dict[str, Dict[str, FundingRate]]
    ) -> List[ArbitrageOpportunity]:
        """
        Scan for arbitrage opportunities across exchanges.
        
        Args:
            funding_data: Dict mapping exchange -> {symbol: FundingRate}
            
        Returns:
            List of detected arbitrage opportunities
        """
        opportunities = []
        exchanges = list(funding_data.keys())
        
        # Check each symbol across exchange pairs
        for symbol in funding_data[exchanges[0]].keys():
            # Skip if we already have a position for this symbol
            if symbol in self.positions:
                continue
            
            # Skip if at max concurrent positions
            if len(self.positions) >= self.max_concurrent:
                break
            
            # Compare all exchange pairs
            for i, long_exchange in enumerate(exchanges):
                for short_exchange in exchanges[i+1:]:
                    # Skip if data unavailable
                    if symbol not in funding_data[long_exchange]:
                        continue
                    if symbol not in funding_data[short_exchange]:
                        continue
                    
                    long_rate = funding_data[long_exchange][symbol].rate
                    short_rate = funding_data[short_exchange][symbol].rate
                    
                    # Calculate rate differential
                    # Positive: long pays short (we go long to receive)
                    # Negative: short pays long (we go short to receive)
                    rate_diff = long_rate - short_rate
                    
                    # Check if opportunity meets criteria
                    if abs(rate_diff) < self.min_funding_diff:
                        continue
                    
                    # Create opportunity
                    opp = ArbitrageOpportunity(
                        long_exchange=long_exchange,
                        short_exchange=short_exchange,
                        symbol=symbol,
                        long_rate=long_rate,
                        short_rate=short_rate,
                        rate_diff=rate_diff,
                        expected_annual_return=0.0,  # Will be calculated in __post_init__
                        mark_price_long=funding_data[long_exchange][symbol].mark_price,
                        mark_price_short=funding_data[short_exchange][symbol].mark_price
                    )
                    
                    # Only include if expected return meets threshold
                    if opp.expected_annual_return >= self.min_expected_return:
                        opportunities.append(opp)
        
        # Sort by expected return (highest first)
        opportunities.sort(key=lambda x: x.expected_annual_return, reverse=True)
        
        logger.info(f"Found {len(opportunities)} arbitrage opportunities")
        
        return opportunities
    
    def generate_signal(
        self, 
        opportunity: ArbitrageOpportunity,
        portfolio_value: float
    ) -> Tuple[SignalType, Optional[Position]]:
        """
        Generate trading signal based on opportunity.
        
        Args:
            opportunity: The arbitrage opportunity
            portfolio_value: Current portfolio value
            
        Returns:
            Tuple of (SignalType, Optional Position to open)
        """
        # Check position size limits
        max_size = portfolio_value * self.max_position_size
        
        # Calculate position size based on expected return
        # Higher expected return = larger position
        position_value = min(
            portfolio_value * self.max_position_size * opportunity.expected_annual_return / 0.10,
            max_size
        )
        position_value = max(position_value, portfolio_value * 0.01)  # Min 1% of portfolio
        
        # Apply leverage
        leveraged_value = position_value * self.max_leverage
        margin_required = position_value
        
        # Create position
        position = Position(
            symbol=opportunity.symbol,
            long_exchange=opportunity.long_exchange,
            short_exchange=opportunity.short_exchange,
            size=leveraged_value / ((opportunity.mark_price_long + opportunity.mark_price_short) / 2),
            entry_long_rate=opportunity.long_rate,
            entry_short_rate=opportunity.short_rate,
            entry_time=datetime.now(),
            entry_long_price=opportunity.mark_price_long,
            entry_short_price=opportunity.mark_price_short,
            margin_used=margin_required,
            leverage=self.max_leverage
        )
        
        return SignalType.ENTER_LONG, position
    
    def check_exit_conditions(self, position: Position) -> bool:
        """
        Check if position should be exited.
        
        Args:
            position: The position to check
            
        Returns:
            True if position should be exited
        """
        # Check max holding period
        if position.days_held() * 86400 > self.max_holding_period:
            logger.info(f"Exiting {position.symbol}: Max holding period reached")
            return True
        
        return False
    
    def calculate_position_pnl(self, position: Position) -> float:
        """
        Calculate current PnL for a position.
        
        Args:
            position: The position to evaluate
            
        Returns:
            Current PnL in quote currency
        """
        # Simplified PnL calculation
        # In reality, would fetch current funding rates
        days = position.days_held()
        
        # Funding received (positive rate = we receive)
        long_funding = position.size * position.entry_long_rate * days * 3
        short_funding = position.size * position.entry_short_rate * days * 3
        
        # Costs
        entry_cost = position.margin_used * (self.taker_fee + self.slippage)
        exit_cost = position.margin_used * (self.taker_fee + self.slippage)
        
        pnl = long_funding + short_funding - entry_cost - exit_cost
        
        return pnl
    
    def update_positions(
        self, 
        portfolio_value: float,
        exit_signals: List[str] = None
    ) -> Dict[str, float]:
        """
        Update all positions, check exit conditions, calculate PnL.
        
        Args:
            portfolio_value: Current portfolio value
            exit_signals: List of symbols to force exit
            
        Returns:
            Dict of symbol -> PnL
        """
        pnl_results = {}
        
        for symbol, position in list(self.positions.items()):
            # Check exit conditions
            should_exit = (
                self.check_exit_conditions(position) or
                (exit_signals and symbol in exit_signals)
            )
            
            if should_exit:
                # Calculate final PnL
                pnl = self.calculate_position_pnl(position)
                pnl_results[symbol] = pnl
                self.total_pnl += pnl
                
                # Remove position
                del self.positions[symbol]
                logger.info(f"Exited position {symbol}, PnL: {pnl:.2f}")
        
        return pnl_results
    
    def get_portfolio_exposure(self) -> Dict[str, float]:
        """
        Get current portfolio exposure by symbol.
        
        Returns:
            Dict of symbol -> exposure as fraction of portfolio
        """
        exposure = {}
        for symbol, position in self.positions.items():
            exposure[symbol] = position.margin_used / 100000  # Simplified
        
        return exposure
    
    def can_open_position(self, symbol: str, new_exposure: float) -> bool:
        """
        Check if a new position can be opened based on risk limits.
        
        Args:
            symbol: Symbol for new position
            new_exposure: New position exposure
            
        Returns:
            True if position can be opened
        """
        # Check single asset exposure
        current_exposure = self.get_portfolio_exposure().get(symbol, 0)
        if current_exposure + new_exposure > self.config["risk"]["max_single_asset_exposure"]:
            logger.warning(f"Cannot open position {symbol}: Would exceed single asset limit")
            return False
        
        # Check total concurrent positions
        if len(self.positions) >= self.max_concurrent:
            logger.warning(f"Cannot open position {symbol}: At max concurrent positions")
            return False
        
        return True
    
    def get_strategy_state(self) -> dict:
        """
        Get current strategy state for monitoring.
        
        Returns:
            Dict with strategy state
        """
        return {
            "total_positions": len(self.positions),
            "total_pnl": self.total_pnl,
            "positions": [
                {
                    "symbol": p.symbol,
                    "exchange_pair": f"{p.long_exchange}/{p.short_exchange}",
                    "days_held": p.days_held(),
                    "margin_used": p.margin_used
                }
                for p in self.positions.values()
            ],
            "timestamp": datetime.now().isoformat()
        }
    
    def reset(self):
        """Reset strategy state (for backtesting)."""
        self.positions = {}
        self.signals_generated = []
        self.total_pnl = 0.0
        logger.info("Strategy state reset")
