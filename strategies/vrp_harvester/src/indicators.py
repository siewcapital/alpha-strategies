"""
Indicators Module for VRP Harvester Strategy

Provides calculations for:
- Implied Volatility (IV) and Realized Volatility (RV)
- Volatility Risk Premium (VRP)
- IV Rank and IV Percentile
- Black-Scholes Greeks calculation
- DVOL/VIX-style volatility index estimation

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class VolatilityCalculator:
    """Calculates various volatility metrics"""
    
    @staticmethod
    def calculate_realized_volatility(returns: pd.Series, 
                                     window: int = 30,
                                     annualize: bool = True) -> float:
        """
        Calculate annualized realized volatility from price returns
        
        Args:
            returns: Series of log returns
            window: Lookback window in periods
            annualize: Whether to annualize the result
            
        Returns:
            Realized volatility as decimal
        """
        if len(returns) < window:
            return np.nan
        
        # Calculate standard deviation of returns
        vol = returns.tail(window).std()
        
        if annualize:
            # Assume hourly data: 24 * 365 = 8760 periods per year
            # Or daily data: 365 periods per year
            periods_per_year = 8760 if len(returns) > 10000 else 365
            vol = vol * np.sqrt(periods_per_year)
        
        return vol
    
    @staticmethod
    def calculate_parkinson_volatility(high: pd.Series, 
                                      low: pd.Series,
                                      window: int = 30,
                                      annualize: bool = True) -> float:
        """
        Calculate Parkinson volatility using high-low range
        More efficient than close-to-close when intraday data available
        
        Args:
            high: Series of high prices
            low: Series of low prices
            window: Lookback window
            annualize: Whether to annualize
            
        Returns:
            Parkinson volatility as decimal
        """
        if len(high) < window or len(low) < window:
            return np.nan
        
        # Parkinson estimator: sqrt(1/(4N*ln2) * sum(ln(high/low)^2))
        log_hl = np.log(high / low)
        parkinson_var = np.mean(log_hl.tail(window) ** 2) / (4 * np.log(2))
        
        vol = np.sqrt(parkinson_var)
        
        if annualize:
            periods_per_year = 8760 if len(high) > 10000 else 365
            vol = vol * np.sqrt(periods_per_year)
        
        return vol
    
    @staticmethod
    def calculate_garman_klass_volatility(open_price: pd.Series,
                                         high: pd.Series,
                                         low: pd.Series,
                                         close: pd.Series,
                                         window: int = 30,
                                         annualize: bool = True) -> float:
        """
        Calculate Garman-Klass volatility (most efficient for OHLC data)
        
        Args:
            open_price: Series of open prices
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            window: Lookback window
            annualize: Whether to annualize
            
        Returns:
            Garman-Klass volatility as decimal
        """
        if len(high) < window:
            return np.nan
        
        # Garman-Klass estimator
        log_hl = np.log(high / low) ** 2
        log_co = np.log(close / open_price) ** 2
        
        gk_var = 0.5 * log_hl.tail(window).mean() - (2 * np.log(2) - 1) * log_co.tail(window).mean()
        gk_var = max(0, gk_var)  # Ensure non-negative
        
        vol = np.sqrt(gk_var)
        
        if annualize:
            periods_per_year = 8760 if len(high) > 10000 else 365
            vol = vol * np.sqrt(periods_per_year)
        
        return vol
    
    @staticmethod
    def calculate_iv_rank(current_iv: float, 
                         iv_history: pd.Series,
                         lookback: int = 252) -> float:
        """
        Calculate IV Rank: where does current IV fall in historical range?
        
        IV Rank = (Current IV - Min IV) / (Max IV - Min IV) * 100
        
        Args:
            current_iv: Current implied volatility
            iv_history: Historical IV series
            lookback: Lookback period
            
        Returns:
            IV Rank (0-100)
        """
        if len(iv_history) < lookback:
            return 50.0  # Neutral if insufficient history
        
        hist = iv_history.tail(lookback)
        min_iv = hist.min()
        max_iv = hist.max()
        
        if max_iv == min_iv:
            return 50.0
        
        iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100
        return np.clip(iv_rank, 0, 100)
    
    @staticmethod
    def calculate_iv_percentile(current_iv: float,
                               iv_history: pd.Series,
                               lookback: int = 252) -> float:
        """
        Calculate IV Percentile: percentage of days IV was lower than current
        
        Args:
            current_iv: Current implied volatility
            iv_history: Historical IV series
            lookback: Lookback period
            
        Returns:
            IV Percentile (0-100)
        """
        if len(iv_history) < lookback:
            return 50.0
        
        hist = iv_history.tail(lookback)
        percentile = (hist < current_iv).mean() * 100
        return np.clip(percentile, 0, 100)
    
    @staticmethod
    def calculate_vrp(implied_vol: float, realized_vol: float) -> float:
        """
        Calculate Volatility Risk Premium
        
        Args:
            implied_vol: Implied volatility (decimal)
            realized_vol: Realized volatility (decimal)
            
        Returns:
            VRP as decimal (positive when IV > RV)
        """
        return implied_vol - realized_vol
    
    @staticmethod
    def calculate_volatility_cone(iv_history: pd.Series,
                                 percentiles: List[float] = [10, 25, 50, 75, 90]) -> Dict[str, float]:
        """
        Calculate volatility cone for context
        
        Args:
            iv_history: Historical IV series
            percentiles: Percentiles to calculate
            
        Returns:
            Dictionary of percentile values
        """
        return {f"p{int(p)}": np.percentile(iv_history, p) for p in percentiles}


class BlackScholesCalculator:
    """Black-Scholes option pricing and Greeks calculation"""
    
    @staticmethod
    def d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate d1 for Black-Scholes"""
        if T <= 0 or sigma <= 0:
            return 0
        return (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    
    @staticmethod
    def d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate d2 for Black-Scholes"""
        if T <= 0 or sigma <= 0:
            return 0
        return BlackScholesCalculator.d1(S, K, T, r, sigma) - sigma * np.sqrt(T)
    
    @classmethod
    def call_price(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate European call option price"""
        if T <= 0:
            return max(0, S - K)
        if sigma <= 0:
            return max(0, S - K)
        
        d1 = cls.d1(S, K, T, r, sigma)
        d2 = cls.d2(S, K, T, r, sigma)
        
        return S * stats.norm.cdf(d1) - K * np.exp(-r * T) * stats.norm.cdf(d2)
    
    @classmethod
    def put_price(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate European put option price"""
        if T <= 0:
            return max(0, K - S)
        if sigma <= 0:
            return max(0, K - S)
        
        d1 = cls.d1(S, K, T, r, sigma)
        d2 = cls.d2(S, K, T, r, sigma)
        
        return K * np.exp(-r * T) * stats.norm.cdf(-d2) - S * stats.norm.cdf(-d1)
    
    @classmethod
    def call_delta(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate call delta"""
        if T <= 0:
            return 1.0 if S > K else 0.0
        return stats.norm.cdf(cls.d1(S, K, T, r, sigma))
    
    @classmethod
    def put_delta(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate put delta"""
        if T <= 0:
            return -1.0 if S < K else 0.0
        return stats.norm.cdf(cls.d1(S, K, T, r, sigma)) - 1
    
    @classmethod
    def gamma(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate gamma (same for calls and puts)"""
        if T <= 0 or sigma <= 0:
            return 0
        d1 = cls.d1(S, K, T, r, sigma)
        return stats.norm.pdf(d1) / (S * sigma * np.sqrt(T))
    
    @classmethod
    def theta_call(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate call theta (daily)"""
        if T <= 0:
            return 0
        d1 = cls.d1(S, K, T, r, sigma)
        d2 = cls.d2(S, K, T, r, sigma)
        
        theta = (-S * stats.norm.pdf(d1) * sigma / (2 * np.sqrt(T)) 
                - r * K * np.exp(-r * T) * stats.norm.cdf(d2))
        return theta / 365  # Convert to daily
    
    @classmethod
    def theta_put(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate put theta (daily)"""
        if T <= 0:
            return 0
        d1 = cls.d1(S, K, T, r, sigma)
        d2 = cls.d2(S, K, T, r, sigma)
        
        theta = (-S * stats.norm.pdf(d1) * sigma / (2 * np.sqrt(T)) 
                + r * K * np.exp(-r * T) * stats.norm.cdf(-d2))
        return theta / 365  # Convert to daily
    
    @classmethod
    def vega(cls, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate vega (change per 1% change in IV)"""
        if T <= 0 or sigma <= 0:
            return 0
        d1 = cls.d1(S, K, T, r, sigma)
        return S * stats.norm.pdf(d1) * np.sqrt(T) / 100  # Per 1% IV change
    
    @classmethod
    def implied_volatility(cls, option_price: float, S: float, K: float, 
                          T: float, r: float, option_type: str = 'call',
                          precision: float = 1e-5) -> float:
        """
        Calculate implied volatility using Brent's method
        
        Args:
            option_price: Market price of option
            S: Spot price
            K: Strike price
            T: Time to expiration (years)
            r: Risk-free rate
            option_type: 'call' or 'put'
            precision: Convergence precision
            
        Returns:
            Implied volatility as decimal
        """
        if T <= 0:
            return 0
        
        def objective(sigma):
            if option_type == 'call':
                return cls.call_price(S, K, T, r, sigma) - option_price
            else:
                return cls.put_price(S, K, T, r, sigma) - option_price
        
        try:
            # Find bounds for Brent's method
            sigma_low = 0.001
            sigma_high = 5.0
            
            # Ensure bounds bracket the root
            while objective(sigma_low) > 0 and sigma_low > 1e-6:
                sigma_low /= 2
            while objective(sigma_high) < 0 and sigma_high < 10:
                sigma_high *= 2
            
            iv = brentq(objective, sigma_low, sigma_high, xtol=precision)
            return iv
        except ValueError:
            logger.warning(f"Could not solve for IV: price={option_price}, S={S}, K={K}")
            return 0.5  # Return 50% as fallback


class GreeksCalculator:
    """Calculate position Greeks for straddle positions"""
    
    def __init__(self, risk_free_rate: float = 0.05):
        """
        Initialize Greeks calculator
        
        Args:
            risk_free_rate: Annual risk-free rate (default 5%)
        """
        self.r = risk_free_rate
        self.bs = BlackScholesCalculator()
    
    def calculate_straddle_greeks(self, S: float, K: float, T: float, 
                                  sigma: float, quantity: int = 1) -> Dict[str, float]:
        """
        Calculate combined Greeks for a short straddle position
        
        Args:
            S: Spot price
            K: Strike price
            T: Time to expiration (years)
            sigma: Implied volatility
            quantity: Number of contracts (negative for short)
            
        Returns:
            Dictionary of Greeks
        """
        # Call Greeks
        call_delta = self.bs.call_delta(S, K, T, self.r, sigma)
        call_gamma = self.bs.gamma(S, K, T, self.r, sigma)
        call_theta = self.bs.theta_call(S, K, T, self.r, sigma)
        call_vega = self.bs.vega(S, K, T, self.r, sigma)
        
        # Put Greeks
        put_delta = self.bs.put_delta(S, K, T, self.r, sigma)
        put_gamma = self.bs.gamma(S, K, T, self.r, sigma)
        put_theta = self.bs.theta_put(S, K, T, self.r, sigma)
        put_vega = self.bs.vega(S, K, T, self.r, sigma)
        
        # Short straddle = short call + short put
        # Multiply by -1 for short position, then by quantity
        greeks = {
            'call_delta': -call_delta * quantity,
            'put_delta': -put_delta * quantity,
            'delta': (-call_delta - put_delta) * quantity,
            'gamma': (-call_gamma - put_gamma) * quantity,
            'theta': (-call_theta - put_theta) * quantity,
            'vega': (-call_vega - put_vega) * quantity,
            'call_premium': self.bs.call_price(S, K, T, self.r, sigma),
            'put_premium': self.bs.put_price(S, K, T, self.r, sigma)
        }
        
        return greeks
    
    def calculate_hedge_delta(self, position_delta: float, 
                             hedge_size: float) -> float:
        """
        Calculate net delta after hedging
        
        Args:
            position_delta: Option position delta
            hedge_size: Hedge position size (futures)
            
        Returns:
            Net delta
        """
        # Futures delta = 1.0 per unit
        return position_delta + hedge_size


class VolatilityRegimeDetector:
    """Detect current volatility regime for filtering"""
    
    @staticmethod
    def detect_regime(current_iv: float,
                     iv_history: pd.Series,
                     rv_history: pd.Series,
                     vrp_threshold: float = 0.02) -> Dict[str, any]:
        """
        Detect current market regime
        
        Returns:
            Dictionary with regime classification
        """
        iv_rank = VolatilityCalculator.calculate_iv_rank(current_iv, iv_history)
        iv_percentile = VolatilityCalculator.calculate_iv_percentile(current_iv, iv_history)
        
        # Classify IV level
        if iv_rank >= 80:
            iv_level = "HIGH"
        elif iv_rank >= 50:
            iv_level = "ELEVATED"
        elif iv_rank >= 20:
            iv_level = "NORMAL"
        else:
            iv_level = "LOW"
        
        # Calculate current VRP
        current_rv = rv_history.iloc[-1] if len(rv_history) > 0 else current_iv * 0.8
        vrp = current_iv - current_rv
        
        # Classify VRP
        if vrp > vrp_threshold * 2:
            vrp_state = "EXPENSIVE"
        elif vrp > vrp_threshold:
            vrp_state = "FAIR"
        else:
            vrp_state = "CHEAP"
        
        # Determine if good for VRP harvesting
        good_for_vrp = (iv_level in ["HIGH", "ELEVATED"]) and (vrp_state in ["EXPENSIVE", "FAIR"])
        
        return {
            'iv_level': iv_level,
            'iv_rank': iv_rank,
            'iv_percentile': iv_percentile,
            'vrp': vrp,
            'vrp_state': vrp_state,
            'good_for_vrp': good_for_vrp,
            'recommendation': 'ENTER' if good_for_vrp else 'WAIT'
        }


def calculate_dvol_proxy(price_data: pd.DataFrame, 
                        window: int = 30) -> pd.Series:
    """
    Calculate a DVOL-like volatility index proxy from price data
    
    This is a simplified version - real DVOL uses options chain data
    
    Args:
        price_data: DataFrame with OHLCV data
        window: Rolling window for calculation
        
    Returns:
        Series of volatility index values (annualized %)
    """
    # Use Garman-Klass for efficiency if OHLC available
    if all(col in price_data.columns for col in ['open', 'high', 'low', 'close']):
        log_hl = np.log(price_data['high'] / price_data['low']) ** 2
        log_co = np.log(price_data['close'] / price_data['open']) ** 2
        var = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
        var = var.rolling(window).mean()
    else:
        # Use close-to-close
        returns = np.log(price_data['close'] / price_data['close'].shift(1))
        var = returns.rolling(window).var()
    
    # Annualize and convert to percentage
    vol = np.sqrt(var * 365) * 100
    return vol
