"""
Rob Hoffman Inventory Retracement Bar (IRB) Trading Strategy

A trend-following pullback strategy that identifies when short-term counter-trend
institutional activity has ceased, signaling a return to the original trend.

Author: ATLAS Alpha Hunter
Date: March 15, 2026
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum


class TradeDirection(Enum):
    """Trade direction enumeration."""
    LONG = 1
    SHORT = -1
    FLAT = 0


@dataclass
class Trade:
    """Represents a single trade."""
    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp] = None
    direction: TradeDirection = TradeDirection.FLAT
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "open"  # open, closed
    exit_reason: str = ""  # stop_loss, take_profit, signal_exit, invalidation


class HoffmanIRBStrategy:
    """
    Rob Hoffman Inventory Retracement Bar (IRB) Strategy.
    
    This strategy identifies institutional retracement bars in trending markets
    and enters on breakouts in the direction of the trend.
    
    Parameters:
    -----------
    ema_period : int
        Period for trend identification EMA (default: 20)
    irb_threshold : float
        Minimum percentage from high/low for IRB identification (default: 0.45)
    risk_per_trade : float
        Risk percentage per trade (default: 0.02 = 2%)
    risk_reward_ratio : float
        Target risk-reward ratio (default: 1.5)
    max_irb_bars : int
        Maximum bars to wait for IRB breakout (default: 20)
    use_atr_filter : bool
        Whether to filter out overextended IRBs using ATR (default: True)
    atr_multiplier : float
        Maximum IRB range as multiple of ATR (default: 2.0)
    atr_period : int
        Period for ATR calculation (default: 14)
    """
    
    def __init__(
        self,
        ema_period: int = 20,
        irb_threshold: float = 0.45,
        risk_per_trade: float = 0.02,
        risk_reward_ratio: float = 1.5,
        max_irb_bars: int = 20,
        use_atr_filter: bool = True,
        atr_multiplier: float = 2.0,
        atr_period: int = 14
    ):
        self.ema_period = ema_period
        self.irb_threshold = irb_threshold
        self.risk_per_trade = risk_per_trade
        self.risk_reward_ratio = risk_reward_ratio
        self.max_irb_bars = max_irb_bars
        self.use_atr_filter = use_atr_filter
        self.atr_multiplier = atr_multiplier
        self.atr_period = atr_period
        
        # State variables
        self.current_trade: Optional[Trade] = None
        self.trades: List[Trade] = []
        self.irb_active: bool = False
        self.irb_bar: Optional[pd.Series] = None
        self.irb_index: Optional[int] = None
        self.bars_since_irb: int = 0
        
    def calculate_ema(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return data['close'].ewm(span=self.ema_period, adjust=False).mean()
    
    def calculate_atr(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Average True Range."""
        high_low = data['high'] - data['low']
        high_close = np.abs(data['high'] - data['close'].shift())
        low_close = np.abs(data['low'] - data['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=self.atr_period).mean()
        return atr
    
    def identify_trend(self, data: pd.DataFrame, index: int) -> TradeDirection:
        """
        Identify trend direction based on EMA slope.
        
        Returns:
        --------
        TradeDirection
            LONG if uptrend, SHORT if downtrend, FLAT if no clear trend
        """
        if index < self.ema_period + 5:
            return TradeDirection.FLAT
            
        ema = self.calculate_ema(data)
        
        # Check EMA slope (using 5-bar lookback)
        current_ema = ema.iloc[index]
        prev_ema = ema.iloc[index - 5]
        
        # Calculate slope as percentage
        slope = (current_ema - prev_ema) / prev_ema
        
        # Threshold for trend (0.1% over 5 bars = ~45 degrees visually on log scale)
        trend_threshold = 0.001
        
        if slope > trend_threshold:
            return TradeDirection.LONG
        elif slope < -trend_threshold:
            return TradeDirection.SHORT
        else:
            return TradeDirection.FLAT
    
    def is_bullish_irb(self, candle: pd.Series, data: pd.DataFrame, index: int) -> bool:
        """
        Check if candle is a bullish IRB (in uptrend).
        
        Bullish IRB characteristics:
        - Bearish candle (close < open)
        - Opens and closes at least 45% below high
        - Not overextended relative to ATR
        """
        if candle['close'] >= candle['open']:  # Must be bearish candle
            return False
            
        candle_range = candle['high'] - candle['low']
        if candle_range == 0:
            return False
            
        # Check if close is at least 45% below high
        close_from_high = (candle['high'] - candle['close']) / candle_range
        open_from_high = (candle['high'] - candle['open']) / candle_range
        
        if close_from_high < self.irb_threshold or open_from_high < self.irb_threshold:
            return False
            
        # ATR filter - avoid overextended IRBs
        if self.use_atr_filter and index >= self.atr_period:
            atr = self.calculate_atr(data).iloc[index]
            if candle_range > atr * self.atr_multiplier:
                return False
                
        return True
    
    def is_bearish_irb(self, candle: pd.Series, data: pd.DataFrame, index: int) -> bool:
        """
        Check if candle is a bearish IRB (in downtrend).
        
        Bearish IRB characteristics:
        - Bullish candle (close > open)
        - Opens and closes at least 45% above low
        - Not overextended relative to ATR
        """
        if candle['close'] <= candle['open']:  # Must be bullish candle
            return False
            
        candle_range = candle['high'] - candle['low']
        if candle_range == 0:
            return False
            
        # Check if close is at least 45% above low
        close_from_low = (candle['close'] - candle['low']) / candle_range
        open_from_low = (candle['open'] - candle['low']) / candle_range
        
        if close_from_low < self.irb_threshold or open_from_low < self.irb_threshold:
            return False
            
        # ATR filter - avoid overextended IRBs
        if self.use_atr_filter and index >= self.atr_period:
            atr = self.calculate_atr(data).iloc[index]
            if candle_range > atr * self.atr_multiplier:
                return False
                
        return True
    
    def calculate_position_size(
        self, 
        account_value: float, 
        entry_price: float, 
        stop_price: float
    ) -> float:
        """
        Calculate position size based on risk percentage.
        
        position_size = (Account Value * Risk %) / |Entry - Stop|
        """
        risk_amount = account_value * self.risk_per_trade
        price_risk = abs(entry_price - stop_price)
        
        if price_risk == 0:
            return 0
            
        position_size = risk_amount / price_risk
        return position_size
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals for the entire dataset.
        
        Returns:
        --------
        pd.DataFrame
            Original data with added signal columns
        """
        df = data.copy()
        df['ema'] = self.calculate_ema(df)
        df['atr'] = self.calculate_atr(df)
        df['trend'] = 0
        df['signal'] = 0  # 1 = long entry, -1 = short entry, 0 = no signal
        df['irb_high'] = np.nan
        df['irb_low'] = np.nan
        df['stop_loss'] = np.nan
        df['take_profit'] = np.nan
        
        pending_irb = None
        pending_irb_index = None
        bars_waiting = 0
        
        for i in range(self.ema_period + 5, len(df)):
            # Identify trend
            trend = self.identify_trend(df, i)
            df.loc[df.index[i], 'trend'] = trend.value
            
            candle = df.iloc[i]
            
            # Check if we have a pending IRB waiting for breakout
            if pending_irb is not None:
                bars_waiting += 1
                
                # Check for breakout
                if trend == TradeDirection.LONG:
                    # Bullish IRB - wait for break above IRB high
                    if candle['high'] > pending_irb['high']:
                        df.loc[df.index[i], 'signal'] = 1
                        df.loc[df.index[i], 'irb_high'] = pending_irb['high']
                        df.loc[df.index[i], 'irb_low'] = pending_irb['low']
                        df.loc[df.index[i], 'stop_loss'] = pending_irb['low']
                        risk = pending_irb['high'] - pending_irb['low']
                        df.loc[df.index[i], 'take_profit'] = pending_irb['high'] + (risk * self.risk_reward_ratio)
                        pending_irb = None
                        
                elif trend == TradeDirection.SHORT:
                    # Bearish IRB - wait for break below IRB low
                    if candle['low'] < pending_irb['low']:
                        df.loc[df.index[i], 'signal'] = -1
                        df.loc[df.index[i], 'irb_high'] = pending_irb['high']
                        df.loc[df.index[i], 'irb_low'] = pending_irb['low']
                        df.loc[df.index[i], 'stop_loss'] = pending_irb['high']
                        risk = pending_irb['high'] - pending_irb['low']
                        df.loc[df.index[i], 'take_profit'] = pending_irb['low'] - (risk * self.risk_reward_ratio)
                        pending_irb = None
                
                # Cancel pending IRB if too many bars passed
                if bars_waiting > self.max_irb_bars:
                    pending_irb = None
                    bars_waiting = 0
            
            # Look for new IRB if no pending IRB
            if pending_irb is None:
                if trend == TradeDirection.LONG and self.is_bullish_irb(candle, df, i):
                    pending_irb = candle
                    pending_irb_index = i
                    bars_waiting = 0
                elif trend == TradeDirection.SHORT and self.is_bearish_irb(candle, df, i):
                    pending_irb = candle
                    pending_irb_index = i
                    bars_waiting = 0
        
        return df
    
    def run_backtest(
        self, 
        data: pd.DataFrame, 
        initial_capital: float = 10000.0,
        transaction_cost: float = 0.001
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Run backtest simulation.
        
        Parameters:
        -----------
        data : pd.DataFrame
            Price data with OHLCV columns
        initial_capital : float
            Starting capital
        transaction_cost : float
            Transaction cost as decimal (0.001 = 0.1%)
            
        Returns:
        --------
        Tuple[pd.DataFrame, pd.DataFrame]
            (signals DataFrame, equity curve DataFrame)
        """
        # Generate signals
        signals = self.generate_signals(data)
        
        # Initialize tracking variables
        equity = initial_capital
        position = 0  # 0 = flat, positive = long, negative = short
        entry_price = 0.0
        stop_loss = 0.0
        take_profit = 0.0
        
        # Track equity curve
        equity_curve = []
        
        for i in range(len(signals)):
            row = signals.iloc[i]
            current_price = row['close']
            
            # Check for exit if in position
            if position != 0:
                exit_triggered = False
                exit_price = current_price
                exit_reason = ""
                
                # Check stop loss
                if position > 0 and current_price <= stop_loss:
                    exit_triggered = True
                    exit_price = stop_loss
                    exit_reason = "stop_loss"
                elif position < 0 and current_price >= stop_loss:
                    exit_triggered = True
                    exit_price = stop_loss
                    exit_reason = "stop_loss"
                
                # Check take profit
                if position > 0 and current_price >= take_profit:
                    exit_triggered = True
                    exit_price = take_profit
                    exit_reason = "take_profit"
                elif position < 0 and current_price <= take_profit:
                    exit_triggered = True
                    exit_price = take_profit
                    exit_reason = "take_profit"
                
                # Check for opposite signal (signal exit)
                if (position > 0 and row['signal'] == -1) or (position < 0 and row['signal'] == 1):
                    exit_triggered = True
                    exit_price = current_price
                    exit_reason = "signal_exit"
                
                if exit_triggered:
                    # Calculate P&L
                    if position > 0:
                        gross_pnl = (exit_price - entry_price) * position
                    else:
                        gross_pnl = (entry_price - exit_price) * abs(position)
                    
                    # Deduct transaction costs
                    transaction_fee = (entry_price + exit_price) * abs(position) * transaction_cost
                    net_pnl = gross_pnl - transaction_fee
                    
                    equity += net_pnl
                    
                    # Record trade
                    trade = Trade(
                        entry_time=signals.index[i-1],
                        exit_time=signals.index[i],
                        direction=TradeDirection.LONG if position > 0 else TradeDirection.SHORT,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        position_size=abs(position),
                        pnl=net_pnl,
                        pnl_pct=(net_pnl / initial_capital) * 100,
                        status="closed",
                        exit_reason=exit_reason
                    )
                    self.trades.append(trade)
                    
                    position = 0
                    entry_price = 0.0
                    stop_loss = 0.0
                    take_profit = 0.0
            
            # Check for entry if flat
            if position == 0 and row['signal'] != 0:
                direction = TradeDirection.LONG if row['signal'] == 1 else TradeDirection.SHORT
                
                # Determine entry price (breakout of IRB)
                if direction == TradeDirection.LONG:
                    entry_price = row['irb_high']
                    stop_loss = row['irb_low']
                    take_profit = row['take_profit']
                else:
                    entry_price = row['irb_low']
                    stop_loss = row['irb_high']
                    take_profit = row['take_profit']
                
                # Calculate position size
                risk_amount = equity * self.risk_per_trade
                price_risk = abs(entry_price - stop_loss)
                
                if price_risk > 0:
                    position_size = risk_amount / price_risk
                    position = position_size if direction == TradeDirection.LONG else -position_size
            
            # Track equity
            unrealized_pnl = 0
            if position != 0:
                if position > 0:
                    unrealized_pnl = (current_price - entry_price) * position
                else:
                    unrealized_pnl = (entry_price - current_price) * abs(position)
            
            equity_curve.append({
                'timestamp': signals.index[i],
                'equity': equity + unrealized_pnl,
                'position': position,
                'price': current_price
            })
        
        equity_df = pd.DataFrame(equity_curve)
        equity_df.set_index('timestamp', inplace=True)
        
        return signals, equity_df
    
    def get_trade_statistics(self) -> Dict:
        """
        Calculate trade statistics.
        
        Returns:
        --------
        Dict
            Dictionary of trade statistics
        """
        if not self.trades:
            return {}
        
        closed_trades = [t for t in self.trades if t.status == "closed"]
        
        if not closed_trades:
            return {}
        
        wins = [t for t in closed_trades if t.pnl > 0]
        losses = [t for t in closed_trades if t.pnl <= 0]
        
        win_count = len(wins)
        loss_count = len(losses)
        total_trades = win_count + loss_count
        
        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0
        
        avg_win = gross_profit / win_count if win_count > 0 else 0
        avg_loss = gross_loss / loss_count if loss_count > 0 else 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': win_count,
            'losing_trades': loss_count,
            'win_rate': win_count / total_trades if total_trades > 0 else 0,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'net_profit': gross_profit - gross_loss,
            'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
            'average_win': avg_win,
            'average_loss': avg_loss,
            'average_trade': (gross_profit - gross_loss) / total_trades if total_trades > 0 else 0,
            'win_loss_ratio': avg_win / avg_loss if avg_loss > 0 else float('inf'),
        }
