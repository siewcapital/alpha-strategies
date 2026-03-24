"""
Cross-Exchange Funding Rate Arbitrage - Backtesting Engine
Event-driven backtester with realistic execution simulation.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path

# Add src to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from strategy import FundingArbitrageStrategy, StrategyConfig, PerformanceMetrics
from risk_manager import RiskLimits, PortfolioState
from signal_generator import Signal, SignalType
from data_loader import SyntheticFundingDataGenerator, FundingDataLoader

logger = logging.getLogger(__name__)


class FillModel(Enum):
    """Order fill model types."""
    IMMEDIATE = "immediate"  # Instant fill at mid price
    SLIPPAGE = "slippage"    # Add slippage based on size
    ORDER_BOOK = "order_book"  # Simulate order book impact


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    # Capital
    initial_capital: float = 100000.0
    
    # Execution costs
    maker_fee: float = 0.0002  # 0.02%
    taker_fee: float = 0.0005  # 0.05%
    slippage_bps: float = 2.0  # 2 basis points
    
    # Fill model
    fill_model: FillModel = FillModel.SLIPPAGE
    
    # Data parameters
    funding_interval_hours: float = 8.0
    
    # Reporting
    log_frequency: int = 100  # Log every N periods


@dataclass
class TradeRecord:
    """Detailed trade record for analysis."""
    trade_id: int
    symbol: str
    long_exchange: str
    short_exchange: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_funding_diff: float = 0.0
    exit_funding_diff: Optional[float] = None
    size_usd: float = 0.0
    entry_price_long: float = 0.0
    entry_price_short: float = 0.0
    exit_price_long: Optional[float] = None
    exit_price_short: Optional[float] = None
    leverage: float = 2.0
    
    # P&L components
    funding_earned: float = 0.0
    trading_fees: float = 0.0
    slippage_cost: float = 0.0
    price_pnl: float = 0.0
    total_pnl: float = 0.0
    
    # Status
    is_open: bool = True
    exit_reason: Optional[str] = None
    
    @property
    def duration_hours(self) -> Optional[float]:
        if self.exit_time:
            return (self.exit_time - self.entry_time).total_seconds() / 3600
        return None
    
    @property
    def return_pct(self) -> float:
        if self.size_usd > 0:
            return self.total_pnl / self.size_usd
        return 0.0


class FundingBacktester:
    """
    Event-driven backtester for funding rate arbitrage strategy.
    """
    
    def __init__(
        self,
        strategy: FundingArbitrageStrategy,
        config: BacktestConfig
    ):
        self.strategy = strategy
        self.config = config
        
        # State tracking
        self.capital = config.initial_capital
        self.peak_capital = config.initial_capital
        self.current_drawdown = 0.0
        
        # Trade tracking
        self.trades: List[TradeRecord] = []
        self.open_trades: Dict[str, TradeRecord] = {}  # key: symbol:long_ex:short_ex
        self.trade_counter = 0
        
        # Equity curve
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.funding_curve: List[Tuple[datetime, float]] = []
        
        # Statistics
        self.periods_processed = 0
        self.signals_generated = 0
        self.signals_executed = 0
        
    def run(
        self,
        data: Dict[str, Dict[str, pd.DataFrame]],
        price_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> Dict:
        """
        Run backtest on historical funding data.
        
        Args:
            data: Nested dict of funding data: data[symbol][exchange] = DataFrame
            price_data: Optional price data for P&L calculation
        
        Returns:
            Backtest results dictionary
        """
        logger.info("Starting backtest run...")
        logger.info(f"Initial capital: ${self.config.initial_capital:,.2f}")
        
        # Initialize strategy
        self.strategy.start()
        
        # Get all unique timestamps
        all_timestamps = self._get_all_timestamps(data)
        logger.info(f"Processing {len(all_timestamps)} periods")
        
        # Initialize strategy portfolio
        self.strategy.risk_manager.update_portfolio_state(
            total_equity=self.capital,
            available_margin=self.capital * 0.9,  # 90% available
            total_exposure=0.0,
            timestamp=all_timestamps[0]
        )
        
        # Main simulation loop
        for i, timestamp in enumerate(all_timestamps):
            self.periods_processed = i
            
            # Process funding updates for this timestamp
            self._process_funding_updates(data, timestamp)
            
            # Update prices if available
            if price_data:
                self._update_prices(price_data, timestamp)
            
            # Execute signals
            self._execute_signals(timestamp)
            
            # Increment funding period counter
            self.strategy.signal_generator.increment_funding_period()
            
            # Update equity
            self._update_equity(timestamp)
            
            # Periodic logging
            if i % self.config.log_frequency == 0:
                self._log_status(timestamp)
        
        # Close any remaining positions
        self._close_all_positions(all_timestamps[-1])
        
        # Stop strategy
        self.strategy.stop()
        
        # Calculate results
        results = self._calculate_results()
        
        logger.info("Backtest complete")
        logger.info(f"Final capital: ${self.capital:,.2f}")
        logger.info(f"Total return: {results['total_return_pct']:.2f}%")
        
        return results
    
    def _get_all_timestamps(
        self,
        data: Dict[str, Dict[str, pd.DataFrame]]
    ) -> List[datetime]:
        """Extract all unique timestamps from data."""
        timestamps = set()
        
        for symbol, exchange_data in data.items():
            for exchange, df in exchange_data.items():
                timestamps.update(df.index.tolist())
        
        return sorted(list(timestamps))
    
    def _process_funding_updates(
        self,
        data: Dict[str, Dict[str, pd.DataFrame]],
        timestamp: datetime
    ) -> None:
        """Process funding rate updates for current timestamp."""
        for symbol, exchange_data in data.items():
            for exchange, df in exchange_data.items():
                if timestamp in df.index:
                    row = df.loc[timestamp]
                    self.strategy.process_funding_update(
                        exchange=exchange,
                        symbol=symbol,
                        funding_rate=row['funding_rate'],
                        timestamp=timestamp,
                        premium_index=row.get('premium_index')
                    )
    
    def _update_prices(
        self,
        price_data: Dict[str, pd.DataFrame],
        timestamp: datetime
    ) -> None:
        """Update position mark prices."""
        # Simulate price updates for open positions
        for trade_key, trade in self.open_trades.items():
            # Simulate small price drift (mean-reverting around entry)
            if trade.is_open:
                # Random walk with mean reversion
                drift_long = np.random.normal(0, 0.001)
                drift_short = np.random.normal(0, 0.001)
                
                # Track price divergence
                pass  # Price tracking simplified for funding-focused backtest
    
    def _execute_signals(self, timestamp: datetime) -> None:
        """Execute strategy signals."""
        # Get signals from strategy
        entry_signals, exit_signals = self.strategy.generate_signals(timestamp)
        
        # Process exits first
        for signal in exit_signals:
            self._execute_exit(signal, timestamp)
        
        # Process entries
        for signal in entry_signals:
            self._execute_entry(signal, timestamp)
    
    def _execute_entry(self, signal: Signal, timestamp: datetime) -> None:
        """Execute entry signal."""
        trade_key = f"{signal.symbol}:{signal.long_exchange}:{signal.short_exchange}"
        
        # Check if position already exists
        if trade_key in self.open_trades:
            return
        
        # Evaluate with risk manager
        is_valid, position_size, notes = self.strategy.evaluate_entry_signal(signal)
        
        if not is_valid or position_size <= 0:
            return
        
        # Calculate execution costs
        fees = position_size * 2 * self.config.taker_fee  # Both legs
        slippage = position_size * 2 * (self.config.slippage_bps / 10000)
        total_cost = fees + slippage
        
        # Check if we have enough capital
        if total_cost > self.capital * 0.1:
            logger.warning(f"Insufficient capital for entry: {trade_key}")
            return
        
        # Create trade record
        self.trade_counter += 1
        trade = TradeRecord(
            trade_id=self.trade_counter,
            symbol=signal.symbol,
            long_exchange=signal.long_exchange,
            short_exchange=signal.short_exchange,
            entry_time=timestamp,
            entry_funding_diff=signal.expected_funding_diff,
            size_usd=position_size,
            leverage=2.0,
            trading_fees=fees,
            slippage_cost=slippage
        )
        
        self.open_trades[trade_key] = trade
        self.trades.append(trade)
        
        # Deduct costs
        self.capital -= total_cost
        
        # Register with strategy
        self.strategy.signal_generator.register_position_entry(signal)
        
        self.signals_executed += 1
        
        logger.debug(f"Opened trade {trade.trade_id}: {trade_key}")
    
    def _execute_exit(self, signal: Signal, timestamp: datetime) -> None:
        """Execute exit signal."""
        trade_key = f"{signal.symbol}:{signal.long_exchange}:{signal.short_exchange}"
        
        if trade_key not in self.open_trades:
            return
        
        trade = self.open_trades[trade_key]
        
        if not trade.is_open:
            return
        
        # Calculate exit costs
        exit_fees = trade.size_usd * 2 * self.config.taker_fee
        exit_slippage = trade.size_usd * 2 * (self.config.slippage_bps / 10000)
        
        # Calculate funding earned
        periods_held = int((timestamp - trade.entry_time).total_seconds() / (8 * 3600))
        
        # Approximate funding (simplified)
        avg_funding_rate = abs(trade.entry_funding_diff)
        funding_earned = trade.size_usd * avg_funding_rate * periods_held
        
        # Calculate total P&L
        total_fees = trade.trading_fees + exit_fees
        total_slippage = trade.slippage_cost + exit_slippage
        trade.funding_earned = funding_earned
        trade.trading_fees = total_fees
        trade.slippage_cost = total_slippage
        
        # Simplified price P&L (assume delta-neutral, small residual)
        trade.price_pnl = np.random.normal(0, trade.size_usd * 0.001)
        
        trade.total_pnl = funding_earned - total_fees - total_slippage + trade.price_pnl
        
        # Close trade
        trade.exit_time = timestamp
        trade.exit_funding_diff = signal.expected_funding_diff
        trade.is_open = False
        trade.exit_reason = signal.exit_reason.value if signal.exit_reason else 'unknown'
        
        # Update capital
        self.capital += trade.size_usd + trade.total_pnl  # Return margin + P&L
        
        # Remove from open trades
        del self.open_trades[trade_key]
        
        # Register with strategy
        self.strategy.signal_generator.register_position_exit(signal, trade.total_pnl)
        
        logger.debug(
            f"Closed trade {trade.trade_id}: PnL=${trade.total_pnl:,.2f} "
            f"({trade.return_pct:.2%})"
        )
    
    def _close_all_positions(self, timestamp: datetime) -> None:
        """Close all open positions at end of backtest."""
        for trade_key in list(self.open_trades.keys()):
            trade = self.open_trades[trade_key]
            
            # Create synthetic exit signal
            from signal_generator import Signal, SignalType, ExitReason
            
            signal = Signal(
                timestamp=timestamp,
                symbol=trade.symbol,
                signal_type=SignalType.EXIT_LONG,
                long_exchange=trade.long_exchange,
                short_exchange=trade.short_exchange,
                size_usd=trade.size_usd,
                confidence=1.0,
                expected_funding_diff=0.0,
                exit_reason=ExitReason.MANUAL
            )
            
            self._execute_exit(signal, timestamp)
    
    def _update_equity(self, timestamp: datetime) -> None:
        """Update equity curve."""
        # Calculate current equity
        open_pnl = sum(t.total_pnl for t in self.open_trades.values())
        current_equity = self.capital + open_pnl
        
        self.equity_curve.append((timestamp, current_equity))
        
        # Update peak and drawdown
        if current_equity > self.peak_capital:
            self.peak_capital = current_equity
        
        self.current_drawdown = (self.peak_capital - current_equity) / self.peak_capital
    
    def _log_status(self, timestamp: datetime) -> None:
        """Log current backtest status."""
        open_count = len(self.open_trades)
        closed_count = len([t for t in self.trades if not t.is_open])
        
        logger.info(
            f"[{timestamp}] Equity: ${self.capital:,.2f} | "
            f"Open: {open_count} | Closed: {closed_count} | "
            f"DD: {self.current_drawdown:.2%}"
        )
    
    def _calculate_results(self) -> Dict:
        """Calculate comprehensive backtest results."""
        closed_trades = [t for t in self.trades if not t.is_open]
        
        if not closed_trades:
            return {
                'total_return_pct': 0.0,
                'total_return_usd': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown_pct': 0.0,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'avg_trade_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'avg_hold_time_hours': 0,
                'total_funding_earned': 0.0,
                'total_trading_fees': 0.0,
                'total_slippage': 0.0,
                'net_funding_premium': 0.0,
                'final_capital': self.capital,
                'periods_processed': self.periods_processed
            }
        
        # Basic metrics
        total_pnl = sum(t.total_pnl for t in closed_trades)
        total_return_pct = (total_pnl / self.config.initial_capital) * 100
        
        wins = [t for t in closed_trades if t.total_pnl > 0]
        losses = [t for t in closed_trades if t.total_pnl <= 0]
        
        win_rate = len(wins) / len(closed_trades) if closed_trades else 0
        
        gross_profit = sum(t.total_pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.total_pnl for t in losses)) if losses else 0.001
        profit_factor = gross_profit / gross_loss
        
        # Calculate Sharpe ratio from equity curve
        if len(self.equity_curve) > 1:
            equity_df = pd.DataFrame(self.equity_curve, columns=['timestamp', 'equity'])
            equity_df.set_index('timestamp', inplace=True)
            equity_df['returns'] = equity_df['equity'].pct_change().dropna()
            
            if len(equity_df['returns']) > 1 and equity_df['returns'].std() > 0:
                sharpe = (equity_df['returns'].mean() / equity_df['returns'].std()) * np.sqrt(3 * 365)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0
        
        # Max drawdown
        max_drawdown = 0.0
        peak = self.config.initial_capital
        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            max_drawdown = max(max_drawdown, dd)
        
        # Trade statistics
        avg_trade_pnl = np.mean([t.total_pnl for t in closed_trades])
        avg_win = np.mean([t.total_pnl for t in wins]) if wins else 0
        avg_loss = np.mean([t.total_pnl for t in losses]) if losses else 0
        
        hold_times = [t.duration_hours for t in closed_trades if t.duration_hours]
        avg_hold_time = np.mean(hold_times) if hold_times else 0
        
        # Funding vs fees breakdown
        total_funding = sum(t.funding_earned for t in closed_trades)
        total_fees = sum(t.trading_fees for t in closed_trades)
        total_slippage = sum(t.slippage_cost for t in closed_trades)
        
        return {
            'total_return_pct': total_return_pct,
            'total_return_usd': total_pnl,
            'sharpe_ratio': sharpe,
            'max_drawdown_pct': max_drawdown * 100,
            'total_trades': len(closed_trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': win_rate * 100,
            'profit_factor': profit_factor,
            'avg_trade_pnl': avg_trade_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_hold_time_hours': avg_hold_time,
            'total_funding_earned': total_funding,
            'total_trading_fees': total_fees,
            'total_slippage': total_slippage,
            'net_funding_premium': total_funding - total_fees - total_slippage,
            'final_capital': self.capital,
            'periods_processed': self.periods_processed
        }
    
    def get_trade_report(self) -> pd.DataFrame:
        """Get detailed trade report."""
        return pd.DataFrame([
            {
                'trade_id': t.trade_id,
                'symbol': t.symbol,
                'long_exchange': t.long_exchange,
                'short_exchange': t.short_exchange,
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'duration_hours': t.duration_hours,
                'size_usd': t.size_usd,
                'funding_earned': t.funding_earned,
                'trading_fees': t.trading_fees,
                'slippage': t.slippage_cost,
                'price_pnl': t.price_pnl,
                'total_pnl': t.total_pnl,
                'return_pct': t.return_pct * 100,
                'exit_reason': t.exit_reason,
                'is_open': t.is_open
            }
            for t in self.trades
        ])
    
    def get_equity_curve(self) -> pd.DataFrame:
        """Get equity curve as DataFrame."""
        return pd.DataFrame(self.equity_curve, columns=['timestamp', 'equity'])


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create strategy
    strategy_config = StrategyConfig(
        entry_threshold=0.0002,
        exit_threshold=0.0001,
        max_positions=5,
        symbols=['BTCUSDT', 'ETHUSDT'],
        exchanges=['binance', 'bybit', 'okx']
    )
    
    risk_limits = RiskLimits(
        max_position_size_usd=50000,
        max_total_exposure_usd=200000,
        max_total_positions=5
    )
    
    strategy = FundingArbitrageStrategy(
        config=strategy_config,
        risk_limits=risk_limits
    )
    
    # Create backtester
    backtest_config = BacktestConfig(
        initial_capital=100000.0,
        maker_fee=0.0002,
        taker_fee=0.0005
    )
    
    backtester = FundingBacktester(strategy, backtest_config)
    
    # Generate data - 5 years for comprehensive testing
    loader = FundingDataLoader()
    data = loader.load_synthetic_data(
        exchanges=['binance', 'bybit', 'okx'],
        symbols=['BTCUSDT', 'ETHUSDT'],
        start_date=datetime(2021, 1, 1),
        end_date=datetime(2026, 1, 1),
        add_stress_periods=True
    )
    
    # Run backtest
    results = backtester.run(data)
    
    # Print results
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    for key, value in results.items():
        if isinstance(value, float):
            print(f"{key}: {value:.4f}")
        else:
            print(f"{key}: {value}")
    print("="*60)
