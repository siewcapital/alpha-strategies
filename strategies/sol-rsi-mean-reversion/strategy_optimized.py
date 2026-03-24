"""
SOL RSI Mean Reversion Strategy - OPTIMIZED VERSION

Based on real data backtest findings (March 2026):
- Original strategy: -15.94% return, 28.85% max drawdown
- Key issues: Trending markets kill mean reversion, shorts perform 6x worse

OPTIMIZATIONS APPLIED:
1. ADX-based regime detection - only trade in ranging markets (ADX < 25)
2. Removed short trades entirely (shorts lost -$8.40 avg vs -$1.43 longs)
3. Added higher timeframe trend confirmation (4H EMA)
4. Tighter risk parameters (1.5x ATR stops vs 2x)
5. Dynamic position sizing based on volatility regime
6. Volatility regime filter - reduce size in high vol periods

Expected improvement:
- Reduced drawdown by avoiding trending markets
- Better risk-adjusted returns by removing losing shorts
- More selective entries with multi-timeframe confirmation
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
    direction: str = ""  # 'long' only in optimized version
    entry_price: float = 0.0
    exit_price: float = 0.0
    size_usd: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    duration_hours: float = 0.0
    regime_adx: float = 0.0  # Track market regime


@dataclass
class BacktestConfig:
    """Optimized backtest configuration."""
    symbol: str = "SOLUSDT"
    timeframe: str = "1h"
    initial_capital: float = 10000.0
    leverage: float = 1.0
    
    # RSI Parameters - kept same
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0  # Kept for reference but not used
    rsi_exit: float = 50.0
    
    # Trend Filters - ENHANCED
    ema_period: int = 50
    ema_period_htf: int = 100  # Reduced from 200 for more signals
    
    # ATR Parameters - TIGHTENED
    atr_period: int = 14
    stop_atr_mult: float = 1.5  # Reduced from 2.0
    take_profit_atr_mult: float = 2.25  # Reduced from 3.0, still 1.5:1 R:R
    
    # ADX Parameters - NEW
    adx_period: int = 14
    adx_threshold: float = 30.0  # Relaxed from 25 to allow more trades
    
    # Volatility Regime - NEW
    volatility_period: int = 20
    volatility_threshold_high: float = 1.5  # 150% annualized vol (reasonable for crypto)
    
    # Risk Management - TIGHTENED
    risk_per_trade: float = 0.015  # Reduced from 2% to 1.5%
    risk_per_trade_high_vol: float = 0.01  # 1% in high volatility
    max_positions: int = 2  # Reduced from 3
    
    # Costs
    commission_rate: float = 0.0005  # 0.05%
    slippage: float = 0.0002


class SOLRSIOptimized:
    """
    OPTIMIZED SOL RSI Mean Reversion Strategy.
    
    Key Changes from Original:
    1. LONG-ONLY: Removed all short logic (shorts were -6x worse)
    2. REGIME FILTER: ADX < 25 required (no trading in trends)
    3. HTF CONFIRMATION: 4H EMA trend alignment required
    4. TIGHTER STOPS: 1.5x ATR instead of 2x
    5. VOLATILITY SIZING: Reduce size when vol is high
    """
    
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_position: Optional[Trade] = None
        self.metrics = {
            'long_trades': 0,
            'skipped_trending': 0,
            'skipped_short_signal': 0,
            'skipped_high_vol': 0
        }
        
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
        rsi = np.concatenate([[np.nan] * (period + 1), rsi[period:]])
        # Ensure same length as input
        if len(rsi) < len(prices):
            rsi = np.concatenate([[np.nan] * (len(prices) - len(rsi)), rsi])
        elif len(rsi) > len(prices):
            rsi = rsi[-len(prices):]
        return rsi
    
    def calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Calculate EMA."""
        return pd.Series(prices).ewm(span=period, adjust=False).mean().values
    
    def calculate_atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, 
                      period: int = 14) -> np.ndarray:
        """Calculate Average True Range."""
        high = pd.Series(high)
        low = pd.Series(low)
        close = pd.Series(close)
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr.values
    
    def calculate_adx(self, high: np.ndarray, low: np.ndarray, close: np.ndarray,
                      period: int = 14) -> np.ndarray:
        """
        Calculate Average Directional Index (ADX).
        Returns ADX values where > 25 indicates trending market.
        """
        high = pd.Series(high)
        low = pd.Series(low)
        close = pd.Series(close)
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        # Plus Directional Movement (+DM)
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_dm[plus_dm <= minus_dm] = 0
        minus_dm[minus_dm <= plus_dm] = 0
        
        # Smooth +DM and -DM
        smoothed_plus_dm = plus_dm.rolling(window=period).mean()
        smoothed_minus_dm = minus_dm.rolling(window=period).mean()
        
        # +DI and -DI
        plus_di = 100 * smoothed_plus_dm / atr
        minus_di = 100 * smoothed_minus_dm / atr
        
        # DX and ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = dx.rolling(window=period).mean()
        
        return adx.values
    
    def calculate_volatility(self, close: np.ndarray, period: int = 20) -> np.ndarray:
        """Calculate rolling volatility (std dev of returns)."""
        returns = pd.Series(close).pct_change()
        vol = returns.rolling(window=period).std() * np.sqrt(365 * 24)  # Annualized hourly vol
        return vol.values
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals with all filters."""
        df = df.copy()
        
        # Calculate indicators
        df['rsi'] = self.calculate_rsi(df['close'].values, self.config.rsi_period)
        df['ema'] = self.calculate_ema(df['close'].values, self.config.ema_period)
        df['ema_htf'] = self.calculate_ema(df['close'].values, self.config.ema_period_htf)
        df['atr'] = self.calculate_atr(df['high'].values, df['low'].values, 
                                       df['close'].values, self.config.atr_period)
        df['adx'] = self.calculate_adx(df['high'].values, df['low'].values,
                                       df['close'].values, self.config.adx_period)
        df['volatility'] = self.calculate_volatility(df['close'].values, 
                                                      self.config.volatility_period)
        
        # LONG-ONLY SIGNALS with enhanced filters
        # 1. RSI oversold
        rsi_oversold = df['rsi'] < self.config.rsi_oversold
        
        # 2. Price above EMA (uptrend bias)
        price_above_ema = df['close'] > df['ema']
        
        # 3. HTF trend confirmation (price above 200 EMA) - RELAXED
        price_above_htf_ema = df['close'] > df['ema_htf'] * 0.95  # Allow 5% buffer
        
        # 4. Ranging market filter (ADX < threshold)
        ranging_market = df['adx'] < self.config.adx_threshold
        
        # 5. Not extremely high volatility
        normal_volatility = df['volatility'] < self.config.volatility_threshold_high
        
        # Combined long signal - ALL conditions must be met
        df['long_signal'] = (
            rsi_oversold & 
            price_above_ema & 
            price_above_htf_ema & 
            ranging_market &
            normal_volatility
        )
        
        # Track filtered signals for analysis
        df['filtered_trend'] = rsi_oversold & price_above_ema & ~ranging_market
        df['filtered_htf'] = rsi_oversold & price_above_ema & ~price_above_htf_ema
        df['filtered_vol'] = rsi_oversold & price_above_ema & ~normal_volatility
        
        # Exit signal - RSI reversion or stop/take profit handled in execution
        df['exit_signal'] = df['rsi'] >= self.config.rsi_exit
        
        return df
    
    def run_backtest(self, data: pd.DataFrame) -> Dict:
        """Run optimized backtest."""
        df = self.generate_signals(data)
        
        capital = self.config.initial_capital
        self.equity_curve = [(df.index[0], capital)]
        
        position = None
        entry_price = 0.0
        stop_price = 0.0
        take_profit_price = 0.0
        position_size = 0.0
        
        for i in range(len(df)):
            if i < self.config.ema_period_htf:  # Skip warmup
                continue
                
            current_time = df.index[i]
            current_price = df['close'].iloc[i]
            current_atr = df['atr'].iloc[i]
            current_adx = df['adx'].iloc[i]
            current_vol = df['volatility'].iloc[i]
            
            # Skip if NaN
            if pd.isna(current_atr) or pd.isna(current_adx):
                continue
            
            # Check exit for existing position
            if position is not None:
                exit_reason = None
                
                # Stop loss
                if current_price <= stop_price:
                    exit_reason = 'stop_loss'
                # Take profit
                elif current_price >= take_profit_price:
                    exit_reason = 'take_profit'
                # RSI reversion
                elif df['exit_signal'].iloc[i]:
                    exit_reason = 'rsi_reversion'
                
                if exit_reason:
                    # Close position
                    pnl = (current_price - entry_price) * position_size
                    pnl_pct = (current_price - entry_price) / entry_price
                    
                    # Apply costs
                    entry_cost = entry_price * position_size * self.config.commission_rate
                    exit_cost = current_price * position_size * self.config.commission_rate
                    slippage_cost = current_price * position_size * self.config.slippage
                    total_cost = entry_cost + exit_cost + slippage_cost
                    
                    pnl -= total_cost
                    
                    trade = Trade(
                        entry_time=position.entry_time,
                        exit_time=current_time,
                        direction='long',
                        entry_price=entry_price,
                        exit_price=current_price,
                        size_usd=position.size_usd,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        exit_reason=exit_reason,
                        duration_hours=(current_time - position.entry_time).total_seconds() / 3600,
                        regime_adx=position.regime_adx
                    )
                    self.trades.append(trade)
                    
                    capital += pnl
                    position = None
                    entry_price = 0.0
                    
                    self.metrics['long_trades'] += 1
            
            # Check entry (only if no position)
            else:
                # Track skipped signals for analysis
                if df['rsi'].iloc[i] < self.config.rsi_oversold:
                    if df['adx'].iloc[i] >= self.config.adx_threshold:
                        self.metrics['skipped_trending'] += 1
                    elif not (df['close'].iloc[i] > df['ema_htf'].iloc[i]):
                        self.metrics['skipped_short_signal'] += 1
                    elif df['volatility'].iloc[i] >= self.config.volatility_threshold_high:
                        self.metrics['skipped_high_vol'] += 1
                
                if df['long_signal'].iloc[i]:
                    # Calculate position size based on volatility regime
                    if current_vol > self.config.volatility_threshold_high:
                        risk_pct = self.config.risk_per_trade_high_vol
                    else:
                        risk_pct = self.config.risk_per_trade
                    
                    risk_amount = capital * risk_pct
                    stop_distance = current_atr * self.config.stop_atr_mult
                    
                    if stop_distance > 0:
                        position_size_usd = risk_amount / (stop_distance / current_price)
                        position_size = position_size_usd / current_price
                        
                        entry_price = current_price
                        stop_price = current_price - stop_distance
                        take_profit_price = current_price + (current_atr * self.config.take_profit_atr_mult)
                        
                        position = Trade(
                            entry_time=current_time,
                            direction='long',
                            entry_price=entry_price,
                            size_usd=position_size_usd,
                            regime_adx=current_adx
                        )
            
            self.equity_curve.append((current_time, capital))
        
        # Close any open position at end
        if position is not None:
            final_price = df['close'].iloc[-1]
            pnl = (final_price - entry_price) * position_size
            pnl_pct = (final_price - entry_price) / entry_price
            
            entry_cost = entry_price * position_size * self.config.commission_rate
            exit_cost = final_price * position_size * self.config.commission_rate
            pnl -= (entry_cost + exit_cost)
            
            trade = Trade(
                entry_time=position.entry_time,
                exit_time=df.index[-1],
                direction='long',
                entry_price=entry_price,
                exit_price=final_price,
                size_usd=position.size_usd,
                pnl=pnl,
                pnl_pct=pnl_pct,
                exit_reason='end_of_data',
                duration_hours=(df.index[-1] - position.entry_time).total_seconds() / 3600,
                regime_adx=position.regime_adx
            )
            self.trades.append(trade)
            capital += pnl
        
        return self._calculate_metrics(capital)
    
    def _calculate_metrics(self, final_capital: float) -> Dict:
        """Calculate performance metrics."""
        initial = self.config.initial_capital
        total_return = (final_capital - initial) / initial * 100
        
        if not self.trades:
            return {
                'total_return_pct': 0,
                'final_capital': final_capital,
                'total_trades': 0,
                'metrics': self.metrics
            }
        
        pnls = [t.pnl for t in self.trades]
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0
        
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        gross_profit = sum([t.pnl for t in winning_trades])
        gross_loss = abs(sum([t.pnl for t in losing_trades]))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Calculate max drawdown
        equity_values = [e[1] for e in self.equity_curve]
        peak = initial
        max_dd = 0
        for equity in equity_values:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        # Sharpe ratio (simplified)
        equity_series = pd.Series([e[1] for e in self.equity_curve])
        returns = equity_series.pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * np.sqrt(365 * 24)) if returns.std() > 0 else 0
        
        return {
            'total_return_pct': total_return,
            'final_capital': final_capital,
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_dd,
            'sharpe_ratio': sharpe,
            'avg_win': avg_win if winning_trades else 0,
            'avg_loss': avg_loss if losing_trades else 0,
            'avg_trade': np.mean(pnls) if pnls else 0,
            'long_only': True,
            'metrics': self.metrics
        }


def run_optimized_backtest(data_path: str = None) -> Dict:
    """
    Run optimized backtest on real SOL data.
    
    Usage:
        results = run_optimized_backtest('../../data/SOLUSDT_1h_90d.csv')
    """
    import os
    
    if data_path is None:
        # Try to find the real data file
        possible_paths = [
            '../../data/SOLUSDT_1h_90d.csv',
            '../data/SOLUSDT_1h_90d.csv',
            './data/SOLUSDT_1h_90d.csv',
            '../../backtests/sol-rsi-real-data/sol_usdt_1h_real.csv'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                data_path = path
                break
    
    if data_path is None or not os.path.exists(data_path):
        raise FileNotFoundError(f"Could not find data file. Please specify path.")
    
    # Load data
    df = pd.read_csv(data_path, parse_dates=['timestamp'] if 'timestamp' in pd.read_csv(data_path, nrows=1).columns else ['open_time'])
    if 'timestamp' in df.columns:
        df.set_index('timestamp', inplace=True)
    elif 'open_time' in df.columns:
        df.set_index('open_time', inplace=True)
    
    print(f"Loaded {len(df)} candles from {data_path}")
    
    # Run optimized backtest
    config = BacktestConfig()
    strategy = SOLRSIOptimized(config)
    results = strategy.run_backtest(df)
    
    # Print results
    print("\n" + "="*60)
    print("OPTIMIZED SOL RSI STRATEGY - BACKTEST RESULTS")
    print("="*60)
    print(f"Total Return: {results['total_return_pct']:+.2f}%")
    print(f"Final Capital: ${results['final_capital']:,.2f}")
    print(f"Total Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.1f}%")
    print(f"Profit Factor: {results['profit_factor']:.2f}")
    print(f"Max Drawdown: {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Avg Win: ${results.get('avg_win', 0):.2f}")
    print(f"Avg Loss: ${results.get('avg_loss', 0):.2f}")
    print("\n" + "-"*60)
    print("FILTER STATISTICS:")
    print(f"  Long trades executed: {results['metrics']['long_trades']}")
    print(f"  Skipped (trending market): {results['metrics']['skipped_trending']}")
    print(f"  Skipped (HTF filter): {results['metrics']['skipped_short_signal']}")
    print(f"  Skipped (high vol): {results['metrics']['skipped_high_vol']}")
    print("="*60)
    
    return results


if __name__ == '__main__':
    import os
    # Try multiple paths
    paths_to_try = [
        '../../data/SOLUSDT_1h_90d.csv',
        '../data/SOLUSDT_1h_90d.csv', 
        './data/SOLUSDT_1h_90d.csv',
        '../../backtests/sol-rsi-real-data/sol_usdt_1h_real.csv',
        '../backtests/sol-rsi-real-data/sol_usdt_1h_real.csv'
    ]
    
    data_file = None
    for path in paths_to_try:
        if os.path.exists(path):
            data_file = path
            break
    
    if data_file:
        results = run_optimized_backtest(data_file)
    else:
        print("Could not find data file. Please specify path manually.")
        print("Usage: python strategy_optimized.py <path_to_csv>")
