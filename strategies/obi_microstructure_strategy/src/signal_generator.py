"""
Signal Generator module for Order Book Imbalance strategy.

Handles signal generation logic with confirmation and filtering.

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from collections import deque

from src.strategy import SignalType, TradeSignal, OrderBookSnapshot
from src.indicators import (
    calculate_ema, calculate_rsi, calculate_bollinger_bands,
    calculate_volume_profile, OrderBookPressureIndex
)


@dataclass
class SignalConfirmation:
    """Signal confirmation metadata."""
    confirmed: bool
    confirmation_type: str
    confidence_boost: float
    reason: str


class SignalGenerator:
    """
    Advanced signal generator with multi-factor confirmation.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize signal generator.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        
        # Confirmation settings
        self.use_rsi_confirmation = config.get('use_rsi_confirmation', True)
        self.use_volume_confirmation = config.get('use_volume_confirmation', True)
        self.use_trend_confirmation = config.get('use_trend_confirmation', True)
        
        # Thresholds
        self.rsi_overbought = config.get('rsi_overbought', 70)
        self.rsi_oversold = config.get('rsi_oversold', 30)
        self.volume_percentile_threshold = config.get('volume_percentile_threshold', 60)
        
        # State
        self.recent_signals: deque = deque(maxlen=100)
        self.pressure_index = OrderBookPressureIndex()
        self.last_signal_time: Optional[pd.Timestamp] = None
        self.signal_cooldown_seconds = config.get('signal_cooldown_seconds', 5)
        
    def check_rsi_confirmation(self, rsi: float, signal_type: SignalType) -> SignalConfirmation:
        """
        Confirm signal using RSI filter.
        
        Args:
            rsi: Current RSI value
            signal_type: Proposed signal type
            
        Returns:
            Confirmation result
        """
        if not self.use_rsi_confirmation:
            return SignalConfirmation(True, "rsi", 0.0, "RSI check disabled")
        
        if signal_type == SignalType.LONG:
            if rsi < self.rsi_overbought:
                return SignalConfirmation(
                    True, "rsi", 0.1,
                    f"RSI {rsi:.1f} below overbought ({self.rsi_overbought})"
                )
            else:
                return SignalConfirmation(
                    False, "rsi", 0.0,
                    f"RSI {rsi:.1f} overbought, avoid longs"
                )
        
        elif signal_type == SignalType.SHORT:
            if rsi > self.rsi_oversold:
                return SignalConfirmation(
                    True, "rsi", 0.1,
                    f"RSI {rsi:.1f} above oversold ({self.rsi_oversold})"
                )
            else:
                return SignalConfirmation(
                    False, "rsi", 0.0,
                    f"RSI {rsi:.1f} oversold, avoid shorts"
                )
        
        return SignalConfirmation(True, "rsi", 0.0, "Neutral")
    
    def check_volume_confirmation(self, volume: float, 
                                   volume_history: List[float]) -> SignalConfirmation:
        """
        Confirm signal using volume analysis.
        
        Args:
            volume: Current volume
            volume_history: Recent volume history
            
        Returns:
            Confirmation result
        """
        if not self.use_volume_confirmation:
            return SignalConfirmation(True, "volume", 0.0, "Volume check disabled")
        
        if len(volume_history) < 20:
            return SignalConfirmation(True, "volume", 0.0, "Insufficient volume history")
        
        # Calculate volume percentile
        volume_percentile = stats.percentileofscore(volume_history, volume)
        
        if volume_percentile >= self.volume_percentile_threshold:
            confidence = (volume_percentile - self.volume_percentile_threshold) / 40
            return SignalConfirmation(
                True, "volume", min(confidence, 0.15),
                f"Volume at {volume_percentile:.0f}th percentile"
            )
        else:
            return SignalConfirmation(
                False, "volume", 0.0,
                f"Volume at {volume_percentile:.0f}th percentile (below threshold)"
            )
    
    def check_trend_confirmation(self, price: float, 
                                  price_history: List[float],
                                  signal_type: SignalType) -> SignalConfirmation:
        """
        Confirm signal using trend alignment.
        
        Args:
            price: Current price
            price_history: Recent price history
            signal_type: Proposed signal type
            
        Returns:
            Confirmation result
        """
        if not self.use_trend_confirmation:
            return SignalConfirmation(True, "trend", 0.0, "Trend check disabled")
        
        if len(price_history) < 50:
            return SignalConfirmation(True, "trend", 0.0, "Insufficient price history")
        
        # Calculate short and medium EMAs
        prices = pd.Series(price_history)
        ema_fast = calculate_ema(prices, 10).iloc[-1]
        ema_slow = calculate_ema(prices, 50).iloc[-1]
        
        if signal_type == SignalType.LONG:
            if price > ema_fast > ema_slow:
                return SignalConfirmation(
                    True, "trend", 0.15,
                    "Price above EMA10 > EMA50 (bullish alignment)"
                )
            elif price > ema_slow:
                return SignalConfirmation(
                    True, "trend", 0.05,
                    "Price above EMA50 (moderate bullish)"
                )
            else:
                return SignalConfirmation(
                    False, "trend", 0.0,
                    "Price below EMA50 (avoid counter-trend longs)"
                )
        
        elif signal_type == SignalType.SHORT:
            if price < ema_fast < ema_slow:
                return SignalConfirmation(
                    True, "trend", 0.15,
                    "Price below EMA10 < EMA50 (bearish alignment)"
                )
            elif price < ema_slow:
                return SignalConfirmation(
                    True, "trend", 0.05,
                    "Price below EMA50 (moderate bearish)"
                )
            else:
                return SignalConfirmation(
                    False, "trend", 0.0,
                    "Price above EMA50 (avoid counter-trend shorts)"
                )
        
        return SignalConfirmation(True, "trend", 0.0, "Neutral")
    
    def check_cooldown(self, current_time: pd.Timestamp) -> bool:
        """
        Check if signal cooldown period has elapsed.
        
        Args:
            current_time: Current timestamp
            
        Returns:
            True if cooldown elapsed
        """
        if self.last_signal_time is None:
            return True
        
        elapsed = (current_time - self.last_signal_time).total_seconds()
        return elapsed >= self.signal_cooldown_seconds
    
    def generate_confirmed_signal(self,
                                  base_signal: TradeSignal,
                                  book: OrderBookSnapshot,
                                  price_history: List[float],
                                  volume_history: List[float],
                                  rsi: Optional[float] = None) -> Optional[TradeSignal]:
        """
        Generate signal with multi-factor confirmation.
        
        Args:
            base_signal: Initial signal from strategy
            book: Current order book
            price_history: Recent prices
            volume_history: Recent volumes
            rsi: Current RSI value
            
        Returns:
            Confirmed signal or None
        """
        # Check cooldown
        if not self.check_cooldown(base_signal.timestamp):
            return None
        
        confirmations: List[SignalConfirmation] = []
        
        # RSI confirmation
        if rsi is not None:
            rsi_conf = self.check_rsi_confirmation(rsi, base_signal.signal_type)
            confirmations.append(rsi_conf)
        
        # Volume confirmation
        vol_conf = self.check_volume_confirmation(
            base_signal.metadata.get('volume', 0), volume_history
        )
        confirmations.append(vol_conf)
        
        # Trend confirmation
        trend_conf = self.check_trend_confirmation(
            base_signal.price, price_history, base_signal.signal_type
        )
        confirmations.append(trend_conf)
        
        # Check if all required confirmations passed
        required_confirmations = [c for c in confirmations if not c.confirmed]
        if required_confirmations:
            # Signal rejected
            return None
        
        # Calculate boosted confidence
        confidence_boost = sum(c.confidence_boost for c in confirmations)
        final_confidence = min(base_signal.confidence + confidence_boost, 1.0)
        
        # Create confirmed signal
        confirmed_signal = TradeSignal(
            signal_type=base_signal.signal_type,
            timestamp=base_signal.timestamp,
            price=base_signal.price,
            confidence=final_confidence,
            obi_l1=base_signal.obi_l1,
            obi_depth=base_signal.obi_depth,
            ofi_momentum=base_signal.ofi_momentum,
            metadata={
                **base_signal.metadata,
                'confirmations': [c.confirmation_type for c in confirmations],
                'confidence_boost': confidence_boost
            }
        )
        
        self.recent_signals.append(confirmed_signal)
        self.last_signal_time = base_signal.timestamp
        
        return confirmed_signal
    
    def calculate_signal_quality_score(self, signal: TradeSignal) -> float:
        """
        Calculate a quality score for a signal.
        
        Higher score = better signal quality.
        
        Args:
            signal: Trade signal to evaluate
            
        Returns:
            Quality score [0, 1]
        """
        scores = []
        
        # OBI magnitude score
        obi_score = min(abs(signal.obi_l1) * 0.8 + abs(signal.obi_depth) * 0.2, 1.0)
        scores.append(obi_score)
        
        # OFI momentum alignment score
        obi_sign = np.sign(signal.obi_l1)
        ofi_sign = np.sign(signal.ofi_momentum)
        ofi_score = 1.0 if obi_sign == ofi_sign else 0.5
        scores.append(ofi_score)
        
        # Confidence score
        scores.append(signal.confidence)
        
        # Calculate weighted average
        weights = [0.4, 0.3, 0.3]
        quality_score = sum(w * s for w, s in zip(weights, scores))
        
        return quality_score
    
    def filter_signals_by_quality(self, signals: List[TradeSignal],
                                   min_quality: float = 0.6) -> List[TradeSignal]:
        """
        Filter signals by quality score.
        
        Args:
            signals: List of signals to filter
            min_quality: Minimum quality threshold
            
        Returns:
            Filtered signals
        """
        return [s for s in signals 
                if self.calculate_signal_quality_score(s) >= min_quality]


from scipy import stats
