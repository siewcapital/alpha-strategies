"""
SOL RSI Mean Reversion Strategy

Strategy: Mean reversion on SOL/USDT using RSI oversold/overbought signals
with trend confirmation and ATR-based position sizing.

Entry Logic:
- Long when RSI(14) < 30 AND price > EMA(50) (oversold in uptrend)
- Short when RSI(14) > 70 AND price < EMA(50) (overbought in downtrend)

Exit Logic:
- RSI reversion to 50
- Stop loss at 2x ATR
- Take profit at 3x ATR (1.5:1 R:R)

Timeframe: 1H for signals, 15m for execution
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json


@dataclass
class Trade:
    """Single trade record."""
    entry_time: datetime
    exit_time: Optional[datetime] = None
    direction: str = ""  # 'long' or 'short'
    entry_price: float = 0.0
    exit_price: float = 0.0
    size_usd: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    duration_hours: float = 0.0


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    symbol: str = "SOLUSDT"
    timeframe: str = "1h"
    initial_capital: float = 10000.0
    leverage: float = 1.0
    
    # RSI Parameters
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    rsi_exit: float = 50.0
    
    # Trend Filter
    ema_period: int = 50
    
    # ATR Parameters
    atr_period: int = 14
    stop_atr_mult: float = 2.0
    take_profit_atr_mult: float = 3.0
    
    # Risk Management
    risk_per_trade: float = 0.02  # 2% per trade
    max_positions: int = 3
    
    # Costs
    commission_rate: float = 0.0005  # 0.05%
    slippage: float = 0.0002


class SOLRSIMeanReversion:
    """
    SOL RSI Mean Reversion Strategy.
    
    Captures reversions from oversold/overbought conditions
    while respecting the overall trend.
    """
    
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_position: Optional[Trade] = None
        
    def calculate_rsi(self, prices: np.ndarray, period: int = 14) -> np.ndarray:
        """Calculate RSI for price series."""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gains = pd.Series(gains).rolling(window=period).mean().values
        avg_losses = pd.Series(losses).rolling(window=period).mean().values
        
        rs = avg_gains / (avg_losses + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        # Pad with NaN to match input length
        rsi = np.concatenate([[np.nan], rsi])
        return rsi
    
    def calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Calculate EMA."""
        return pd.Series(prices).ewm(span=period, adjust=False).mean().values
    
    def calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """Calculate Average True Range."""
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        atr = pd.Series(tr).rolling(window=period).mean().values
        # Pad with NaN to match input length
        atr = np.concatenate([[np.nan], atr])
        return atr
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals."""
        df = df.copy()
        
        # Calculate indicators
        df['rsi'] = self.calculate_rsi(df['close'].values, self.config.rsi_period)
        df['ema'] = self.calculate_ema(df['close'].values, self.config.ema_period)
        df['atr'] = self.calculate_atr(
            df['high'].values, 
            df['low'].values, 
            df['close'].values, 
            self.config.atr_period
        )
        
        # Initialize signal columns
        df['long_signal'] = False
        df['short_signal'] = False
        df['exit_signal'] = False
        
        # Skip NaN periods
        valid_idx = df['rsi'].notna() & df['ema'].notna() & df['atr'].notna()
        
        # Long signal: RSI oversold + price above EMA (uptrend)
        df.loc[valid_idx, 'long_signal'] = (
            (df.loc[valid_idx, 'rsi'] < self.config.rsi_oversold) & 
            (df.loc[valid_idx, 'close'] > df.loc[valid_idx, 'ema'])
        )
        
        # Short signal: RSI overbought + price below EMA (downtrend)
        df.loc[valid_idx, 'short_signal'] = (
            (df.loc[valid_idx, 'rsi'] > self.config.rsi_overbought) & 
            (df.loc[valid_idx, 'close'] < df.loc[valid_idx, 'ema'])
        )
        
        return df
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """
        Run full backtest on historical data.
        
        Args:
            df: DataFrame with columns: timestamp, open, high, low, close, volume
        
        Returns:
            Dictionary with backtest results
        """
        df = self.generate_signals(df)
        
        capital = self.config.initial_capital
        position = None
        
        for i in range(len(df)):
            if i < max(self.config.rsi_period, self.config.ema_period, self.config.atr_period):
                continue
                
            row = df.iloc[i]
            timestamp = row['timestamp'] if 'timestamp' in row else pd.Timestamp.now()
            
            # Check for position exit
            if position is not None:
                # Calculate unrealized PnL
                if position.direction == 'long':
                    unrealized_pct = (row['close'] - position.entry_price) / position.entry_price
                else:
                    unrealized_pct = (position.entry_price - row['close']) / position.entry_price
                
                unrealized_pnl = position.size_usd * unrealized_pct
                atr = row['atr']
                
                # Exit conditions
                exit_triggered = False
                exit_reason = ""
                
                # RSI exit (mean reversion)
                if position.direction == 'long' and row['rsi'] >= self.config.rsi_exit:
                    exit_triggered = True
                    exit_reason = "rsi_target"
                elif position.direction == 'short' and row['rsi'] <= self.config.rsi_exit:
                    exit_triggered = True
                    exit_reason = "rsi_target"
                
                # Stop loss (2x ATR)
                stop_distance = (self.config.stop_atr_mult * atr) / position.entry_price
                if unrealized_pct < -stop_distance:
                    exit_triggered = True
                    exit_reason = "stop_loss"
                
                # Take profit (3x ATR - 1.5:1 R:R)
                tp_distance = (self.config.take_profit_atr_mult * atr) / position.entry_price
                if unrealized_pct > tp_distance:
                    exit_triggered = True
                    exit_reason = "take_profit"
                
                if exit_triggered:
                    # Close position
                    position.exit_time = timestamp
                    position.exit_price = row['close']
                    position.pnl = unrealized_pnl
                    position.pnl_pct = unrealized_pct * 100
                    position.exit_reason = exit_reason
                    
                    # Apply costs
                    commission = position.size_usd * self.config.commission_rate * 2  # entry + exit
                    slippage_cost = position.size_usd * self.config.slippage * 2
                    position.pnl -= (commission + slippage_cost)
                    
                    capital += position.pnl
                    self.trades.append(position)
                    position = None
            
            # Check for position entry
            if position is None and capital > 0:
                # Calculate position size based on risk
                atr = row['atr']
                stop_distance = self.config.stop_atr_mult * atr
                risk_amount = capital * self.config.risk_per_trade
                
                if stop_distance > 0:
                    position_size = risk_amount / (stop_distance / row['close'])
                    position_size = min(position_size, capital * self.config.leverage)
                else:
                    position_size = capital * 0.1
                
                # Enter long
                if row['long_signal']:
                    position = Trade(
                        entry_time=timestamp,
                        direction='long',
                        entry_price=row['close'],
                        size_usd=position_size
                    )
                    # Deduct entry commission
                    capital -= position_size * self.config.commission_rate
                
                # Enter short
                elif row['short_signal']:
                    position = Trade(
                        entry_time=timestamp,
                        direction='short',
                        entry_price=row['close'],
                        size_usd=position_size
                    )
                    # Deduct entry commission
                    capital -= position_size * self.config.commission_rate
            
            # Record equity
            current_equity = capital
            if position is not None:
                if position.direction == 'long':
                    unrealized = position.size_usd * (row['close'] - position.entry_price) / position.entry_price
                else:
                    unrealized = position.size_usd * (position.entry_price - row['close']) / position.entry_price
                current_equity += unrealized
            
            self.equity_curve.append((timestamp, current_equity))
        
        # Close any open position at the end
        if position is not None:
            final_price = df['close'].iloc[-1]
            position.exit_time = df['timestamp'].iloc[-1] if 'timestamp' in df.columns else pd.Timestamp.now()
            position.exit_price = final_price
            
            if position.direction == 'long':
                position.pnl = position.size_usd * (final_price - position.entry_price) / position.entry_price
            else:
                position.pnl = position.size_usd * (position.entry_price - final_price) / position.entry_price
            
            position.exit_reason = "end_of_data"
            capital += position.pnl
            self.trades.append(position)
        
        return self.calculate_metrics(capital)
    
    def calculate_metrics(self, final_capital: float) -> Dict:
        """Calculate performance metrics."""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'total_return_pct': 0.0,
                'max_drawdown_pct': 0.0,
                'sharpe_ratio': 0.0
            }
        
        trades_df = pd.DataFrame([{
            'pnl': t.pnl,
            'pnl_pct': t.pnl_pct,
            'direction': t.direction,
            'exit_reason': t.exit_reason
        } for t in self.trades])
        
        winning_trades = trades_df[trades_df['pnl'] > 0]
        losing_trades = trades_df[trades_df['pnl'] <= 0]
        
        total_trades = len(self.trades)
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        
        gross_profit = winning_trades['pnl'].sum() if len(winning_trades) > 0 else 0
        gross_loss = abs(losing_trades['pnl'].sum()) if len(losing_trades) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        total_return_pct = ((final_capital - self.config.initial_capital) / self.config.initial_capital) * 100
        
        # Calculate max drawdown
        equity_df = pd.DataFrame(self.equity_curve, columns=['timestamp', 'equity'])
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak']
        max_drawdown_pct = abs(equity_df['drawdown'].min()) * 100
        
        # Calculate Sharpe ratio (simplified)
        returns = equity_df['equity'].pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(365 * 24)  # Hourly data
        else:
            sharpe_ratio = 0.0
        
        return {
            'total_trades': total_trades,
            'win_rate': win_rate * 100,
            'profit_factor': profit_factor,
            'total_return_pct': total_return_pct,
            'max_drawdown_pct': max_drawdown_pct,
            'sharpe_ratio': sharpe_ratio,
            'avg_trade_return': trades_df['pnl_pct'].mean(),
            'avg_win': winning_trades['pnl_pct'].mean() if len(winning_trades) > 0 else 0,
            'avg_loss': losing_trades['pnl_pct'].mean() if len(losing_trades) > 0 else 0,
            'final_capital': final_capital,
            'initial_capital': self.config.initial_capital
        }


def generate_synthetic_data(days: int = 365, volatility: float = 0.03) -> pd.DataFrame:
    """Generate synthetic SOL price data for backtesting."""
    np.random.seed(42)
    hours = days * 24
    
    # Generate price with trend and mean reversion
    returns = np.random.normal(0.0002, volatility, hours)
    
    # Add mean reversion component
    price = 100.0
    prices = [price]
    
    for ret in returns:
        price *= (1 + ret)
        prices.append(price)
    
    # Generate OHLC
    df = pd.DataFrame({
        'timestamp': pd.date_range(end=pd.Timestamp.now(), periods=hours, freq='h'),
        'close': prices[1:]
    })
    
    df['open'] = df['close'].shift(1).fillna(df['close'])
    df['high'] = df[['open', 'close']].max(axis=1) * (1 + np.random.uniform(0, 0.005, hours))
    df['low'] = df[['open', 'close']].min(axis=1) * (1 - np.random.uniform(0, 0.005, hours))
    df['volume'] = np.random.uniform(100000, 1000000, hours)
    
    return df


def main():
    import os
    print("=" * 70)
    print("SOL RSI MEAN REVERSION STRATEGY BACKTEST")
    print("=" * 70)
    print()
    
    # Load real data if available, otherwise use synthetic
    data_path = 'alpha-strategies/strategies/sol-rsi-mean-reversion/data/sol_usdt_1h_2024_2026.csv'
    if os.path.exists(data_path):
        print(f"Loading real SOL data from {data_path}...")
        df = pd.read_csv(data_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    else:
        print("Real data not found. Generating 1 year of synthetic SOL price data...")
        df = generate_synthetic_data(days=365)
        
    print(f"Data range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    print()
    
    # Run backtest
    print("Running backtest...")
    strategy = SOLRSIMeanReversion()
    results = strategy.run_backtest(df)
    
    # Display results
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    print(f"\nInitial Capital:       ${results['initial_capital']:,.2f}")
    print(f"Final Capital:         ${results['final_capital']:,.2f}")
    print(f"Total Return:          {results['total_return_pct']:+.2f}%")
    print()
    print(f"Total Trades:          {results['total_trades']}")
    print(f"Win Rate:              {results['win_rate']:.1f}%")
    print(f"Profit Factor:         {results['profit_factor']:.2f}")
    print()
    print(f"Avg Trade Return:      {results['avg_trade_return']:+.2f}%")
    print(f"Avg Win:               {results['avg_win']:+.2f}%")
    print(f"Avg Loss:              {results['avg_loss']:+.2f}%")
    print()
    print(f"Max Drawdown:          {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:          {results['sharpe_ratio']:.2f}")
    print()
    
    # Save results
    output_dir = 'alpha-strategies/results/sol-rsi-mean-reversion'
    os.makedirs(output_dir, exist_ok=True)
    with open(f'{output_dir}/results_real_data.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"Results saved to {output_dir}/results_real_data.json")
    
    return results


if __name__ == "__main__":
    main()
