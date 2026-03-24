"""
Backtesting Engine for VRP Harvester Strategy

Event-driven backtester that simulates:
- Option premium collection and theta decay
- Delta hedging with transaction costs
- IV changes and VRP capture
- Risk management and position limits

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy import VRPHarvesterStrategy, StraddlePosition, Signal
from src.indicators import VolatilityCalculator, GreeksCalculator
from src.signal_generator import SignalGenerator, SignalResult
from src.risk_manager import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Record of a backtest trade"""
    entry_date: datetime
    exit_date: Optional[datetime]
    asset: str
    strike: float
    entry_premium: float
    exit_premium: Optional[float]
    entry_iv: float
    exit_iv: Optional[float]
    entry_underlying: float
    exit_underlying: Optional[float]
    days_held: int
    pnl: float
    hedge_pnl: float
    total_pnl: float
    exit_reason: Optional[str]
    num_hedge_rebalances: int


class BacktestEngine:
    """
    Event-driven backtesting engine for VRP Harvester strategy
    """
    
    def __init__(self, config: Dict, strategy_config: Dict):
        """
        Initialize backtest engine
        
        Args:
            config: Backtest configuration
            strategy_config: Strategy configuration
        """
        self.config = config
        self.strategy_config = strategy_config
        
        # Extract parameters
        self.initial_capital = config.get('initial_capital', 100000)
        self.commission_rate = config.get('commission_rate', 0.001)
        self.slippage = config.get('slippage', 0.001)
        self.hedge_cost = config.get('hedge_cost', 0.0005)
        
        # State
        self.current_capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.positions: List[Dict] = []
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        
        # Initialize components
        self.strategy = VRPHarvesterStrategy(strategy_config)
        self.signal_generator = SignalGenerator(strategy_config)
        self.risk_manager = RiskManager(strategy_config.get('risk', {}))
        self.greeks_calc = GreeksCalculator()
        
        logger.info("Backtest Engine initialized")
        logger.info(f"Initial Capital: ${self.initial_capital:,.0f}")
    
    def run(self, data: Dict[str, pd.DataFrame]) -> Dict:
        """
        Run backtest on historical data
        
        Args:
            data: Dictionary of DataFrames with OHLCV + IV data for each asset
                  Each DataFrame should have columns:
                  ['open', 'high', 'low', 'close', 'volume', 'iv', 'rv']
                  
        Returns:
            Dictionary with backtest results
        """
        logger.info("Starting backtest...")
        
        # Align data to common timeline
        all_dates = self._align_dates(data)
        logger.info(f"Backtest period: {all_dates[0]} to {all_dates[-1]}")
        logger.info(f"Total bars: {len(all_dates)}")
        
        # Run simulation
        for i, date in enumerate(all_dates):
            if i % 100 == 0:
                logger.info(f"Processing {date}... ({i}/{len(all_dates)})")
            
            # Update equity curve
            self.equity_curve.append((date, self.current_capital))
            
            # Update existing positions
            self._update_positions(date, data)
            
            # Check for exits
            self._check_exits(date, data)
            
            # Check for new entries (weekly rebalancing)
            if i % 7 == 0:  # Weekly
                entries = self._check_entries(date, data)
                if entries > 0:
                    logger.info(f"  Entered {entries} new positions")
            
            # Update risk manager
            self.risk_manager.check_drawdown(self.current_capital)
        
        # Close any remaining positions at end
        self._close_all_positions(all_dates[-1], data)
        
        # Generate results
        results = self._generate_results()
        
        logger.info("Backtest complete!")
        logger.info(f"Final Capital: ${self.current_capital:,.0f}")
        logger.info(f"Total Return: {results['total_return']:.2%}")
        logger.info(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        
        return results
    
    def _align_dates(self, data: Dict[str, pd.DataFrame]) -> List[datetime]:
        """Align all data to common date range"""
        all_dates = set()
        for asset, df in data.items():
            all_dates.update(df.index)
        return sorted(list(all_dates))
    
    def _update_positions(self, date: datetime, data: Dict[str, pd.DataFrame]):
        """Update position Greeks and values"""
        for pos in self.positions:
            asset = pos['asset']
            if asset not in data or date not in data[asset].index:
                continue
            
            row = data[asset].loc[date]
            
            # Update position tracking
            pos['current_price'] = row['close']
            pos['current_iv'] = row['iv']
            pos['days_held'] += 1
            
            # Calculate current Greeks
            T = max(0, (pos['expiration'] - date).days / 365)
            if T > 0:
                greeks = self.greeks_calc.calculate_straddle_greeks(
                    S=row['close'],
                    K=pos['strike'],
                    T=T,
                    sigma=row['iv'],
                    quantity=pos['quantity']
                )
                pos['delta'] = greeks['delta']
                pos['gamma'] = greeks['gamma']
                pos['theta'] = greeks['theta']
                pos['vega'] = greeks['vega']
    
    def _check_exits(self, date: datetime, data: Dict[str, pd.DataFrame]):
        """Check and execute exits"""
        positions_to_close = []
        
        for pos in self.positions:
            if pos['status'] != 'OPEN':
                continue
            
            asset = pos['asset']
            if asset not in data or date not in data[asset].index:
                continue
            
            row = data[asset].loc[date]
            
            # Check exit conditions
            current_premium = self._estimate_straddle_value(pos, row)
            pnl_pct = (pos['entry_premium'] - current_premium) / pos['entry_premium']
            dte = max(0, (pos['expiration'] - date).days)
            
            exit_reason = None
            
            # Profit target
            if pnl_pct >= self.strategy_config.get('profit_target', 0.50):
                exit_reason = "PROFIT_TARGET"
            # Stop loss
            elif pnl_pct <= -self.strategy_config.get('stop_loss', 2.00):
                exit_reason = "STOP_LOSS"
            # Time stop
            elif dte <= self.strategy_config.get('time_stop_dte', 5):
                exit_reason = "TIME_STOP"
            # IV collapse
            elif row['iv'] < pos['entry_iv'] * 0.7 and pnl_pct > 0.25:
                exit_reason = "IV_COLLAPSE"
            
            if exit_reason:
                positions_to_close.append((pos, exit_reason, current_premium, row))
        
        # Execute exits
        for pos, reason, premium, row in positions_to_close:
            self._close_position(pos, date, reason, premium, row)
    
    def _check_entries(self, date: datetime, data: Dict[str, pd.DataFrame]):
        """Check and execute new entries"""
        entries_found = 0
        for asset, df in data.items():
            if date not in df.index:
                continue
            
            row = df.loc[date]
            
            # Skip if risk limits
            can_trade, reason = self.risk_manager.can_enter_position(
                self.current_capital,
                len(self.positions),
                {},
                row.get('dvol', 50)
            )
            if not can_trade:
                continue
            
            # Build history for calculations
            hist_start = max(0, df.index.get_loc(date) - 252)
            hist_end = df.index.get_loc(date)
            
            if hist_end - hist_start < 30:
                continue
            
            iv_history = df['iv'].iloc[hist_start:hist_end]
            rv_history = df['rv'].iloc[hist_start:hist_end]
            price_history = df[['open', 'high', 'low', 'close']].iloc[hist_start:hist_end]
            
            # Check entry signal
            signal = self.signal_generator.generate_entry_signal(
                asset=asset,
                current_price=row['close'],
                current_iv=row['iv'],
                iv_history=iv_history,
                rv_history=rv_history,
                price_history=price_history,
                available_margin=self.current_capital * 0.5,
                open_positions=len(self.positions)
            )
            
            if signal.signal_type == 'ENTER':
                self._enter_position(asset, date, row, signal.metadata)
                entries_found += 1
        
        return entries_found
    
    def _enter_position(self, asset: str, date: datetime, row: pd.Series, metadata: Dict):
        """Enter a new straddle position"""
        # Calculate position size
        entry_premium = row['close'] * row['iv'] * 0.15  # Approximate ATM straddle price
        quantity = self.risk_manager.calculate_position_size(
            self.current_capital, entry_premium
        )
        
        if quantity <= 0:
            return
        
        # Set expiration (30 days)
        expiration = date + timedelta(days=30)
        
        # Create position
        position = {
            'asset': asset,
            'entry_date': date,
            'expiration': expiration,
            'strike': row['close'],  # ATM
            'quantity': quantity,
            'entry_premium': entry_premium * quantity,
            'entry_iv': row['iv'],
            'entry_price': row['close'],
            'current_price': row['close'],
            'current_iv': row['iv'],
            'delta': 0,
            'gamma': 0,
            'theta': 0,
            'vega': 0,
            'days_held': 0,
            'hedge_size': 0,
            'hedge_entry_price': row['close'],
            'hedge_rebalances': 0,
            'status': 'OPEN'
        }
        
        # Calculate initial Greeks
        greeks = self.greeks_calc.calculate_straddle_greeks(
            S=row['close'],
            K=row['close'],
            T=30/365,
            sigma=row['iv'],
            quantity=quantity
        )
        position['delta'] = greeks['delta']
        position['gamma'] = greeks['gamma']
        position['theta'] = greeks['theta']
        position['vega'] = greeks['vega']
        
        # Set initial hedge
        position['hedge_size'] = -greeks['delta']
        
        # Deduct commission
        commission = entry_premium * quantity * self.commission_rate
        self.current_capital -= commission
        
        self.positions.append(position)
        logger.info(f"ENTER: {asset} at {date}, Premium=${entry_premium*quantity:.2f}")
    
    def _close_position(self, pos: Dict, date: datetime, reason: str, 
                       exit_premium: float, row: pd.Series):
        """Close a position"""
        # Calculate P&L
        premium_pnl = (pos['entry_premium'] - exit_premium * pos['quantity'])
        
        # Calculate hedge P&L
        hedge_pnl = pos['hedge_size'] * (row['close'] - pos['hedge_entry_price'])
        
        total_pnl = premium_pnl + hedge_pnl
        
        # Deduct commissions
        commission = exit_premium * pos['quantity'] * self.commission_rate
        total_pnl -= commission
        
        # Update capital
        self.current_capital += total_pnl
        
        # Record trade
        trade = BacktestTrade(
            entry_date=pos['entry_date'],
            exit_date=date,
            asset=pos['asset'],
            strike=pos['strike'],
            entry_premium=pos['entry_premium'],
            exit_premium=exit_premium * pos['quantity'],
            entry_iv=pos['entry_iv'],
            exit_iv=row['iv'],
            entry_underlying=pos['entry_price'],
            exit_underlying=row['close'],
            days_held=pos['days_held'],
            pnl=premium_pnl,
            hedge_pnl=hedge_pnl,
            total_pnl=total_pnl,
            exit_reason=reason,
            num_hedge_rebalances=pos['hedge_rebalances']
        )
        self.trades.append(trade)
        
        # Update risk manager
        self.risk_manager.record_trade({
            'pnl': total_pnl,
            'asset': pos['asset'],
            'exit_reason': reason
        })
        
        # Mark position closed
        pos['status'] = 'CLOSED'
        
        logger.info(f"EXIT: {pos['asset']} at {date}, PnL=${total_pnl:.2f}, Reason={reason}")
    
    def _close_all_positions(self, date: datetime, data: Dict[str, pd.DataFrame]):
        """Close all remaining positions at end of backtest"""
        for pos in self.positions:
            if pos['status'] == 'OPEN':
                asset = pos['asset']
                if asset in data and date in data[asset].index:
                    row = data[asset].loc[date]
                    exit_premium = self._estimate_straddle_value(pos, row)
                    self._close_position(pos, date, "BACKTEST_END", exit_premium, row)
    
    def _estimate_straddle_value(self, pos: Dict, row: pd.Series) -> float:
        """Estimate current straddle value"""
        T = max(0.001, (pos['expiration'] - pd.Timestamp(row.name)).days / 365)
        
        # Use Black-Scholes
        greeks = self.greeks_calc.calculate_straddle_greeks(
            S=row['close'],
            K=pos['strike'],
            T=T,
            sigma=row['iv'],
            quantity=1
        )
        
        return greeks['call_premium'] + greeks['put_premium']
    
    def _generate_results(self) -> Dict:
        """Generate comprehensive backtest results"""
        if not self.trades:
            return {
                'total_return': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0,
                'win_rate': 0,
                'num_trades': 0
            }
        
        # Basic stats
        total_pnl = sum(t.total_pnl for t in self.trades)
        total_return = total_pnl / self.initial_capital
        
        # Win rate
        wins = sum(1 for t in self.trades if t.total_pnl > 0)
        win_rate = wins / len(self.trades)
        
        # Profit factor
        gross_profit = sum(t.total_pnl for t in self.trades if t.total_pnl > 0)
        gross_loss = abs(sum(t.total_pnl for t in self.trades if t.total_pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 1.0
        
        # Average trade stats
        avg_trade = np.mean([t.total_pnl for t in self.trades])
        avg_win = np.mean([t.total_pnl for t in self.trades if t.total_pnl > 0]) if wins > 0 else 0
        avg_loss = np.mean([t.total_pnl for t in self.trades if t.total_pnl < 0]) if wins < len(self.trades) else 0
        
        # Calculate equity curve metrics
        equity_values = [e[1] for e in self.equity_curve]
        returns = pd.Series(equity_values).pct_change().dropna()
        
        # Sharpe ratio (annualized)
        if len(returns) > 1 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(365)
        else:
            sharpe = 0
        
        # Max drawdown
        peak = self.initial_capital
        max_dd = 0
        for eq in equity_values:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
        
        # Exit analysis
        exit_reasons = defaultdict(lambda: {'count': 0, 'pnl': 0})
        for t in self.trades:
            exit_reasons[t.exit_reason]['count'] += 1
            exit_reasons[t.exit_reason]['pnl'] += t.total_pnl
        
        return {
            'initial_capital': self.initial_capital,
            'final_capital': self.current_capital,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'num_trades': len(self.trades),
            'winning_trades': wins,
            'losing_trades': len(self.trades) - wins,
            'avg_trade_pnl': avg_trade,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'exit_analysis': dict(exit_reasons),
            'equity_curve': self.equity_curve,
            'trades': self.trades
        }
