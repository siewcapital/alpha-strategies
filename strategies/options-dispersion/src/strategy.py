"""
Main Strategy Module for Options Dispersion Trading
Implements the core dispersion trading logic
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

from src.indicators import (
    CorrelationCalculator, 
    CorrelationMetrics,
    VolatilityIndicators,
    SignalGenerator
)
from src.risk_manager import (
    RiskManager,
    Position,
    Greeks,
    PositionStatus
)


@dataclass
class Trade:
    """Represents a completed trade"""
    entry_date: pd.Timestamp
    exit_date: Optional[pd.Timestamp]
    position_type: str  # 'long_dispersion', 'short_dispersion'
    entry_correlation: float
    exit_correlation: Optional[float]
    entry_zscore: float
    exit_zscore: Optional[float]
    pnl: float
    return_pct: float
    holding_days: int
    exit_reason: str


class DispersionStrategy:
    """
    Options Dispersion Trading Strategy
    
    Core strategy: Trade the difference between index implied volatility
    and the volatility implied by constituent options
    """
    
    def __init__(
        self,
        params: Dict,
        initial_capital: float = 1_000_000
    ):
        self.params = params
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        
        # Initialize components
        self.correlation_calc = CorrelationCalculator(
            lookback_window=params['signals']['correlation']['lookback_window']
        )
        
        self.signal_generator = SignalGenerator(
            z_score_threshold_long=params['signals']['correlation']['z_score_threshold_long'],
            z_score_threshold_exit=params['signals']['correlation']['z_score_threshold_exit'],
            z_score_threshold_short=params['signals']['correlation']['z_score_threshold_short'],
            vix_max=params['signals']['volatility']['vix_max'],
            vix_min=params['signals']['volatility']['vix_min'],
            max_atr_multiple=params['signals']['trend_filter']['max_atr_multiple']
        )
        
        self.risk_manager = RiskManager(
            portfolio_value=initial_capital,
            target_vega_exposure=params['position_sizing']['target_vega_exposure'],
            max_vega_exposure=params['position_sizing']['max_vega_exposure'],
            max_delta_exposure=params['risk_management']['delta_hedge']['threshold'],
            max_loss_per_trade=params['risk_management']['stop_loss']['max_loss_per_trade'],
            stop_correlation_move=params['risk_management']['stop_loss']['implied_correlation_move']
        )
        self.risk_manager.max_holding_days = params['risk_management']['time_stop']['max_hold_days']
        
        # State tracking
        self.current_position = PositionStatus.NO_POSITION
        self.active_trade: Optional[Trade] = None
        self.trade_history: List[Trade] = []
        self.daily_pnl: List[Dict] = []
        
        # Market data storage
        self.index_prices: pd.Series = pd.Series()
        self.constituent_prices: pd.DataFrame = pd.DataFrame()
        self.vix_series: pd.Series = pd.Series()
        
    def calculate_option_greeks(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        implied_vol: float,
        option_type: str,
        risk_free_rate: float = 0.05
    ) -> Greeks:
        """
        Calculate option Greeks using Black-Scholes
        
        This is a simplified calculation - real implementation would use
        more sophisticated models or market data
        """
        from scipy.stats import norm
        
        S = underlying_price
        K = strike
        T = time_to_expiry
        sigma = implied_vol
        r = risk_free_rate
        
        # Protect against divide by zero in greeks calculation
        if sigma <= 0 or T <= 0:
            return Greeks(delta=0.5 if option_type == 'call' else -0.5, gamma=0, theta=0, vega=0, rho=0)
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        if option_type == 'call':
            delta = norm.cdf(d1)
            theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) 
                     - r * K * np.exp(-r * T) * norm.cdf(d2))
        else:  # put
            delta = norm.cdf(d1) - 1
            theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) 
                     + r * K * np.exp(-r * T) * norm.cdf(-d2))
        
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        vega = S * norm.pdf(d1) * np.sqrt(T) / 100  # Per 1% change in vol
        rho = K * T * np.exp(-r * T) * norm.cdf(d2 if option_type == 'call' else -d2) / 100
        
        return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)
    
    def simulate_option_prices(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        implied_vol: float,
        option_type: str,
        risk_free_rate: float = 0.05
    ) -> float:
        """
        Simulate option price using Black-Scholes
        """
        from scipy.stats import norm
        
        S = underlying_price
        K = strike
        T = time_to_expiry
        sigma = implied_vol
        r = risk_free_rate
        
        # Protect against divide by zero
        if sigma <= 0 or T <= 0:
            return max(0, S - K) if option_type == 'call' else max(0, K - S)
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        if option_type == 'call':
            price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        
        return price
    
    def enter_position(
        self,
        timestamp: pd.Timestamp,
        signal_type: str,
        metrics: CorrelationMetrics,
        market_data: Dict
    ) -> bool:
        """
        Enter a new dispersion trade
        """
        # Check risk conditions
        can_enter, reason = self.risk_manager.check_entry_conditions(
            metrics.implied_correlation,
            metrics.correlation_zscore,
            market_data.get('vix', 20),
            self.risk_manager.positions
        )
        
        if not can_enter:
            return False
        
        # Determine position type
        if signal_type == 'ENTER_LONG':
            self.current_position = PositionStatus.LONG_DISPERSION
            position_type = 'long_dispersion'
            # Short index, long constituents
            index_quantity = -1
            constituent_quantity = 1
        else:  # ENTER_SHORT
            self.current_position = PositionStatus.SHORT_DISPERSION
            position_type = 'short_dispersion'
            # Long index, short constituents
            index_quantity = 1
            constituent_quantity = -1
        
        # Calculate position sizes
        position_sizes = self.risk_manager.calculate_position_size(
            index_vega=market_data['index_vega'],
            avg_constituent_vega=market_data['avg_constituent_vega'],
            signal_type=signal_type
        )
        
        # Create index positions (straddle)
        index_price = market_data['index_price']
        atm_strike = round(index_price / 10) * 10  # Round to nearest 10
        days_to_exp = self.params['options']['days_to_expiration']
        expiry = timestamp + pd.Timedelta(days=days_to_exp)
        
        # Short/Long index call
        call_greeks = self.calculate_option_greeks(
            index_price, atm_strike, days_to_exp/365,
            market_data['index_iv'], 'call'
        )
        call_price = self.simulate_option_prices(
            index_price, atm_strike, days_to_exp/365,
            market_data['index_iv'], 'call'
        )
        
        index_call = Position(
            underlying='INDEX',
            option_type='call',
            strike=atm_strike,
            expiration=expiry,
            quantity=position_sizes['index_contracts'] * index_quantity,
            entry_price=call_price,
            entry_date=timestamp,
            greeks=call_greeks
        )
        
        # Short/Long index put
        put_greeks = self.calculate_option_greeks(
            index_price, atm_strike, days_to_exp/365,
            market_data['index_iv'], 'put'
        )
        put_price = self.simulate_option_prices(
            index_price, atm_strike, days_to_exp/365,
            market_data['index_iv'], 'put'
        )
        
        index_put = Position(
            underlying='INDEX',
            option_type='put',
            strike=atm_strike,
            expiration=expiry,
            quantity=position_sizes['index_contracts'] * index_quantity,
            entry_price=put_price,
            entry_date=timestamp,
            greeks=put_greeks
        )
        
        self.risk_manager.positions = [index_call, index_put]
        
        # Create constituent positions (straddles for each)
        for symbol, data in market_data['constituents'].items():
            stock_price = data['price']
            stock_strike = round(stock_price)
            stock_iv = data['implied_vol']
            
            # Call
            stock_call_greeks = self.calculate_option_greeks(
                stock_price, stock_strike, days_to_exp/365, stock_iv, 'call'
            )
            stock_call_price = self.simulate_option_prices(
                stock_price, stock_strike, days_to_exp/365, stock_iv, 'call'
            )
            
            stock_call = Position(
                underlying=symbol,
                option_type='call',
                strike=stock_strike,
                expiration=expiry,
                quantity=position_sizes['constituent_contracts_per'] * constituent_quantity,
                entry_price=stock_call_price,
                entry_date=timestamp,
                greeks=stock_call_greeks
            )
            
            # Put
            stock_put_greeks = self.calculate_option_greeks(
                stock_price, stock_strike, days_to_exp/365, stock_iv, 'put'
            )
            stock_put_price = self.simulate_option_prices(
                stock_price, stock_strike, days_to_exp/365, stock_iv, 'put'
            )
            
            stock_put = Position(
                underlying=symbol,
                option_type='put',
                strike=stock_strike,
                expiration=expiry,
                quantity=position_sizes['constituent_contracts_per'] * constituent_quantity,
                entry_price=stock_put_price,
                entry_date=timestamp,
                greeks=stock_put_greeks
            )
            
            self.risk_manager.positions.extend([stock_call, stock_put])
        
        # Record entry
        self.risk_manager.entry_correlation = metrics.implied_correlation
        self.risk_manager.entry_zscore = metrics.correlation_zscore
        self.risk_manager.record_trade('entry', position_type, timestamp)
        
        # Create trade record
        self.active_trade = Trade(
            entry_date=timestamp,
            exit_date=None,
            position_type=position_type,
            entry_correlation=metrics.implied_correlation,
            exit_correlation=None,
            entry_zscore=metrics.correlation_zscore,
            exit_zscore=None,
            pnl=0.0,
            return_pct=0.0,
            holding_days=0,
            exit_reason=''
        )
        
        return True
    
    def exit_position(
        self,
        timestamp: pd.Timestamp,
        reason: str,
        market_data: Dict
    ) -> float:
        """
        Exit current position and calculate P&L
        """
        if self.current_position == PositionStatus.NO_POSITION:
            return 0.0
        
        # Calculate P&L
        total_pnl = 0.0
        
        for pos in self.risk_manager.positions:
            # Current option value
            if pos.underlying == 'INDEX':
                underlying_price = market_data['index_price']
                iv = market_data['index_iv']
            else:
                underlying_price = market_data['constituents'][pos.underlying]['price']
                iv = market_data['constituents'][pos.underlying]['implied_vol']
            
            # Remaining time
            days_left = (pos.expiration - timestamp).days
            if days_left < 0:
                days_left = 0
            
            current_price = self.simulate_option_prices(
                underlying_price, pos.strike, days_left/365, iv, pos.option_type
            )
            
            # P&L = (exit - entry) * quantity * 100
            trade_pnl = (current_price - pos.entry_price) * pos.quantity * 100
            total_pnl += trade_pnl
        
        # Record exit
        position_type = 'long_dispersion' if self.current_position == PositionStatus.LONG_DISPERSION else 'short_dispersion'
        self.risk_manager.record_trade('exit', position_type, timestamp, total_pnl)
        
        # Update trade record
        if self.active_trade:
            self.active_trade.exit_date = timestamp
            self.active_trade.exit_correlation = market_data.get('correlation', self.active_trade.entry_correlation)
            self.active_trade.exit_zscore = market_data.get('zscore', self.active_trade.entry_zscore)
            self.active_trade.pnl = total_pnl
            self.active_trade.return_pct = total_pnl / self.initial_capital * 100
            self.active_trade.holding_days = self.risk_manager.holding_days
            self.active_trade.exit_reason = reason
            
            self.trade_history.append(self.active_trade)
        
        # Reset state
        self.current_position = PositionStatus.NO_POSITION
        self.risk_manager.reset_position_tracking()
        self.active_trade = None
        
        # Update capital
        self.current_capital += total_pnl
        self.risk_manager.update_portfolio_value(self.current_capital)
        
        return total_pnl
    
    def update(
        self,
        timestamp: pd.Timestamp,
        metrics: CorrelationMetrics,
        market_data: Dict
    ) -> Dict:
        """
        Update strategy for current timestamp
        """
        # Increment holding days if in position
        if self.current_position != PositionStatus.NO_POSITION:
            self.risk_manager.increment_holding_days()
        
        # Check for exit if in position
        if self.current_position != PositionStatus.NO_POSITION:
            # Calculate unrealized P&L
            unrealized_pnl = 0.0
            for pos in self.risk_manager.positions:
                if pos.underlying == 'INDEX':
                    underlying_price = market_data['index_price']
                    iv = market_data['index_iv']
                else:
                    if pos.underlying in market_data['constituents']:
                        underlying_price = market_data['constituents'][pos.underlying]['price']
                        iv = market_data['constituents'][pos.underlying]['implied_vol']
                    else:
                        continue
                
                days_left = max(0, (pos.expiration - timestamp).days)
                current_price = self.simulate_option_prices(
                    underlying_price, pos.strike, days_left/365, iv, pos.option_type
                )
                unrealized_pnl += (current_price - pos.entry_price) * pos.quantity * 100
            
            # Check exit conditions
            should_exit, exit_reason = self.risk_manager.check_exit_conditions(
                metrics.implied_correlation,
                metrics.correlation_zscore,
                unrealized_pnl,
                self.risk_manager.holding_days
            )
            
            if should_exit:
                pnl = self.exit_position(timestamp, exit_reason, market_data)
                return {
                    'action': 'EXIT',
                    'reason': exit_reason,
                    'pnl': pnl,
                    'position': 'flat'
                }
            else:
                return {
                    'action': 'HOLD',
                    'unrealized_pnl': unrealized_pnl,
                    'holding_days': self.risk_manager.holding_days,
                    'position': 'long_dispersion' if self.current_position == PositionStatus.LONG_DISPERSION else 'short_dispersion'
                }
        
        # Look for entry if no position
        else:
            # Calculate ATR for trend filter
            if len(self.index_prices) >= 20:
                atr = VolatilityIndicators.calculate_atr(
                    self.index_prices.rolling(2).max(),
                    self.index_prices.rolling(2).min(),
                    self.index_prices,
                    window=20
                ).iloc[-1]
                recent_move = abs(self.index_prices.iloc[-1] - self.index_prices.iloc[-5])
            else:
                atr = 10
                recent_move = 0
            
            signal, info = self.signal_generator.generate_signal(
                metrics,
                0,  # No current position
                market_data.get('vix', 20),
                recent_move,
                atr
            )
            
            if signal in ['ENTER_LONG', 'ENTER_SHORT']:
                success = self.enter_position(timestamp, signal, metrics, market_data)
                if success:
                    return {
                        'action': signal,
                        'info': info,
                        'position': 'long_dispersion' if signal == 'ENTER_LONG' else 'short_dispersion'
                    }
            
            return {
                'action': 'NO_SIGNAL',
                'info': info,
                'position': 'flat'
            }
