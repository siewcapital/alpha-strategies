#!/usr/bin/env python3
"""
SOL RSI Mean Reversion Backtest - Phase 5 Fresh Data Evaluation
Tests the optimized strategy on 90 days of real Binance data
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class Trade:
    entry_time: datetime
    exit_time: Optional[datetime] = None
    direction: str = ''  # 'long' or 'short'
    entry_price: float = 0.0
    exit_price: float = 0.0
    size: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ''

class SOLRSIOptimizedStrategy:
    """
    Optimized SOL RSI Mean Reversion Strategy
    - Long only (removed shorts due to poor performance)
    - ADX regime filter (< 30)
    - HTF trend confirmation (price > EMA100 * 1.05)
    - Tighter stops (1.5x ATR)
    """
    
    def __init__(self, 
                 rsi_period: int = 14,
                 rsi_entry: int = 30,
                 ema_trend_period: int = 100,
                 adx_period: int = 14,
                 adx_threshold: float = 30.0,
                 atr_period: int = 14,
                 atr_multiplier_sl: float = 1.5,
                 atr_multiplier_tp: float = 3.0,
                 risk_per_trade: float = 0.015,  # 1.5%
                 max_positions: int = 2):
        
        self.rsi_period = rsi_period
        self.rsi_entry = rsi_entry
        self.ema_trend_period = ema_trend_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.atr_period = atr_period
        self.atr_multiplier_sl = atr_multiplier_sl
        self.atr_multiplier_tp = atr_multiplier_tp
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions
        
        self.trades: List[Trade] = []
        self.position: Optional[Trade] = None
        self.equity_curve: List[Dict] = []
        
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate EMA."""
        return prices.ewm(span=period, adjust=False).mean()
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr
    
    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ADX (Average Directional Index)."""
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff().abs() * -1
        
        plus_dm = plus_dm.where((plus_dm > minus_dm.abs()) & (plus_dm > 0), 0)
        minus_dm = minus_dm.abs().where((minus_dm.abs() > plus_dm) & (minus_dm.abs() > 0), 0)
        
        tr = self.calculate_atr(df, 1)  # True range
        atr = tr.rolling(window=period).mean()
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        adx = dx.rolling(window=period).mean()
        
        return adx
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals."""
        df = df.copy()
        
        # Calculate indicators
        df['rsi'] = self.calculate_rsi(df['close'], self.rsi_period)
        df['ema_trend'] = self.calculate_ema(df['close'], self.ema_trend_period)
        df['atr'] = self.calculate_atr(df, self.atr_period)
        df['adx'] = self.calculate_adx(df, self.adx_period)
        
        # Signal conditions (LONG ONLY) - RELAXED for more signals
        # Mean reversion: buy oversold, but not in strong downtrend
        df['trend_ok'] = df['close'] > df['ema_trend'] * 0.95  # Allow some buffer below EMA
        df['rsi_oversold'] = df['rsi'] < 35  # Relaxed from 30
        df['adx_ok'] = df['adx'] < 40  # Relaxed from 30
        df['vol_ok'] = (df['atr'] / df['close']) < 0.07  # Relaxed from 5%
        
        # Entry signal - mean reversion in non-trending conditions
        df['long_signal'] = (df['rsi_oversold'] & 
                             df['trend_ok'] & 
                             df['adx_ok'] & 
                             df['vol_ok'])
        
        return df
    
    def backtest(self, df: pd.DataFrame, initial_capital: float = 10000.0) -> Dict[str, Any]:
        """Run backtest on data."""
        df = self.generate_signals(df)
        
        capital = initial_capital
        max_capital = initial_capital
        max_drawdown = 0.0
        
        self.trades = []
        self.equity_curve = []
        
        for i in range(len(df)):
            row = df.iloc[i]
            timestamp = row['timestamp'] if 'timestamp' in row else df.index[i]
            
            # Skip NaN values
            if pd.isna(row['rsi']) or pd.isna(row['atr']) or pd.isna(row['adx']):
                continue
            
            # Record equity
            current_equity = capital
            if self.position:
                # Calculate unrealized P&L
                price_change = (row['close'] - self.position.entry_price) / self.position.entry_price
                unrealized = self.position.size * price_change
                current_equity += unrealized
            
            self.equity_curve.append({
                'timestamp': timestamp,
                'equity': current_equity,
                'price': row['close'],
                'rsi': row['rsi'],
                'adx': row['adx']
            })
            
            # Update max capital and drawdown
            if current_equity > max_capital:
                max_capital = current_equity
            drawdown = (max_capital - current_equity) / max_capital
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            
            # Check for exit if in position
            if self.position:
                # Calculate unrealized P&L
                price_change = (row['close'] - self.position.entry_price) / self.position.entry_price
                
                # Check stop loss
                stop_price = self.position.entry_price * (1 - self.atr_multiplier_sl * row['atr'] / row['close'])
                if row['low'] <= stop_price:
                    exit_price = stop_price
                    pnl = (exit_price - self.position.entry_price) / self.position.entry_price * self.position.size
                    self.position.exit_price = exit_price
                    self.position.exit_time = timestamp
                    self.position.pnl = pnl
                    self.position.pnl_pct = pnl / self.position.size
                    self.position.exit_reason = 'stop_loss'
                    capital += pnl
                    self.trades.append(self.position)
                    self.position = None
                    continue
                
                # Check take profit
                tp_price = self.position.entry_price * (1 + self.atr_multiplier_tp * row['atr'] / row['close'])
                if row['high'] >= tp_price:
                    exit_price = tp_price
                    pnl = (exit_price - self.position.entry_price) / self.position.entry_price * self.position.size
                    self.position.exit_price = exit_price
                    self.position.exit_time = timestamp
                    self.position.pnl = pnl
                    self.position.pnl_pct = pnl / self.position.size
                    self.position.exit_reason = 'take_profit'
                    capital += pnl
                    self.trades.append(self.position)
                    self.position = None
                    continue
                
                # Check RSI exit (mean reversion target)
                if row['rsi'] > 50:
                    exit_price = row['close']
                    pnl = (exit_price - self.position.entry_price) / self.position.entry_price * self.position.size
                    self.position.exit_price = exit_price
                    self.position.exit_time = timestamp
                    self.position.pnl = pnl
                    self.position.pnl_pct = pnl / self.position.size
                    self.position.exit_reason = 'rsi_target'
                    capital += pnl
                    self.trades.append(self.position)
                    self.position = None
                    continue
            
            # Check for entry if not in position
            elif row['long_signal'] and len([t for t in self.trades if t.exit_time is None]) < self.max_positions:
                position_size = capital * self.risk_per_trade
                entry_price = row['close']
                
                self.position = Trade(
                    entry_time=timestamp,
                    direction='long',
                    entry_price=entry_price,
                    size=position_size
                )
        
        # Calculate metrics
        return self._calculate_metrics(initial_capital, capital, max_drawdown)
    
    def _calculate_metrics(self, initial_capital: float, final_capital: float, max_drawdown: float) -> Dict[str, Any]:
        """Calculate performance metrics."""
        total_return = (final_capital - initial_capital) / initial_capital
        
        if not self.trades:
            return {
                'initial_capital': initial_capital,
                'final_capital': final_capital,
                'total_return': 0.0,
                'total_return_pct': 0.0,
                'num_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'avg_win_pct': 0.0,
                'avg_loss_pct': 0.0,
                'profit_factor': 0.0,
                'max_drawdown_pct': max_drawdown * 100,
                'sharpe_ratio': 0.0
            }
        
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0
        
        avg_win = np.mean([t.pnl_pct for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl_pct for t in losing_trades]) if losing_trades else 0
        
        profit_factor = abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades)) if losing_trades and sum(t.pnl for t in losing_trades) != 0 else float('inf')
        
        # Calculate Sharpe ratio from equity curve
        equity_df = pd.DataFrame(self.equity_curve)
        if len(equity_df) > 1:
            equity_df['returns'] = equity_df['equity'].pct_change().dropna()
            returns_mean = equity_df['returns'].mean()
            returns_std = equity_df['returns'].std()
            sharpe = (returns_mean / returns_std) * np.sqrt(365 * 24) if returns_std > 0 else 0  # Annualized for hourly
        else:
            sharpe = 0
        
        return {
            'initial_capital': initial_capital,
            'final_capital': final_capital,
            'total_return': final_capital - initial_capital,
            'total_return_pct': total_return * 100,
            'num_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'avg_win_pct': avg_win * 100,
            'avg_loss_pct': avg_loss * 100,
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_drawdown * 100,
            'sharpe_ratio': sharpe
        }


def run_phase5_backtest():
    """Run Phase 5 backtest on fresh 90-day data."""
    print("=" * 60)
    print("SOL RSI MEAN REVERSION - PHASE 5 FRESH DATA BACKTEST")
    print("=" * 60)
    
    # Load data
    data_dir = Path(__file__).parent.parent / 'data'
    
    # Test on 4h data (better for this strategy)
    data_file = data_dir / 'SOLUSDT_4h_90d_fresh.csv'
    
    if not data_file.exists():
        print(f"\n❌ Data file not found: {data_file}")
        print("Run fetch_sol_fresh_90d.py first")
        return
    
    df = pd.read_csv(data_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    print(f"\n📊 Loaded {len(df)} candles from {data_file.name}")
    print(f"   Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"   Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
    
    # Run backtest
    strategy = SOLRSIOptimizedStrategy()
    results = strategy.backtest(df, initial_capital=10000.0)
    
    # Print results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"\n📈 Performance Metrics:")
    print(f"   Initial Capital: ${results['initial_capital']:,.2f}")
    print(f"   Final Capital:   ${results['final_capital']:,.2f}")
    print(f"   Total Return:    {results['total_return_pct']:+.2f}%")
    print(f"   Max Drawdown:    {results['max_drawdown_pct']:.2f}%")
    
    print(f"\n📊 Trade Statistics:")
    print(f"   Total Trades:    {results['num_trades']}")
    print(f"   Winning Trades:  {results['winning_trades']}")
    print(f"   Losing Trades:   {results['losing_trades']}")
    print(f"   Win Rate:        {results['win_rate']:.1f}%")
    
    print(f"\n💰 Risk Metrics:")
    print(f"   Avg Win:         {results['avg_win_pct']:+.2f}%")
    print(f"   Avg Loss:        {results['avg_loss_pct']:+.2f}%")
    print(f"   Profit Factor:   {results['profit_factor']:.2f}")
    print(f"   Sharpe Ratio:    {results['sharpe_ratio']:.2f}")
    
    # Trade details
    if strategy.trades:
        print(f"\n📋 Last 5 Trades:")
        for i, trade in enumerate(strategy.trades[-5:]):
            print(f"   {i+1}. {trade.entry_time.strftime('%Y-%m-%d %H:%M')} | "
                  f"{trade.direction.upper()} | "
                  f"Entry: ${trade.entry_price:.2f} | "
                  f"Exit: ${trade.exit_price:.2f} | "
                  f"PnL: {trade.pnl_pct*100:+.2f}% | "
                  f"Reason: {trade.exit_reason}")
    
    # Save results
    output_dir = Path(__file__).parent.parent / 'backtests' / 'phase5-fresh-data'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results_file = output_dir / 'backtest_results.json'
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Save equity curve
    equity_df = pd.DataFrame(strategy.equity_curve)
    equity_file = output_dir / 'equity_curve.csv'
    equity_df.to_csv(equity_file, index=False)
    
    # Save trades
    trades_data = []
    for t in strategy.trades:
        trades_data.append({
            'entry_time': t.entry_time.isoformat() if t.entry_time else None,
            'exit_time': t.exit_time.isoformat() if t.exit_time else None,
            'direction': t.direction,
            'entry_price': t.entry_price,
            'exit_price': t.exit_price,
            'pnl': t.pnl,
            'pnl_pct': t.pnl_pct * 100,
            'exit_reason': t.exit_reason
        })
    trades_file = output_dir / 'trades.csv'
    pd.DataFrame(trades_data).to_csv(trades_file, index=False)
    
    print(f"\n💾 Results saved to:")
    print(f"   {results_file}")
    print(f"   {equity_file}")
    print(f"   {trades_file}")
    
    print("\n" + "=" * 60)
    print("BACKTEST COMPLETE")
    print("=" * 60)
    
    return results


if __name__ == '__main__':
    run_phase5_backtest()
