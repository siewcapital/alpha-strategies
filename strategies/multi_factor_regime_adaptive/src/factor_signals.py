"""
factor_signals.py - Individual factor signal generators.

Each factor returns a signal in [-1, 0, 1]:
-1 = bearish signal
 0 = no signal
+1 = bullish signal

Combined with confidence score (0 to 1) for position sizing.
"""

import numpy as np
from typing import Tuple, Dict
from .indicators import (
    sma, ema, adx, rsi, atr, zscore, roc, bollinger_bands,
    sharpe_momentum, garman_klass_vol, atr_percentile
)


def trend_following_signal(closes: np.ndarray, 
                            fast_period: int = 20,
                            slow_period: int = 50) -> Tuple[np.ndarray, np.ndarray]:
    """
    Trend-following signal: price above SMA = bullish, below = bearish.
    
    Uses dual SMA crossover for confirmation.
    
    Returns:
        signals: -1, 0, or +1
        confidence: 0 to 1 (based on how far price is from SMA)
    """
    n = len(closes)
    signals = np.zeros(n)
    confidence = np.zeros(n)
    
    fast_sma = sma(closes, fast_period)
    slow_sma = sma(closes, slow_period)
    
    for i in range(slow_period, n):
        if np.isnan(fast_sma[i]) or np.isnan(slow_sma[i]):
            continue
            
        # Both SMAs must be valid
        if fast_sma[i] > slow_sma[i] and fast_sma[i-1] <= slow_sma[i-1]:
            signals[i] = 1  # Bullish crossover
            # Confidence based on how strong the trend is
            diff_pct = (fast_sma[i] - slow_sma[i]) / slow_sma[i]
            confidence[i] = np.clip(diff_pct * 10, 0, 1)  # 0-10% diff → 0-1 confidence
        elif fast_sma[i] < slow_sma[i] and fast_sma[i-1] >= slow_sma[i-1]:
            signals[i] = -1  # Bearish crossover
            diff_pct = (slow_sma[i] - fast_sma[i]) / slow_sma[i]
            confidence[i] = np.clip(diff_pct * 10, 0, 1)
        elif fast_sma[i] > slow_sma[i]:
            signals[i] = 1
            diff_pct = (fast_sma[i] - slow_sma[i]) / slow_sma[i]
            confidence[i] = np.clip(diff_pct * 5, 0, 0.8)
        elif fast_sma[i] < slow_sma[i]:
            signals[i] = -1
            diff_pct = (slow_sma[i] - fast_sma[i]) / slow_sma[i]
            confidence[i] = np.clip(diff_pct * 5, 0, 0.8)
    
    return signals, confidence


def mean_reversion_signal(closes: np.ndarray, 
                          period: int = 20,
                          z_threshold: float = 2.0) -> Tuple[np.ndarray, np.ndarray]:
    """
    Mean-reversion signal: Z-score > threshold → expect reversion.
    
    When price is far above mean (high z-score), expect it to fall.
    When price is far below mean (low z-score), expect it to rise.
    
    Returns:
        signals: -1 (short if z too high), +1 (long if z too low), 0 (neutral)
        confidence: Based on z-score magnitude
    """
    z = zscore(closes, period)
    
    n = len(closes)
    signals = np.zeros(n)
    confidence = np.zeros(n)
    
    for i in range(period, n):
        if np.isnan(z[i]):
            continue
        
        # Z > +threshold: price too high, expect reversion DOWN → signal = -1
        # Z < -threshold: price too low, expect reversion UP → signal = +1
        if z[i] > z_threshold:
            signals[i] = -1
            confidence[i] = np.clip((z[i] - z_threshold) / 2, 0, 1)
        elif z[i] < -z_threshold:
            signals[i] = 1
            confidence[i] = np.clip((-z[i] - z_threshold) / 2, 0, 1)
        else:
            signals[i] = 0
            confidence[i] = 0
    
    return signals, confidence


def volatility_breakout_signal(highs: np.ndarray, lows: np.ndarray,
                               closes: np.ndarray,
                               atr_period: int = 20,
                               vol_expansion_threshold: float = 2.0) -> Tuple[np.ndarray, np.ndarray]:
    """
    Volatility breakout signal: ATR expands significantly → momentum follows.
    
    When volatility spikes (ATR >> historical mean), there's often a directional
    move that follows. This catches those explosive moves.
    
    Returns:
        signals: +1 (long) if price breaks out with vol, -1 if breaks down
        confidence: Based on ATR expansion magnitude
    """
    current_atr = atr(highs, lows, closes, atr_period)
    
    # ATR mean over longer period
    atr_mean = np.zeros_like(current_atr)
    for i in range(2 * atr_period, len(current_atr)):
        atr_mean[i] = np.mean(current_atr[i-2*atr_period+1:i+1])
    
    n = len(closes)
    signals = np.zeros(n)
    confidence = np.zeros(n)
    
    for i in range(2 * atr_period, n):
        if np.isnan(current_atr[i]) or np.isnan(atr_mean[i]) or atr_mean[i] == 0:
            continue
        
        atr_ratio = current_atr[i] / atr_mean[i]
        
        # Significant volatility expansion
        if atr_ratio > vol_expansion_threshold:
            # Check direction of breakout
            # Use recent momentum to determine direction
            lookback = min(5, i)
            recent_return = (closes[i] - closes[i-lookback]) / closes[i-lookback]
            
            if recent_return > 0:
                signals[i] = 1
            else:
                signals[i] = -1
            
            confidence[i] = np.clip((atr_ratio - vol_expansion_threshold), 0, 2) / 2
    
    return signals, confidence


def momentum_signal(closes: np.ndarray,
                    short_period: int = 10,
                    long_period: int = 30) -> Tuple[np.ndarray, np.ndarray]:
    """
    Momentum signal: Serial correlation in returns.
    
    Assets with positive momentum (up over past period) tend to continue up.
    Uses rate of change comparison between short and long lookback.
    
    Returns:
        signals: +1 (bullish momentum), -1 (bearish momentum)
        confidence: Based on momentum strength
    """
    roc_short = roc(closes, short_period)
    roc_long = roc(closes, long_period)
    
    n = len(closes)
    signals = np.zeros(n)
    confidence = np.zeros(n)
    
    for i in range(long_period, n):
        if np.isnan(roc_short[i]) or np.isnan(roc_long[i]):
            continue
        
        # Short-term momentum > long-term = bullish
        # Both positive = strong bullish
        # Both negative = strong bearish
        # Short positive, long negative = potential reversal
        
        momentum_diff = roc_short[i] - roc_long[i]
        
        if momentum_diff > 5:  # Threshold for momentum signal
            signals[i] = 1
            confidence[i] = np.clip(momentum_diff / 20, 0, 1)
        elif momentum_diff < -5:
            signals[i] = -1
            confidence[i] = np.clip(-momentum_diff / 20, 0, 1)
    
    return signals, confidence


def all_factor_signals(highs: np.ndarray, lows: np.ndarray,
                       closes: np.ndarray) -> Dict[str, Dict[str, np.ndarray]]:
    """
    Calculate all four factor signals for a given OHLC dataset.
    
    Args:
        highs, lows, closes: OHLC arrays
        
    Returns:
        Dictionary with factor_name -> {"signal": array, "confidence": array}
    """
    tf_signal, tf_conf = trend_following_signal(closes)
    mr_signal, mr_conf = mean_reversion_signal(closes)
    vb_signal, vb_conf = volatility_breakout_signal(highs, lows, closes)
    mom_signal, mom_conf = momentum_signal(closes)
    
    return {
        "trend_following": {"signal": tf_signal, "confidence": tf_conf},
        "mean_reversion": {"signal": mr_signal, "confidence": mr_conf},
        "volatility_breakout": {"signal": vb_signal, "confidence": vb_conf},
        "momentum": {"signal": mom_signal, "confidence": mom_conf}
    }


def regime_weights(regime: str) -> Dict[str, float]:
    """
    Get factor weights based on detected market regime.
    
    In trending markets, trend-following gets more weight.
    In ranging markets, mean-reversion gets more weight.
    In high-vol markets, volatility breakout gets more weight.
    In calm markets, momentum gets more weight.
    
    Args:
        regime: One of "TRENDING", "RANGING", "HIGH_VOL", "CALM", "UNKNOWN"
        
    Returns:
        Dictionary of factor weights (must sum to 1.0)
    """
    weights = {
        "TRENDING": {
            "trend_following": 0.50,
            "mean_reversion": 0.10,
            "volatility_breakout": 0.20,
            "momentum": 0.20
        },
        "RANGING": {
            "trend_following": 0.10,
            "mean_reversion": 0.50,
            "volatility_breakout": 0.20,
            "momentum": 0.20
        },
        "HIGH_VOL": {
            "trend_following": 0.20,
            "mean_reversion": 0.10,
            "volatility_breakout": 0.60,
            "momentum": 0.10
        },
        "CALM": {
            "trend_following": 0.20,
            "mean_reversion": 0.25,
            "volatility_breakout": 0.05,
            "momentum": 0.50
        },
        "UNKNOWN": {
            "trend_following": 0.25,
            "mean_reversion": 0.25,
            "volatility_breakout": 0.25,
            "momentum": 0.25
        }
    }
    
    return weights.get(regime, weights["UNKNOWN"])


def composite_score(factor_signals: Dict[str, Dict[str, np.ndarray]],
                    weights: Dict[str, float],
                    position: int) -> Tuple[float, Dict[str, float]]:
    """
    Calculate composite factor score at a specific time point.
    
    Args:
        factor_signals: Output from all_factor_signals()
        weights: Factor weights from regime_weights()
        position: Time index
        
    Returns:
        composite_score: Weighted sum of factor signals (-1 to +1)
        breakdown: Individual factor contributions for debugging
    """
    score = 0.0
    breakdown = {}
    
    for factor_name, weight in weights.items():
        signal = factor_signals[factor_name]["signal"][position]
        confidence = factor_signals[factor_name]["confidence"][position]
        
        # Weight * signal * confidence
        contribution = weight * signal * confidence
        score += contribution
        breakdown[factor_name] = contribution
    
    # Normalize to [-1, 1]
    score = np.clip(score, -1, 1)
    
    return score, breakdown
