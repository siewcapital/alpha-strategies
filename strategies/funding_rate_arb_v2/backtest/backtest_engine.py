"""
Funding Rate Arbitrage Backtest Engine

Event-driven backtesting with realistic transaction costs,
slippage modeling, and funding payment simulation.

Author: ATLAS
Date: March 30, 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

# Import strategy components
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from strategy import (
    FundingArbitrageStrategy, FundingAnalyzer, SignalGenerator, RiskManager,
    FundingPrediction, FundingOpportunity, Signal, Position, Portfolio,
    SignalType, PositionSide
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    start_date: datetime
    end_date: datetime
    initial_capital: float = 100000.0
    
    # Transaction costs
    maker_fee: float = 0.0002  # 0.02%
    taker_fee: float = 0.0005  # 0.05%
    slippage_bps: float = 2.0  # 2 basis points
    
    # Execution
    use_maker_only: bool = True
    execution_delay_ms: int = 500
    partial_fill_prob: float = 0.05  # 5% chance of partial fill
    
    # Strategy params
    entry_threshold: float = 0.15  # 15% annualized
    exit_threshold: float = 0.05   # 5% annualized
    min_persistence: float = 0.7
    max_positions: int = 5
    max_position_usd: float = 50000.0
    min_position_usd: float = 5000.0
    default_leverage: float = 2.0
    max_utilization: float = 0.5
    max_hold_hours: float = 48.0
    
    def to_strategy_config(self) -> Dict[str, Any]:
        """Convert to strategy configuration dict."""
        return {
            "initial_capital": self.initial_capital,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "min_persistence": self.min_persistence,
            "max_positions": self.max_positions,
            "max_position_usd": self.max_position_usd,
            "min_position_usd": self.min_position_usd,
            "default_leverage": self.default_leverage,
            "max_utilization": self.max_utilization,
            "max_hold_hours": self.max_hold_hours,
        }


@dataclass
class Trade:
    """Executed trade record."""
    trade_id: str
    timestamp: datetime
    symbol: str
    exchange: str
    side: PositionSide
    size_usd: float
    entry_price: float
    exit_price: Optional[float] = None
    leverage: float = 1.0
    funding_earned: float = 0.0
    fees_paid: float = 0.0
    exit_timestamp: Optional[datetime] = None
    exit_reason: Optional[str] = None
    
    @property
    def is_closed(self) -> bool:
        return self.exit_price is not None
    
    @property
    def pnl(self) -> float:
        """Calculate PnL including funding and fees."""
        if not self.is_closed:
            return 0.0
        
        # Price PnL (should be ~0 for delta-neutral)
        if self.side == PositionSide.LONG:
            price_pnl = (self.exit_price - self.entry_price) / self.entry_price * self.size_usd
        else:
            price_pnl = (self.entry_price - self.exit_price) / self.entry_price * self.size_usd
        
        # Include funding earned/paid and fees
        return price_pnl + self.funding_earned - self.fees_paid
    
    @property
    def hold_time_hours(self) -> float:
        if not self.exit_timestamp:
            return 0.0
        return (self.exit_timestamp - self.timestamp).total_seconds() / 3600


@dataclass
class BacktestResult:
    """Complete backtest results."""
    config: BacktestConfig
    trades: List[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    funding_events: List[Dict] = field(default_factory=list)
    
    # Performance metrics
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    calmar_ratio: float = 0.0
    total_trades: int = 0
    avg_hold_time: float = 0.0
    
    def calculate_metrics(self):
        """Calculate all performance metrics."""
        if not self.trades:
            logger.warning("No trades to calculate metrics")
            return
        
        closed_trades = [t for t in self.trades if t.is_closed]
        if not closed_trades:
            logger.warning("No closed trades to calculate metrics")
            return
        
        # Basic counts
        self.total_trades = len(closed_trades)
        
        # PnL statistics
        pnls = [t.pnl for t in closed_trades]
        winning_trades = [p for p in pnls if p > 0]
        losing_trades = [p for p in pnls if p <= 0]
        
        self.win_rate = len(winning_trades) / len(pnls) if pnls else 0
        
        gross_profit = sum(winning_trades) if winning_trades else 0
        gross_loss = abs(sum(losing_trades)) if losing_trades else 0
        self.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Returns
        total_pnl = sum(pnls)
        self.total_return = total_pnl / self.config.initial_capital
        
        # Annualized return
        if len(self.equity_curve) > 1:
            days = (self.equity_curve.index[-1] - self.equity_curve.index[0]).days
            if days > 0:
                self.annualized_return = (1 + self.total_return) ** (365 / days) - 1
        
        # Sharpe ratio (assuming risk-free rate = 0)
        if len(self.equity_curve) > 1:
            returns = self.equity_curve.pct_change().dropna()
            if len(returns) > 1 and returns.std() > 0:
                self.sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(365)
        
        # Max drawdown
        if len(self.equity_curve) > 0:
            rolling_max = self.equity_curve.expanding().max()
            drawdown = (self.equity_curve - rolling_max) / rolling_max
            self.max_drawdown = abs(drawdown.min())
            
            # Drawdown duration
            in_drawdown = drawdown < 0
            drawdown_periods = []
            current_duration = 0
            for is_dd in in_drawdown:
                if is_dd:
                    current_duration += 1
                else:
                    if current_duration > 0:
                        drawdown_periods.append(current_duration)
                    current_duration = 0
            if current_duration > 0:
                drawdown_periods.append(current_duration)
            self.max_drawdown_duration = max(drawdown_periods) if drawdown_periods else 0
        
        # Calmar ratio
        if self.max_drawdown > 0:
            self.calmar_ratio = self.annualized_return / self.max_drawdown
        
        # Average hold time
        hold_times = [t.hold_time_hours for t in closed_trades if t.is_closed]
        self.avg_hold_time = np.mean(hold_times) if hold_times else 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary summary."""
        return {
            "performance_metrics": {
                "total_return": f"{self.total_return:.2%}",
                "annualized_return": f"{self.annualized_return:.2%}",
                "sharpe_ratio": f"{self.sharpe_ratio:.2f}",
                "max_drawdown": f"{self.max_drawdown:.2%}",
                "max_drawdown_duration_days": self.max_drawdown_duration,
                "calmar_ratio": f"{self.calmar_ratio:.2f}",
                "win_rate": f"{self.win_rate:.2%}",
                "profit_factor": f"{self.profit_factor:.2f}",
                "total_trades": self.total_trades,
                "avg_hold_time_hours": f"{self.avg_hold_time:.1f}",
            },
            "config": {
                "entry_threshold": f"{self.config.entry_threshold:.2%}",
                "exit_threshold": f"{self.config.exit_threshold:.2%}",
                "maker_fee": f"{self.config.maker_fee:.4%}",
                "slippage_bps": self.config.slippage_bps,
                "use_maker_only": self.config.use_maker_only,
            }
        }
    
    def print_summary(self):
        """Print formatted summary."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS - Funding Rate Arbitrage V2")
        print("=" * 60)
        
        metrics = self.to_dict()["performance_metrics"]
        for key, value in metrics.items():
            print(f"{key.replace('_', ' ').title():30s}: {value}")
        
        print("\n" + "-" * 60)
        print("Transaction Costs")
        print("-" * 60)
        
        total_fees = sum(t.fees_paid for t in self.trades)
        total_funding = sum(t.funding_earned for t in self.trades)
        total_slippage = sum(t.fees_paid * 0.4 for t in self.trades)  # Estimate
        
        print(f"{'Total Fees Paid':30s}: ${total_fees:,.2f}")
        print(f"{'Total Funding Earned':30s}: ${total_funding:,.2f}")
        print(f"{'Net from Funding':30s}: ${total_funding - total_fees:,.2f}")
        
        print("=" * 60)


class BacktestEngine:
    """
    Event-driven backtest engine for funding rate arbitrage.
    Simulates realistic execution with transaction costs.
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.strategy = FundingArbitrageStrategy(config=config.to_strategy_config())
        self.result = BacktestResult(config=config)
        
        # State tracking
        self.current_time: Optional[datetime] = None
        self.active_positions: Dict[str, Dict] = {}  # position_id -> position details
        self.price_data: Dict[str, pd.Series] = {}  # (exchange, symbol) -> prices
        self.funding_schedule: List[datetime] = []  # Funding payment times
    
    def load_historical_data(self, data_dir: Path) -> bool:
        """
        Load historical funding rate and price data.
        
        Expected file format (parquet or CSV):
        - funding_rates.parquet: columns [timestamp, exchange, symbol, funding_rate]
        - prices.parquet: columns [timestamp, exchange, symbol, mark_price, index_price]
        """
        funding_file = data_dir / "funding_rates.parquet"
        prices_file = data_dir / "prices.parquet"
        
        if not funding_file.exists():
            logger.warning(f"Funding data not found at {funding_file}")
            return False
        
        # Load funding rates
        if funding_file.suffix == '.parquet':
            self.funding_df = pd.read_parquet(funding_file)
        else:
            self.funding_df = pd.read_csv(funding_file)
            self.funding_df['timestamp'] = pd.to_datetime(self.funding_df['timestamp'])
        
        # Load prices if available
        if prices_file.exists():
            if prices_file.suffix == '.parquet':
                self.prices_df = pd.read_parquet(prices_file)
            else:
                self.prices_df = pd.read_csv(prices_file)
                self.prices_df['timestamp'] = pd.to_datetime(self.prices_df['timestamp'])
        else:
            self.prices_df = None
            logger.warning("Price data not found, using synthetic prices")
        
        logger.info(f"Loaded {len(self.funding_df)} funding rate records")
        return True
    
    def generate_synthetic_data(self, exchanges: List[str], symbols: List[str],
                               days: int = 1095) -> pd.DataFrame:
        """
        Generate synthetic funding rate data for backtesting.
        Uses Ornstein-Uhlenbeck process with cross-exchange correlations.
        """
        logger.info(f"Generating {days} days of synthetic data for {len(exchanges)} exchanges, {len(symbols)} symbols")
        
        records = []
        start_date = self.config.start_date
        
        # Generate funding times (every 8 hours)
        funding_times = pd.date_range(
            start=start_date,
            periods=days * 3,  # 3 funding periods per day
            freq='8H'
        )
        
        for symbol in symbols:
            # Base funding parameters for this symbol
            base_funding = np.random.uniform(-0.0001, 0.0003)  # Slight positive bias
            volatility = np.random.uniform(0.0002, 0.0008)  # Symbol-specific volatility
            
            for exchange in exchanges:
                # Exchange-specific adjustment
                exchange_bias = np.random.uniform(-0.00005, 0.00005)
                
                # Generate OU process
                theta = 0.3  # Mean reversion speed
                mu = base_funding + exchange_bias
                
                funding_rates = []
                current_rate = mu
                
                for _ in funding_times:
                    # OU step
                    dt = 1.0
                    dW = np.random.normal(0, np.sqrt(dt))
                    current_rate += theta * (mu - current_rate) * dt + volatility * dW
                    
                    # Clamp to realistic bounds
                    current_rate = max(-0.01, min(0.01, current_rate))
                    funding_rates.append(current_rate)
                
                # Create records
                for t, rate in zip(funding_times, funding_rates):
                    records.append({
                        'timestamp': t,
                        'exchange': exchange,
                        'symbol': symbol,
                        'funding_rate': rate
                    })
        
        df = pd.DataFrame(records)
        self.funding_df = df
        logger.info(f"Generated {len(df)} synthetic funding records")
        return df
    
    def _get_price(self, exchange: str, symbol: str, timestamp: datetime) -> float:
        """Get price for exchange-symbol at timestamp."""
        if self.prices_df is not None:
            # Look up actual price
            mask = (
                (self.prices_df['exchange'] == exchange) &
                (self.prices_df['symbol'] == symbol) &
                (self.prices_df['timestamp'] <= timestamp)
            )
            prices = self.prices_df[mask]
            if len(prices) > 0:
                return prices.iloc[-1]['mark_price']
        
        # Generate synthetic price
        # Use symbol hash for deterministic "price"
        base_price = hash(symbol) % 10000 + 20000  # $20K-$30K base
        noise = np.random.normal(0, base_price * 0.001)
        return base_price + noise
    
    def _calculate_execution_cost(self, size_usd: float, use_maker: bool = True) -> Tuple[float, float]:
        """
        Calculate execution cost (fees + slippage).
        
        Returns: (total_cost, fees_only)
        """
        fee_rate = self.config.maker_fee if use_maker else self.config.taker_fee
        fees = size_usd * fee_rate
        slippage = size_usd * (self.config.slippage_bps / 10000)
        
        return fees + slippage, fees
    
    def _process_funding_payment(self, timestamp: datetime):
        """Process funding payments for all active positions."""
        for pos_id, position in self.active_positions.items():
            if position['status'] != 'open':
                continue
            
            symbol = position['symbol']
            
            # Long leg funding
            long_exchange = position['long_exchange']
            long_funding = self._get_funding_rate(long_exchange, symbol, timestamp)
            if long_funding:
                # Long pays funding if positive, receives if negative
                long_payment = -position['long_size'] * long_funding['funding_rate']
                position['funding_earned'] += long_payment
                position['long_trades'][0].funding_earned += long_payment
            
            # Short leg funding
            short_exchange = position['short_exchange']
            short_funding = self._get_funding_rate(short_exchange, symbol, timestamp)
            if short_funding:
                # Short receives funding if positive, pays if negative
                short_payment = position['short_size'] * short_funding['funding_rate']
                position['funding_earned'] += short_payment
                position['short_trades'][0].funding_earned += short_payment
            
            # Log funding event
            self.result.funding_events.append({
                'timestamp': timestamp,
                'position_id': pos_id,
                'long_payment': long_payment if long_funding else 0,
                'short_payment': short_payment if short_funding else 0,
            })
    
    def _get_funding_rate(self, exchange: str, symbol: str, timestamp: datetime) -> Optional[Dict]:
        """Get funding rate for exchange-symbol at timestamp."""
        mask = (
            (self.funding_df['exchange'] == exchange) &
            (self.funding_df['symbol'] == symbol) &
            (self.funding_df['timestamp'] <= timestamp)
        )
        rates = self.funding_df[mask]
        if len(rates) > 0:
            return rates.iloc[-1].to_dict()
        return None
    
    def _execute_entry(self, signal: Signal, timestamp: datetime) -> Optional[Trade]:
        """Execute entry signal and return trade record."""
        price = self._get_price(signal.exchange, signal.symbol, timestamp)
        
        # Calculate costs
        total_cost, fees = self._calculate_execution_cost(
            signal.size_usd, use_maker=self.config.use_maker_only
        )
        
        trade = Trade(
            trade_id=str(uuid.uuid4())[:8],
            timestamp=timestamp,
            symbol=signal.symbol,
            exchange=signal.exchange,
            side=signal.side,
            size_usd=signal.size_usd,
            entry_price=price,
            leverage=signal.leverage,
            fees_paid=fees
        )
        
        return trade
    
    def _execute_exit(self, signal: Signal, position: Dict, timestamp: datetime) -> Optional[Trade]:
        """Execute exit signal and return trade record."""
        price = self._get_price(signal.exchange, signal.symbol, timestamp)
        
        # Find the original entry trade
        if signal.side == PositionSide.LONG:
            entry_trade = position.get('long_trades', [None])[0]
        else:
            entry_trade = position.get('short_trades', [None])[0]
        
        if entry_trade is None:
            logger.warning(f"No entry trade found for exit signal: {signal}")
            return None
        
        # Calculate costs
        total_cost, fees = self._calculate_execution_cost(
            signal.size_usd, use_maker=self.config.use_maker_only
        )
        
        # Update entry trade with exit details
        entry_trade.exit_price = price
        entry_trade.exit_timestamp = timestamp
        entry_trade.exit_reason = signal.metadata.get('exit_reason', 'unknown')
        entry_trade.fees_paid += fees  # Add exit fees
        
        return entry_trade
    
    def run(self) -> BacktestResult:
        """
        Run the full backtest.
        """
        logger.info("Starting backtest...")
        
        if not hasattr(self, 'funding_df') or self.funding_df is None:
            logger.error("No data loaded. Call load_historical_data() or generate_synthetic_data() first.")
            return self.result
        
        # Get unique timestamps
        timestamps = sorted(self.funding_df['timestamp'].unique())
        
        # Filter by date range
        timestamps = [
            t for t in timestamps 
            if self.config.start_date <= pd.to_datetime(t) <= self.config.end_date
        ]
        
        logger.info(f"Running backtest over {len(timestamps)} funding periods")
        
        # Get unique exchanges and symbols
        exchanges = self.funding_df['exchange'].unique().tolist()
        symbols = self.funding_df['symbol'].unique().tolist()
        
        # Initialize equity curve
        equity_values = []
        equity_timestamps = []
        
        # Run simulation
        for i, timestamp in enumerate(timestamps):
            self.current_time = pd.to_datetime(timestamp)
            
            # Get funding data for this timestamp
            current_funding = self.funding_df[self.funding_df['timestamp'] == timestamp]
            
            # Convert to strategy format
            funding_data = current_funding.to_dict('records')
            
            # Update strategy and generate signals
            self.strategy.update_funding_data(funding_data)
            predictions = self.strategy.generate_predictions(exchanges, symbols)
            
            # Update current predictions in signal generator
            self.strategy.current_predictions = {
                (p.exchange, p.symbol): p for p in predictions
            }
            
            # Generate signals
            signals = self.strategy.generate_signals()
            
            # Process signals
            for signal in signals:
                if signal.signal_type in [SignalType.ENTRY_LONG, SignalType.ENTRY_SHORT]:
                    trade = self._execute_entry(signal, self.current_time)
                    if trade:
                        self.result.trades.append(trade)
                        
                        # Track position
                        symbol = signal.symbol
                        if symbol not in self.active_positions:
                            self.active_positions[symbol] = {
                                'symbol': symbol,
                                'long_exchange': None,
                                'short_exchange': None,
                                'long_size': 0,
                                'short_size': 0,
                                'long_trades': [],
                                'short_trades': [],
                                'funding_earned': 0,
                                'status': 'open',
                                'entry_time': self.current_time
                            }
                        
                        pos = self.active_positions[symbol]
                        if signal.side == PositionSide.LONG:
                            pos['long_exchange'] = signal.exchange
                            pos['long_size'] = signal.size_usd
                            pos['long_trades'].append(trade)
                        else:
                            pos['short_exchange'] = signal.exchange
                            pos['short_size'] = signal.size_usd
                            pos['short_trades'].append(trade)
                
                elif signal.signal_type == SignalType.EXIT:
                    symbol = signal.symbol
                    if symbol in self.active_positions:
                        position = self.active_positions[symbol]
                        trade = self._execute_exit(signal, position, self.current_time)
                        
                        # Check if both legs are closed
                        if signal.side == PositionSide.LONG:
                            position['long_trades'][-1].exit_price = signal.metadata.get('exit_price')
                        else:
                            position['short_trades'][-1].exit_price = signal.metadata.get('exit_price')
                        
                        # Mark position closed if both legs done
                        long_closed = position['long_trades'] and position['long_trades'][0].is_closed
                        short_closed = position['short_trades'] and position['short_trades'][0].is_closed
                        
                        if long_closed and short_closed:
                            position['status'] = 'closed'
                            position['exit_time'] = self.current_time
                
            # Process funding payments
            self._process_funding_payment(self.current_time)
            
            # Calculate equity
            realized_pnl = sum(t.pnl for t in self.result.trades if t.is_closed)
            unrealized_pnl = sum(t.pnl for t in self.result.trades if not t.is_closed)
            current_equity = self.config.initial_capital + realized_pnl + unrealized_pnl
            
            equity_values.append(current_equity)
            equity_timestamps.append(self.current_time)
            
            # Progress logging
            if i % 100 == 0:
                logger.info(f"Processed {i}/{len(timestamps)} periods. Equity: ${current_equity:,.2f}")
        
        # Build equity curve
        self.result.equity_curve = pd.Series(equity_values, index=equity_timestamps)
        
        # Calculate metrics
        self.result.calculate_metrics()
        
        logger.info("Backtest complete!")
        return self.result


def run_backtest_example():
    """Run example backtest with synthetic data."""
    config = BacktestConfig(
        start_date=datetime(2021, 1, 1),
        end_date=datetime(2024, 1, 1),
        initial_capital=100000,
        entry_threshold=0.15,
        exit_threshold=0.05,
        maker_fee=0.0002,
        slippage_bps=2.0
    )
    
    engine = BacktestEngine(config)
    
    # Generate synthetic data
    engine.generate_synthetic_data(
        exchanges=['binance', 'bybit', 'okx'],
        symbols=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        days=1095  # 3 years
    )
    
    # Run backtest
    result = engine.run()
    
    # Print results
    result.print_summary()
    
    return result


if __name__ == "__main__":
    run_backtest_example()
