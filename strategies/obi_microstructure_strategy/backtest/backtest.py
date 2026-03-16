"""
Backtesting Engine for Order Book Imbalance Strategy

Event-driven backtester that simulates execution with realistic
microstructure dynamics and latency assumptions.

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging

from src.strategy import (
    OrderBookImbalanceStrategy, OrderBookSnapshot, OrderBookLevel,
    TradeSignal, SignalType, OrderSide
)
from src.risk_manager import RiskManager
from backtest.data_loader import (
    SyntheticOrderBookGenerator, OrderBookTick, create_dataframe_from_ticks
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Represents a completed trade."""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    side: str  # 'long' or 'short'
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    holding_seconds: float
    confidence: float
    obi_entry: float


@dataclass
class BacktestResult:
    """Container for backtest results."""
    trades: List[Trade]
    equity_curve: pd.DataFrame
    signals: List[TradeSignal]
    metrics: Dict[str, Any]
    
    def __post_init__(self):
        self._calculate_metrics()
    
    def _calculate_metrics(self):
        """Calculate performance metrics."""
        if not self.trades:
            self.metrics = {
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'avg_trade': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'total_return': 0.0
            }
            return
        
        pnls = [t.pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_trades = len(pnls)
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Use pnl_pct for percentage metrics
        pnl_pcts = [t.pnl_pct for t in self.trades]
        win_pcts = [p for p in pnl_pcts if p > 0]
        loss_pcts = [p for p in pnl_pcts if p <= 0]
        
        avg_trade = np.mean(pnl_pcts)
        avg_win = np.mean(win_pcts) if win_pcts else 0.0
        avg_loss = np.mean(loss_pcts) if loss_pcts else 0.0
        
        # Sharpe ratio (hourly returns)
        if len(self.equity_curve) > 1:
            hourly_returns = self.equity_curve['equity'].pct_change().dropna()
            if len(hourly_returns) > 1 and hourly_returns.std() > 0:
                sharpe = (hourly_returns.mean() / hourly_returns.std()) * np.sqrt(252 * 24)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0
        
        # Max drawdown
        equity = self.equity_curve['equity']
        rolling_max = equity.expanding().max()
        drawdown = (equity - rolling_max) / rolling_max
        max_dd = abs(drawdown.min())
        
        # Total return
        total_return = (equity.iloc[-1] - equity.iloc[0]) / equity.iloc[0]
        
        self.metrics = {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'avg_trade': avg_trade,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_return': total_return,
            'holding_time_avg': np.mean([t.holding_seconds for t in self.trades]),
            'holding_time_med': np.median([t.holding_seconds for t in self.trades])
        }
    
    def print_summary(self):
        """Print formatted backtest summary."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS - Order Book Imbalance Strategy")
        print("=" * 60)
        
        if not self.trades:
            print("No trades executed.")
            return
        
        m = self.metrics
        print(f"\n📊 Trade Statistics:")
        print(f"  Total Trades:    {m['total_trades']:,}")
        print(f"  Win Rate:        {m['win_rate']:.1%}")
        print(f"  Profit Factor:   {m['profit_factor']:.2f}")
        
        print(f"\n💰 Performance:")
        print(f"  Total Return:    {m['total_return']:.2%}")
        print(f"  Sharpe Ratio:    {m['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown:    {m['max_drawdown']:.2%}")
        
        print(f"\n📈 Trade Details:")
        print(f"  Avg Trade:       {m['avg_trade']:.4%}")
        print(f"  Avg Win:         {m['avg_win']:.4%}")
        print(f"  Avg Loss:        {m['avg_loss']:.4%}")
        
        print(f"\n⏱️  Timing:")
        print(f"  Avg Hold Time:   {m['holding_time_avg']:.1f}s")
        print(f"  Med Hold Time:   {m['holding_time_med']:.1f}s")
        
        print("=" * 60)


class BacktestEngine:
    """
    Event-driven backtesting engine for OBI strategy.
    """
    
    def __init__(self, 
                 strategy_config: Dict[str, Any],
                 risk_config: Dict[str, Any],
                 initial_capital: float = 100000.0,
                 fee_rate: float = 0.0005,  # 5 bps taker fee
                 slippage_bps: float = 0.5):  # 0.5 bps slippage
        """
        Initialize backtest engine.
        
        Args:
            strategy_config: Strategy configuration
            risk_config: Risk manager configuration
            initial_capital: Starting capital
            fee_rate: Trading fee rate per trade
            slippage_bps: Slippage in basis points
        """
        self.strategy = OrderBookImbalanceStrategy(strategy_config)
        self.risk_manager = RiskManager(risk_config)
        
        self.initial_capital = initial_capital
        self.equity = initial_capital
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        
        # State
        self.position: Optional[Dict] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        self.signals: List[TradeSignal] = []
        
    def _tick_to_snapshot(self, tick: OrderBookTick) -> OrderBookSnapshot:
        """Convert OrderBookTick to OrderBookSnapshot."""
        bids = [OrderBookLevel(price=p, volume=v, side=OrderSide.BID) 
                for p, v in tick.bids]
        asks = [OrderBookLevel(price=p, volume=v, side=OrderSide.ASK) 
                for p, v in tick.asks]
        
        return OrderBookSnapshot(
            timestamp=tick.timestamp,
            bids=bids,
            asks=asks,
            mid_price=tick.mid_price,
            spread=tick.spread
        )
    
    def _calculate_entry_price(self, tick: OrderBookTick, 
                               side: str) -> float:
        """
        Calculate realistic entry price with slippage.
        
        Args:
            tick: Current order book tick
            side: 'long' or 'short'
            
        Returns:
            Entry price
        """
        if side == 'long':
            # Buy at ask + slippage
            base_price = tick.asks[0][0] if tick.asks else tick.mid_price
            slippage = base_price * self.slippage_bps / 10000
            return base_price + slippage
        else:
            # Sell at bid - slippage
            base_price = tick.bids[0][0] if tick.bids else tick.mid_price
            slippage = base_price * self.slippage_bps / 10000
            return base_price - slippage
    
    def _calculate_exit_price(self, tick: OrderBookTick,
                              side: str) -> float:
        """
        Calculate realistic exit price with slippage.
        
        Args:
            tick: Current order book tick
            side: 'long' or 'short'
            
        Returns:
            Exit price
        """
        if side == 'long':
            # Sell at bid - slippage
            base_price = tick.bids[0][0] if tick.bids else tick.mid_price
            slippage = base_price * self.slippage_bps / 10000
            return base_price - slippage
        else:
            # Buy at ask + slippage
            base_price = tick.asks[0][0] if tick.asks else tick.mid_price
            slippage = base_price * self.slippage_bps / 10000
            return base_price + slippage
    
    def _enter_position(self, tick: OrderBookTick, signal: TradeSignal):
        """
        Enter a new position.
        
        Args:
            tick: Current tick
            signal: Trade signal
        """
        side = 'long' if signal.signal_type == SignalType.LONG else 'short'
        entry_price = self._calculate_entry_price(tick, side)
        
        # Calculate position size
        sizing = self.risk_manager.calculate_position_size(
            confidence=signal.confidence,
            obi_magnitude=abs(signal.obi_l1),
            current_volatility=0.5,  # Simplified
            avg_volatility=0.5
        )
        
        position_value = self.equity * sizing.size_pct
        size = position_value / entry_price
        
        # Apply fees
        fee = position_value * self.fee_rate
        self.equity -= fee
        
        self.position = {
            'side': side,
            'entry_price': entry_price,
            'entry_time': tick.timestamp,
            'size': size,
            'confidence': signal.confidence,
            'obi_entry': signal.obi_l1
        }
        
        logger.debug(f"Entered {side} position at {entry_price:.2f}")
    
    def _exit_position(self, tick: OrderBookTick, reason: str):
        """
        Exit current position.
        
        Args:
            tick: Current tick
            reason: Exit reason
        """
        if not self.position:
            return
        
        pos = self.position
        exit_price = self._calculate_exit_price(tick, pos['side'])
        
        # Calculate P&L
        if pos['side'] == 'long':
            pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price']
        else:
            pnl_pct = (pos['entry_price'] - exit_price) / pos['entry_price']
        
        position_value = pos['size'] * pos['entry_price']
        pnl = position_value * pnl_pct
        
        # Apply fees
        fee = position_value * self.fee_rate
        pnl -= fee
        pnl_pct -= self.fee_rate * 2  # Entry + exit fees
        
        # Update equity
        self.equity += pnl
        
        holding_seconds = (tick.timestamp - pos['entry_time']).total_seconds()
        
        trade = Trade(
            entry_time=pos['entry_time'],
            exit_time=tick.timestamp,
            entry_price=pos['entry_price'],
            exit_price=exit_price,
            side=pos['side'],
            size=pos['size'],
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            holding_seconds=holding_seconds,
            confidence=pos['confidence'],
            obi_entry=pos['obi_entry']
        )
        
        self.trades.append(trade)
        self.risk_manager.record_trade(pnl_pct, tick.timestamp)
        
        logger.debug(f"Exited {pos['side']} position at {exit_price:.2f}, "
                    f"P&L: {pnl_pct:.4%}, Reason: {reason}")
        
        self.position = None
    
    def _update_position(self, tick: OrderBookTick):
        """
        Update existing position and check for exits.
        
        Args:
            tick: Current tick
        """
        if not self.position:
            return
        
        pos = self.position
        book = self._tick_to_snapshot(tick)
        
        # Calculate current P&L
        if pos['side'] == 'long':
            current_price = tick.bids[0][0] if tick.bids else tick.mid_price
            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
        else:
            current_price = tick.asks[0][0] if tick.asks else tick.mid_price
            pnl_pct = (pos['entry_price'] - current_price) / pos['entry_price']
        
        # Check exit conditions
        holding_seconds = (tick.timestamp - pos['entry_time']).total_seconds()
        
        # Time exit
        if holding_seconds >= self.strategy.max_holding_seconds:
            self._exit_position(tick, "time_exit")
            return
        
        # Profit target
        if pnl_pct >= self.strategy.profit_target_bps / 10000:
            self._exit_position(tick, "profit_target")
            return
        
        # Stop loss
        if pnl_pct <= -self.strategy.stop_loss_bps / 10000:
            self._exit_position(tick, "stop_loss")
            return
        
        # OBI reversal
        current_obi = self.strategy.calculate_obi_level1(book)
        if pos['side'] == 'long' and current_obi < 0:
            self._exit_position(tick, "obi_reversal")
            return
        elif pos['side'] == 'short' and current_obi > 0:
            self._exit_position(tick, "obi_reversal")
            return
    
    def run(self, ticks: List[OrderBookTick]) -> BacktestResult:
        """
        Run backtest on tick data.
        
        Args:
            ticks: List of order book ticks
            
        Returns:
            BacktestResult object
        """
        logger.info(f"Starting backtest with {len(ticks):,} ticks")
        logger.info(f"Initial capital: ${self.initial_capital:,.2f}")
        
        for i, tick in enumerate(ticks):
            # Update equity curve
            self.equity_curve.append({
                'timestamp': tick.timestamp,
                'equity': self.equity,
                'price': tick.mid_price
            })
            
            # Check if trading allowed
            can_trade, reason = self.risk_manager.can_trade(tick.timestamp)
            
            # Update position
            if self.position:
                self._update_position(tick)
            
            # Generate signal if no position and trading allowed
            if not self.position and can_trade:
                book = self._tick_to_snapshot(tick)
                signal = self.strategy.generate_signal(book, tick.trade_volume)
                
                if signal:
                    self.signals.append(signal)
                    self._enter_position(tick, signal)
            
            # Progress update
            if (i + 1) % 100000 == 0:
                logger.info(f"Processed {i+1:,} ticks, "
                           f"Trades: {len(self.trades)}, "
                           f"Equity: ${self.equity:,.2f}")
        
        # Close any open position at end
        if self.position and ticks:
            self._exit_position(ticks[-1], "end_of_data")
        
        # Create results
        equity_df = pd.DataFrame(self.equity_curve)
        
        result = BacktestResult(
            trades=self.trades,
            equity_curve=equity_df,
            signals=self.signals,
            metrics={}
        )
        
        logger.info(f"Backtest complete. Total trades: {len(self.trades)}")
        
        return result


def run_backtest(duration_hours: float = 24,
                 random_seed: int = 42) -> BacktestResult:
    """
    Run a complete backtest with synthetic data.
    
    Args:
        duration_hours: Duration of backtest
        random_seed: Random seed for reproducibility
        
    Returns:
        BacktestResult
    """
    # Strategy configuration
    strategy_config = {
        'obi_long_threshold': 0.4,
        'obi_short_threshold': -0.4,
        'obi_depth_threshold': 0.3,
        'persistence_ticks': 3,
        'spread_max_bps': 5.0,
        'vol_velocity_threshold': 0.5,
        'max_holding_seconds': 30,
        'profit_target_bps': 5.0,
        'stop_loss_bps': 3.0,
        'micro_ema_span': 50
    }
    
    # Risk configuration
    risk_config = {
        'daily_loss_limit': 0.01,
        'hourly_loss_limit': 0.005,
        'max_drawdown_limit': 0.04,
        'max_consecutive_losses': 5,
        'max_daily_trades': 200,
        'base_position_pct': 0.01,
        'max_position_pct': 0.015
    }
    
    # Generate data
    logger.info("Generating synthetic order book data...")
    gen = SyntheticOrderBookGenerator(
        base_price=65000.0,
        random_seed=random_seed
    )
    
    ticks = list(gen.generate_data(
        duration_hours=duration_hours,
        tick_frequency_ms=100
    ))
    
    # Run backtest
    engine = BacktestEngine(
        strategy_config=strategy_config,
        risk_config=risk_config,
        initial_capital=100000.0,
        fee_rate=0.0005,
        slippage_bps=0.5
    )
    
    result = engine.run(ticks)
    
    return result


if __name__ == '__main__':
    # Run example backtest
    result = run_backtest(duration_hours=6, random_seed=42)
    result.print_summary()
