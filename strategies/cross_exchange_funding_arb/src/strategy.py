"""
Cross-Exchange Funding Rate Arbitrage - Main Strategy Module
Orchestrates the full strategy lifecycle from data ingestion to execution.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
import yaml
from pathlib import Path

try:
    from src.indicators import (
        FundingRateCalculator, OpportunityFilter, FundingRate, FundingDifferential
    )
    from src.signal_generator import SignalGenerator, Signal, SignalType, PositionState
    from src.risk_manager import RiskManager, RiskLimits, PortfolioState, RiskLevel
except ImportError:
    from indicators import (
        FundingRateCalculator, OpportunityFilter, FundingRate, FundingDifferential
    )
    from signal_generator import SignalGenerator, Signal, SignalType, PositionState
    from risk_manager import RiskManager, RiskLimits, PortfolioState, RiskLevel

logger = logging.getLogger(__name__)


class StrategyState(Enum):
    """Strategy operational states."""
    INITIALIZED = "initialized"
    RUNNING = "running"
    PAUSED = "paused"
    SHUTDOWN = "shutdown"
    ERROR = "error"


@dataclass
class StrategyConfig:
    """Strategy configuration parameters."""
    # Entry/Exit thresholds
    entry_threshold: float = 0.0002  # 0.02%
    exit_threshold: float = 0.00005  # 0.005%
    min_annualized_return: float = 0.08  # 8%
    
    # Position management
    max_positions: int = 5
    max_position_size_usd: float = 50000.0
    default_leverage: float = 2.0
    
    # Time parameters
    funding_interval_hours: float = 8.0
    max_hold_hours: float = 72.0
    min_hold_periods: int = 2
    
    # Risk parameters
    max_drawdown_pct: float = 0.10
    max_daily_loss_pct: float = 0.02
    
    # Exchange configuration
    exchanges: List[str] = field(default_factory=lambda: ['binance', 'bybit', 'okx'])
    symbols: List[str] = field(default_factory=lambda: ['BTCUSDT', 'ETHUSDT'])
    
    @classmethod
    def from_yaml(cls, path: str) -> 'StrategyConfig':
        """Load configuration from YAML file."""
        with open(path, 'r') as f:
            config_dict = yaml.safe_load(f)
        return cls(**config_dict.get('strategy', {}))


@dataclass
class PerformanceMetrics:
    """Strategy performance metrics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    profit_factor: float = 0.0
    
    avg_trade_return: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    
    total_funding_earned: float = 0.0
    avg_hold_time_hours: float = 0.0
    
    def update_from_trades(self, trades: List[Dict]) -> None:
        """Update metrics from trade history."""
        if not trades:
            return
        
        self.total_trades = len(trades)
        
        wins = [t for t in trades if t.get('total_pnl', 0) > 0]
        losses = [t for t in trades if t.get('total_pnl', 0) <= 0]
        
        self.winning_trades = len(wins)
        self.losing_trades = len(losses)
        self.win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        
        self.gross_profit = sum(t['total_pnl'] for t in wins) if wins else 0
        self.gross_loss = abs(sum(t['total_pnl'] for t in losses)) if losses else 0
        self.net_profit = self.gross_profit - self.gross_loss
        self.profit_factor = self.gross_profit / self.gross_loss if self.gross_loss > 0 else float('inf')
        
        if self.total_trades > 0:
            returns = [t.get('total_pnl', 0) for t in trades]
            self.avg_trade_return = np.mean(returns)
            
            hold_times = [t.get('duration_hours', 0) for t in trades if 'duration_hours' in t]
            if hold_times:
                self.avg_hold_time_hours = np.mean(hold_times)
        
        if wins:
            self.avg_win = np.mean([t['total_pnl'] for t in wins])
        if losses:
            self.avg_loss = np.mean([t['total_pnl'] for t in losses])
        
        self.total_funding_earned = sum(t.get('funding_earned', 0) for t in trades)


class FundingArbitrageStrategy:
    """
    Main cross-exchange funding rate arbitrage strategy.
    
    This strategy identifies and exploits funding rate differentials across
    cryptocurrency exchanges while maintaining delta-neutral exposure.
    """
    
    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        risk_limits: Optional[RiskLimits] = None
    ):
        self.config = config or StrategyConfig()
        self.state = StrategyState.INITIALIZED
        
        # Initialize components
        self.calculator = FundingRateCalculator(
            min_differential=self.config.entry_threshold / 2,
            lookback_periods=30
        )
        
        self.opportunity_filter = OpportunityFilter(
            min_annualized_return=self.config.min_annualized_return,
            min_confidence=0.6,
            max_funding_volatility=0.001
        )
        
        self.signal_generator = SignalGenerator(
            entry_threshold=self.config.entry_threshold,
            exit_threshold=self.config.exit_threshold,
            max_hold_hours=self.config.max_hold_hours,
            min_hold_periods=self.config.min_hold_periods
        )
        
        self.risk_manager = RiskManager(risk_limits or RiskLimits())
        
        # State tracking
        self.current_rates: Dict[str, Dict[str, FundingRate]] = {}
        self.performance = PerformanceMetrics()
        self._trade_history: List[Dict] = []
        self._equity_curve: List[Tuple[datetime, float]] = []
        
        logger.info("FundingArbitrageStrategy initialized")
    
    def process_funding_update(
        self,
        exchange: str,
        symbol: str,
        funding_rate: float,
        timestamp: datetime,
        premium_index: Optional[float] = None,
        next_funding_time: Optional[datetime] = None
    ) -> None:
        """
        Process new funding rate data from an exchange.
        
        Args:
            exchange: Exchange name
            symbol: Trading pair symbol
            funding_rate: Current funding rate
            timestamp: Data timestamp
            premium_index: Premium index if available
            next_funding_time: Next funding payment time
        """
        # Store current rate
        if symbol not in self.current_rates:
            self.current_rates[symbol] = {}
        
        self.current_rates[symbol][exchange] = FundingRate(
            exchange=exchange,
            symbol=symbol,
            funding_rate=funding_rate,
            next_funding_time=next_funding_time or timestamp + timedelta(hours=8),
            premium_index=premium_index
        )
        
        # Add to calculator history
        self.calculator.add_funding_data(
            exchange=exchange,
            symbol=symbol,
            timestamp=timestamp,
            funding_rate=funding_rate,
            premium_index=premium_index
        )
        
        logger.debug(f"Updated {exchange}:{symbol} funding: {funding_rate:.4%}")
    
    def generate_signals(self, timestamp: datetime) -> Tuple[List[Signal], List[Signal]]:
        """
        Generate entry and exit signals for current market state.
        
        Returns:
            (entry_signals, exit_signals)
        """
        entry_signals = []
        exit_signals = []
        
        # Generate exit signals first (risk management priority)
        exit_signals = self.signal_generator.generate_exit_signals(
            current_rates=self.current_rates,
            current_time=timestamp
        )
        
        # Generate entry signals for each symbol
        for symbol in self.config.symbols:
            if symbol not in self.current_rates:
                continue
            
            exchanges = list(self.current_rates[symbol].keys())
            if len(exchanges) < 2:
                continue
            
            # Calculate differentials
            opportunities = self.calculator.calculate_differentials(
                symbol=symbol,
                exchanges=exchanges,
                current_rates=self.current_rates[symbol]
            )
            
            # Filter opportunities
            portfolio_heat = (
                self.risk_manager.state.total_exposure / 
                self.risk_manager.limits.max_total_exposure_usd
                if self.risk_manager.limits.max_total_exposure_usd > 0 else 0
            )
            
            filtered = self.opportunity_filter.filter_opportunities(
                opportunities=opportunities,
                portfolio_heat=portfolio_heat
            )
            
            # Generate entry signals
            available_capital = self.risk_manager.state.available_margin
            
            symbol_entries = self.signal_generator.generate_entry_signals(
                opportunities=filtered,
                current_time=timestamp,
                available_capital=available_capital,
                max_positions=self.config.max_positions
            )
            
            entry_signals.extend(symbol_entries)
        
        # Log signal generation
        if entry_signals:
            logger.info(f"Generated {len(entry_signals)} entry signals")
        if exit_signals:
            logger.info(f"Generated {len(exit_signals)} exit signals")
        
        return entry_signals, exit_signals
    
    def evaluate_entry_signal(self, signal: Signal) -> Tuple[bool, float, List[str]]:
        """
        Evaluate and size an entry signal with risk checks.
        
        Returns:
            (is_valid, position_size, notes)
        """
        # Check risk permissions
        permitted, reasons = self.risk_manager.check_entry_permissions(
            symbol=signal.symbol,
            long_exchange=signal.long_exchange,
            short_exchange=signal.short_exchange,
            proposed_size=signal.size_usd
        )
        
        if not permitted:
            return False, 0.0, reasons
        
        # Calculate position size with risk adjustments
        opportunity_score = signal.metadata.get('opportunity_score', 0.1)
        
        sized_position, risk_level, warnings = self.risk_manager.calculate_position_size(
            opportunity_score=opportunity_score,
            confidence=signal.confidence,
            funding_differential=signal.expected_funding_diff,
            symbol=signal.symbol,
            long_exchange=signal.long_exchange,
            short_exchange=signal.short_exchange,
            base_size=signal.size_usd
        )
        
        notes = warnings
        if risk_level.value in ['high', 'critical']:
            notes.append(f"Risk level: {risk_level.value}")
        
        if sized_position <= 0:
            return False, 0.0, notes
        
        return True, sized_position, notes
    
    def execute_entry(
        self,
        signal: Signal,
        position_size: float,
        timestamp: datetime,
        entry_prices: Optional[Dict[str, float]] = None
    ) -> bool:
        """
        Execute position entry (simulated for backtest).
        
        Returns:
            Success boolean
        """
        try:
            # Register with signal generator
            self.signal_generator.register_position_entry(
                signal=signal,
                leverage_long=self.config.default_leverage,
                leverage_short=self.config.default_leverage
            )
            
            # Update risk manager state
            current_exposure = self.risk_manager.state.total_exposure
            new_exposure = current_exposure + position_size * 2  # Both legs
            
            self.risk_manager.update_portfolio_state(
                total_equity=self.risk_manager.state.total_equity,
                available_margin=self.risk_manager.state.available_margin - position_size * 0.1,
                total_exposure=new_exposure
            )
            
            logger.info(
                f"Executed ENTRY: {signal.symbol} ${position_size:,.2f} "
                f"Long@{signal.long_exchange} Short@{signal.short_exchange}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Entry execution failed: {e}")
            return False
    
    def execute_exit(
        self,
        signal: Signal,
        timestamp: datetime,
        exit_prices: Optional[Dict[str, float]] = None
    ) -> bool:
        """
        Execute position exit (simulated for backtest).
        
        Returns:
            Success boolean
        """
        try:
            # Get position state
            position_key = f"{signal.symbol}:{signal.long_exchange}:{signal.short_exchange}"
            active_positions = self.signal_generator.get_active_positions()
            
            if position_key not in active_positions:
                logger.warning(f"Position {position_key} not found for exit")
                return False
            
            position = active_positions[position_key]
            
            # Calculate P&L (simplified)
            realized_pnl = position.unrealized_pnl
            funding_earned = position.accumulated_funding
            
            # Record trade
            trade_record = {
                'symbol': signal.symbol,
                'long_exchange': signal.long_exchange,
                'short_exchange': signal.short_exchange,
                'entry_time': position.entry_time,
                'exit_time': timestamp,
                'duration_hours': (timestamp - position.entry_time).total_seconds() / 3600,
                'size_usd': position.size_usd,
                'realized_pnl': realized_pnl,
                'funding_earned': funding_earned,
                'total_pnl': realized_pnl + funding_earned,
                'exit_reason': signal.exit_reason.value if signal.exit_reason else 'unknown'
            }
            
            self._trade_history.append(trade_record)
            
            # Update risk manager
            self.risk_manager.record_trade(**trade_record)
            
            # Register exit with signal generator
            self.signal_generator.register_position_exit(
                signal=signal,
                realized_pnl=realized_pnl + funding_earned
            )
            
            # Update exposure
            current_exposure = self.risk_manager.state.total_exposure
            new_exposure = max(0, current_exposure - position.size_usd * 2)
            
            self.risk_manager.update_portfolio_state(
                total_equity=self.risk_manager.state.total_equity + realized_pnl + funding_earned,
                available_margin=self.risk_manager.state.available_margin + position.size_usd * 0.1,
                total_exposure=new_exposure
            )
            
            logger.info(
                f"Executed EXIT: {signal.symbol} PnL=${realized_pnl+funding_earned:,.2f} "
                f"Reason: {signal.exit_reason.value if signal.exit_reason else 'unknown'}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Exit execution failed: {e}")
            return False
    
    def update(self, timestamp: datetime) -> Dict:
        """
        Main strategy update cycle.
        
        Args:
            timestamp: Current timestamp
        
        Returns:
            Update results summary
        """
        if self.state != StrategyState.RUNNING:
            logger.warning(f"Strategy not running, current state: {self.state.value}")
            return {'status': 'not_running'}
        
        # Generate signals
        entry_signals, exit_signals = self.generate_signals(timestamp)
        
        # Process exits first
        executed_exits = []
        for signal in exit_signals:
            success = self.execute_exit(signal, timestamp)
            if success:
                executed_exits.append(signal)
        
        # Process entries
        executed_entries = []
        for signal in entry_signals:
            is_valid, position_size, notes = self.evaluate_entry_signal(signal)
            if is_valid:
                success = self.execute_entry(signal, position_size, timestamp)
                if success:
                    executed_entries.append(signal)
        
        # Update performance metrics
        self.performance.update_from_trades(self._trade_history)
        
        # Record equity
        self._equity_curve.append((timestamp, self.risk_manager.state.total_equity))
        
        return {
            'status': 'success',
            'timestamp': timestamp,
            'entry_signals': len(entry_signals),
            'exit_signals': len(exit_signals),
            'executed_entries': len(executed_entries),
            'executed_exits': len(executed_exits),
            'active_positions': len(self.signal_generator.get_active_positions()),
            'total_pnl': self.risk_manager.state.total_pnl
        }
    
    def get_status(self) -> Dict:
        """Get current strategy status."""
        return {
            'state': self.state.value,
            'performance': {
                'total_trades': self.performance.total_trades,
                'win_rate': self.performance.win_rate,
                'net_profit': self.performance.net_profit,
                'profit_factor': self.performance.profit_factor,
                'avg_hold_time': self.performance.avg_hold_time_hours
            },
            'portfolio': self.risk_manager.get_risk_report(),
            'active_positions': len(self.signal_generator.get_active_positions())
        }
    
    def start(self) -> None:
        """Start the strategy."""
        self.state = StrategyState.RUNNING
        logger.info("Strategy started")
    
    def stop(self) -> None:
        """Stop the strategy."""
        self.state = StrategyState.SHUTDOWN
        logger.info("Strategy stopped")
    
    def pause(self) -> None:
        """Pause the strategy (no new entries)."""
        self.state = StrategyState.PAUSED
        logger.info("Strategy paused")
    
    def get_trade_report(self) -> pd.DataFrame:
        """Get trade history as DataFrame."""
        if not self._trade_history:
            return pd.DataFrame()
        return pd.DataFrame(self._trade_history)
    
    def get_equity_curve(self) -> pd.DataFrame:
        """Get equity curve as DataFrame."""
        if not self._equity_curve:
            return pd.DataFrame()
        
        df = pd.DataFrame(self._equity_curve, columns=['timestamp', 'equity'])
        df.set_index('timestamp', inplace=True)
        return df
