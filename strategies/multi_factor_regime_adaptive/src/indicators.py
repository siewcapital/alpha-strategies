"""
indicators.py - Technical indicators for multi-factor regime-adaptive strategy.

This module provides all technical indicators needed for:
1. Trend-following signals (SMA, EMA, ADX)
2. Mean-reversion signals (Z-score, Bollinger Bands, RSI)
3. Volatility signals (ATR, Garman-Klass, volatility percentile)
4. Momentum signals (ROC, RSI, Sharpe momentum)

All functions are pure numpy/pandas for speed.
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional


def sma(closes: np.ndarray, period: int) -> np.ndarray:
    """
    Simple Moving Average.
    
    Args:
        closes: Array of closing prices
        period: SMA period
        
    Returns:
        Array of SMA values (same length as input, NaN for insufficient data)
    """
    result = np.full_like(closes, np.nan)
    result[period-1:] = pd.Series(closes).rolling(period).mean().values[period-1:]
    return result


def ema(closes: np.ndarray, period: int) -> np.ndarray:
    """
    Exponential Moving Average.
    
    Args:
        closes: Array of closing prices
        period: EMA period
        
    Returns:
        Array of EMA values
    """
    return pd.Series(closes).ewm(span=period, adjust=False).mean().values


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, 
        period: int = 14) -> np.ndarray:
    """
    Average True Range - measures market volatility.
    
    True Range = max(H - L, |H - C_prev|, |L - C_prev|)
    
    Args:
        highs: Array of high prices
        lows: Array of low prices
        closes: Array of closing prices
        period: ATR period (typically 14)
        
    Returns:
        Array of ATR values
    """
    tr = np.zeros(len(closes))
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        h_l = highs[i] - lows[i]
        h_c = abs(highs[i] - closes[i-1])
        l_c = abs(lows[i] - closes[i-1])
        tr[i] = max(h_l, h_c, l_c)
    
    atr_vals = np.full_like(tr, np.nan)
    atr_vals[period-1:] = pd.Series(tr).rolling(period).mean().values[period-1:]
    return atr_vals


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        period: int = 14) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Average Directional Index - measures trend strength (not direction).
    
    Returns:
        adx: Trend strength (0-100, >25 = trending)
        plus_di: Positive directional indicator
        minus_di: Negative directional indicator
        
    Args:
        highs, lows, closes: OHLC arrays
        period: ADX period
    """
    n = len(closes)
    
    # Calculate True Range and Directional Movements
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_c = abs(highs[i] - closes[i-1])
        l_c = abs(lows[i] - closes[i-1])
        
        tr[i] = max(h_l, h_c, l_c)
        
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
    
    # Smooth with Wilder's smoothing
    atr_smooth = np.full_like(tr, np.nan)
    plus_dm_smooth = np.full_like(plus_dm, np.nan)
    minus_dm_smooth = np.full_like(minus_dm, np.nan)
    
    atr_smooth[period-1] = np.mean(tr[1:period+1])
    plus_dm_smooth[period-1] = np.mean(plus_dm[1:period+1])
    minus_dm_smooth[period-1] = np.mean(minus_dm[1:period+1])
    
    alpha = 1.0 / period
    
    for i in range(period, n):
        atr_smooth[i] = atr_smooth[i-1] * (1 - alpha) + tr[i] * alpha
        plus_dm_smooth[i] = plus_dm_smooth[i-1] * (1 - alpha) + plus_dm[i] * alpha
        minus_dm_smooth[i] = minus_dm_smooth[i-1] * (1 - alpha) + minus_dm[i] * alpha
    
    # Calculate DI
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)
    
    valid = atr_smooth > 0
    plus_di[valid] = 100 * plus_dm_smooth[valid] / atr_smooth[valid]
    minus_di[valid] = 100 * minus_dm_smooth[valid] / atr_smooth[valid]
    
    di_sum = plus_di + minus_di
    dx[valid & (di_sum > 0)] = 100 * np.abs(plus_di[valid & (di_sum > 0)] - minus_di[valid & (di_sum > 0)]) / di_sum[valid & (di_sum > 0)]
    
    adx_vals = np.full_like(dx, np.nan)
    adx_vals[2*period-2:] = pd.Series(dx[2*period-2:]).rolling(period).mean().values
    
    return adx_vals, plus_di, minus_di


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """
    Relative Strength Index - measures momentum and overbought/oversold.
    
    Args:
        closes: Array of closing prices
        period: RSI period (typically 14)
        
    Returns:
        Array of RSI values (0-100)
    """
    deltas = np.diff(closes, prepend=closes[0])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gains = np.full_like(closes, np.nan)
    avg_losses = np.full_like(closes, np.nan)
    
    avg_gains[period] = np.mean(gains[1:period+1])
    avg_losses[period] = np.mean(losses[1:period+1])
    
    for i in range(period+1, len(closes)):
        avg_gains[i] = (avg_gains[i-1] * (period - 1) + gains[i]) / period
        avg_losses[i] = (avg_losses[i-1] * (period - 1) + losses[i]) / period
    
    rs = np.zeros_like(closes)
    rs[avg_losses > 0] = avg_gains[avg_losses > 0] / avg_losses[avg_losses > 0]
    
    rsi_vals = 100 - (100 / (1 + rs))
    return rsi_vals


def zscore(series: np.ndarray, period: int = 20) -> np.ndarray:
    """
    Z-score: How many standard deviations current value is from the mean.
    
    Used for mean-reversion signals.
    
    Args:
        series: Price series (typically close or spread)
        period: Lookback period for mean/std calculation
        
    Returns:
        Array of z-scores
    """
    mean = pd.Series(series).rolling(period).mean().values
    std = pd.Series(series).rolling(period).std().values
    
    z = np.zeros_like(series)
    z[std > 0] = (series[std > 0] - mean[std > 0]) / std[std > 0]
    z[std == 0] = 0
    return z


def bollinger_bands(closes: np.ndarray, period: int = 20, 
                    num_std: float = 2.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Bollinger Bands - mean-reversion indicator.
    
    Args:
        closes: Closing prices
        period: SMA period
        num_std: Number of standard deviations for bands
        
    Returns:
        upper_band, middle_band, lower_band
    """
    middle = sma(closes, period)
    std = pd.Series(closes).rolling(period).std().values
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def roc(closes: np.ndarray, period: int = 10) -> np.ndarray:
    """
    Rate of Change - momentum indicator.
    
    Args:
        closes: Closing prices
        period: Lookback period
        
    Returns:
        ROC as percentage
    """
    roc_vals = np.zeros_like(closes)
    roc_vals[period:] = ((closes[period:] - closes[:-period]) / closes[:-period]) * 100
    return roc_vals


def sharpe_momentum(returns: np.ndarray, lookback: int = 20) -> np.ndarray:
    """
    Momentum measured by historical Sharpe ratio.
    
    Higher = stronger upward momentum with lower volatility.
    
    Args:
        returns: Array of returns
        lookback: Period for Sharpe calculation
        
    Returns:
        Rolling Sharpe ratio
    """
    mean_ret = pd.Series(returns).rolling(lookback).mean().values
    std_ret = pd.Series(returns).rolling(lookback).std().values
    
    sharpe = np.zeros_like(returns)
    sharpe[std_ret > 0] = (mean_ret[std_ret > 0] * np.sqrt(252)) / std_ret[std_ret > 0]
    return sharpe


def garman_klass_vol(highs: np.ndarray, lows: np.ndarray, 
                     opens: np.ndarray, closes: np.ndarray,
                     period: int = 20) -> np.ndarray:
    """
    Garman-Klass Volatility Estimator.
    
    More efficient than close-to-close; uses OHLC data.
    
    Formula:
    GK = sqrt(0.5 * (log(H/L))^2 - (2*ln(2)-1) * (log(C/O))^2)
    
    Annualized by multiplying by sqrt(252).
    
    Args:
        highs, lows, opens, closes: OHLC arrays
        period: Lookback period
        
    Returns:
        Annualized Garman-Klass volatility
    """
    log_hl = np.log(highs / lows)
    log_co = np.log(closes / opens)
    
    gk_sq = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    
    gk_vol = np.sqrt(pd.Series(gk_sq).rolling(period).mean().values) * np.sqrt(252)
    return gk_vol


def atr_percentile(atr_series: np.ndarray, period: int = 100) -> np.ndarray:
    """
    ATR percentile - is current volatility high or low relative to history?
    
    Args:
        atr_series: Array of ATR values
        period: Lookback for percentile calculation
        
    Returns:
        Percentile rank of current ATR (0-100)
    """
    percentile = np.zeros_like(atr_series)
    for i in range(period, len(atr_series)):
        window = atr_series[i-period+1:i+1]
        percentile[i] = (atr_series[i] < window).sum() / len(window) * 100
    return percentile


def regime_score(adx: np.ndarray, rsi: np.ndarray, 
                 atr_pct: np.ndarray) -> np.ndarray:
    """
    Composite regime score from multiple indicators.
    
    Regime labels:
    - "TRENDING": ADX > 25, RSI not in middle range
    - "RANGING": ADX < 25, RSI in middle range
    - "HIGH_VOL": ATR percentile > 70
    - "CALM": ATR percentile < 30
    
    Returns composite score:
    - Positive = trending/bullish
    - Negative = ranging/bearish
    
    Args:
        adx: ADX values (trend strength)
        rsi: RSI values (momentum)
        atr_pct: ATR percentile (vol regime)
    """
    n = len(adx)
    score = np.zeros(n)
    
    # Trend component: ADX normalized to 0-1, scaled
    trend_score = np.clip((adx - 25) / 25, -1, 1)  # -1 to +1 based on ADX
    
    # RSI component: >50 = bullish, <50 = bearish
    rsi_score = (rsi - 50) / 50  # -1 to +1
    
    # Vol component: High vol often accompanies trends
    vol_score = (atr_pct - 50) / 50  # -1 to +1
    
    # Composite: weight trend most heavily
    score = 0.5 * trend_score + 0.3 * rsi_score + 0.2 * vol_score
    
    return score


def regime_label(adx: np.ndarray, rsi: np.ndarray, 
                 atr_pct: np.ndarray) -> np.ndarray:
    """
    Discrete regime labels based on indicators.
    
    Args:
        adx, rsi, atr_pct: Indicator arrays
        
    Returns:
        Array of regime strings: "TRENDING", "RANGING", "HIGH_VOL", "CALM"
    """
    n = len(adx)
    labels = np.array(["UNKNOWN"] * n, dtype=object)
    
    for i in range(n):
        if np.isnan(adx[i]) or np.isnan(rsi[i]) or np.isnan(atr_pct[i]):
            labels[i] = "UNKNOWN"
            continue
            
        # Determine vol regime
        is_high_vol = atr_pct[i] > 70
        is_calm = atr_pct[i] < 30
        
        # Determine trend regime
        is_trending = adx[i] > 25
        
        # Determine range regime
        is_ranging = 40 <= rsi[i] <= 60
        
        if is_high_vol:
            labels[i] = "HIGH_VOL"
        elif is_calm:
            labels[i] = "CALM"
        elif is_trending:
            labels[i] = "TRENDING"
        elif is_ranging:
            labels[i] = "RANGING"
        else:
            # Default: pick the secondary signal
            if adx[i] > 20:
                labels[i] = "TRENDING"
            else:
                labels[i] = "RANGING"
    
    return labels
