"""
Order Book Imbalance (OBI) Microstructure Momentum Strategy

High-frequency strategy exploiting order book imbalance for short-term
price prediction in crypto perpetual futures markets.

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from collections import deque
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SignalType(Enum):
    LONG = 1
    SHORT = -1
    NEUTRAL = 0


class OrderSide(Enum):
    BID = 1
    ASK = -1


@dataclass
class TradeSignal:
    """Represents a trade signal from the strategy."""
    signal_type: SignalType
    timestamp: pd.Timestamp
    price: float
    confidence: float
    obi_l1: float
    obi_depth: float
    ofi_momentum: float
    metadata: Dict


@dataclass
class OrderBookLevel:
    """Represents a single level in the order book."""
    price: float
    volume: float
    side: OrderSide


@dataclass
class OrderBookSnapshot:
    """Complete L2 order book snapshot."""
    timestamp: pd.Timestamp
    bids: List[OrderBookLevel]  # Sorted descending by price
    asks: List[OrderBookLevel]  # Sorted ascending by price
    mid_price: float
    spread: float
    
    def get_best_bid(self) -> Optional[OrderBookLevel]:
        return self.bids[0] if self.bids else None
    
    def get_best_ask(self) -> Optional[OrderBookLevel]:
        return self.asks[0] if self.asks else None
    
    def get_volume_at_level(self, side: OrderSide, level: int = 0) -> float:
        levels = self.bids if side == OrderSide.BID else self.asks
        if level < len(levels):
            return levels[level].volume
        return 0.0
    
    def get_price_at_level(self, side: OrderSide, level: int = 0) -> float:
        levels = self.bids if side == OrderSide.BID else self.asks
        if level < len(levels):
            return levels[level].price
        return self.mid_price


class OrderBookImbalanceStrategy:
    """
    Order Book Imbalance Microstructure Momentum Strategy
    
    Exploits predictive power of order book imbalance for short-term
    price movements in crypto perpetual futures.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the strategy with configuration parameters.
        
        Args:
            config: Dictionary containing strategy parameters
        """
        self.config = config
        
        # Signal thresholds
        self.obi_long_threshold = config.get('obi_long_threshold', 0.4)
        self.obi_short_threshold = config.get('obi_short_threshold', -0.4)
        self.obi_depth_threshold = config.get('obi_depth_threshold', 0.3)
        self.persistence_ticks = config.get('persistence_ticks', 3)
        self.spread_max_bps = config.get('spread_max_bps', 5.0)
        self.vol_velocity_threshold = config.get('vol_velocity_threshold', 0.5)
        
        # Risk parameters
        self.max_holding_seconds = config.get('max_holding_seconds', 30)
        self.profit_target_bps = config.get('profit_target_bps', 5.0)
        self.stop_loss_bps = config.get('stop_loss_bps', 3.0)
        self.trailing_stop_bps = config.get('trailing_stop_bps', 3.0)
        
        # State tracking
        self.ob_history: deque = deque(maxlen=100)
        self.ofi_history: deque = deque(maxlen=50)
        self.price_history: deque = deque(maxlen=200)
        self.volume_history: deque = deque(maxlen=100)
        self.last_book: Optional[OrderBookSnapshot] = None
        self.tick_count = 0
        
        # Signal tracking
        self.signals: List[TradeSignal] = []
        self.active_position: Optional[Dict] = None
        self.consecutive_long_signals = 0
        self.consecutive_short_signals = 0
        
        # Micro EMA state
        self.micro_ema = None
        self.micro_ema_alpha = 2.0 / (config.get('micro_ema_span', 50) + 1)
        
    def calculate_obi_level1(self, book: OrderBookSnapshot) -> float:
        """
        Calculate Level 1 OBI (best bid/ask only).
        
        Formula: (BidVol - AskVol) / (BidVol + AskVol)
        
        Args:
            book: Current order book snapshot
            
        Returns:
            OBI value in [-1, 1]
        """
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        
        if not best_bid or not best_ask:
            return 0.0
        
        bid_vol = best_bid.volume
        ask_vol = best_ask.volume
        
        if bid_vol + ask_vol == 0:
            return 0.0
        
        obi = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        return np.clip(obi, -1.0, 1.0)
    
    def calculate_obi_depth(self, book: OrderBookSnapshot, levels: int = 3) -> float:
        """
        Calculate depth-weighted OBI across multiple levels.
        
        Microstructure Logic:
        While Level 1 OBI only looks at the best bid and ask, depth-weighted OBI incorporates
        liquidity deeper in the book. By applying a decaying weight (e.g., L1=0.5, L2=0.3, L3=0.2),
        we prioritize orders closer to the mid-price (which are more likely to be filled and represent 
        immediate urgency) while still factoring in the broader support/resistance levels.
        This helps filter out noise from single large orders at the top of the book.
        
        Args:
            book: Current order book snapshot
            levels: Number of depth levels to include
            
        Returns:
            Depth-weighted OBI value in [-1, 1]
        """
        weights = [0.5, 0.3, 0.15, 0.05]
        obi_weighted = 0.0
        total_weight = 0.0
        
        for level in range(min(levels, len(weights))):
            bid_vol = book.get_volume_at_level(OrderSide.BID, level)
            ask_vol = book.get_volume_at_level(OrderSide.ASK, level)
            
            if bid_vol + ask_vol > 0:
                obi_l = (bid_vol - ask_vol) / (bid_vol + ask_vol)
                obi_weighted += weights[level] * obi_l
                total_weight += weights[level]
        
        if total_weight == 0:
            return 0.0
        
        return np.clip(obi_weighted / total_weight, -1.0, 1.0)
    
    def calculate_ofi(self, current: OrderBookSnapshot, previous: OrderBookSnapshot) -> float:
        """
        Calculate Order Flow Imbalance (OFI) between two book snapshots.
        
        OFI measures the net buying or selling pressure by analyzing changes in the
        best bid and ask prices and their corresponding volumes. Unlike OBI which is 
        a static snapshot, OFI measures the *flow* of orders.
        
        Microstructure Logic:
        - If the best bid price increases, the entire new bid volume represents new buying interest.
        - If the best bid price decreases, the entire old bid volume represents canceled/filled buying interest.
        - If the best bid price remains the same, the change in volume represents the net buying flow.
        - Similar logic applies symmetrically to the ask side for selling pressure.
        
        Args:
            current: Current order book snapshot
            previous: Previous order book snapshot
            
        Returns:
            OFI value representing net buying (positive) or selling (negative) pressure
        """
        cb = current.get_best_bid()
        ca = current.get_best_ask()
        pb = previous.get_best_bid()
        pa = previous.get_best_ask()
        
        if not all([cb, ca, pb, pa]):
            return 0.0
        
        # OFI formula from academic literature
        ofi = 0.0
        
        # Bid side contribution
        if cb.price >= pb.price:
            ofi += cb.volume
        if cb.price <= pb.price:
            ofi -= pb.volume
        
        # Ask side contribution
        if ca.price <= pa.price:
            ofi -= ca.volume
        if ca.price >= pa.price:
            ofi += pa.volume
        
        # Normalize by average volume
        avg_vol = (cb.volume + ca.volume + pb.volume + pa.volume) / 4
        if avg_vol > 0:
            ofi = ofi / avg_vol
        
        return ofi
    
    def update_micro_ema(self, price: float):
        """Update micro-trend EMA."""
        if self.micro_ema is None:
            self.micro_ema = price
        else:
            self.micro_ema = (self.micro_ema * (1 - self.micro_ema_alpha) + 
                            price * self.micro_ema_alpha)
    
    def calculate_ofi_momentum(self, window: int = 10) -> float:
        """
        Calculate OFI momentum (EMA of recent OFI values).
        
        Args:
            window: Number of OFI events to consider
            
        Returns:
            Smoothed OFI momentum
        """
        if len(self.ofi_history) < window:
            return 0.0
        
        recent_ofi = list(self.ofi_history)[-window:]
        alpha = 2.0 / (window + 1)
        ema = recent_ofi[0]
        for ofi in recent_ofi[1:]:
            ema = ema * (1 - alpha) + ofi * alpha
        return ema
    
    def calculate_volume_velocity(self, current_volume: float, window: int = 60) -> float:
        """
        Calculate volume velocity relative to recent average.
        
        Args:
            current_volume: Current tick volume
            window: Lookback window for average
            
        Returns:
            Volume velocity ratio
        """
        self.volume_history.append(current_volume)
        if len(self.volume_history) < window // 2:
            return 1.0
        
        avg_volume = np.mean(list(self.volume_history)[-window:])
        if avg_volume == 0:
            return 1.0
        
        return current_volume / avg_volume
    
    def check_persistence(self, obi: float, threshold: float, 
                          required_ticks: int) -> bool:
        """
        Check if OBI has persisted above threshold for required ticks.
        
        Args:
            obi: Current OBI value
            threshold: Threshold to check
            required_ticks: Number of consecutive ticks required
            
        Returns:
            True if persistence condition met
        """
        if threshold > 0:  # Long signal
            if obi > threshold:
                self.consecutive_long_signals += 1
                self.consecutive_short_signals = 0
            else:
                self.consecutive_long_signals = 0
            return self.consecutive_long_signals >= required_ticks
        else:  # Short signal
            if obi < threshold:
                self.consecutive_short_signals += 1
                self.consecutive_long_signals = 0
            else:
                self.consecutive_short_signals = 0
            return self.consecutive_short_signals >= required_ticks
    
    def detect_spoofing(self, obi_history: List[float], window: int = 10) -> bool:
        """
        Detect potential spoofing by checking for rapid OBI oscillations.
        
        Args:
            obi_history: Recent OBI values
            window: Lookback window
            
        Returns:
            True if spoofing detected
        """
        if len(obi_history) < window:
            return False
        
        recent = obi_history[-window:]
        zero_crossings = sum(1 for i in range(1, len(recent)) 
                           if recent[i-1] * recent[i] < 0)
        
        # More than 3 zero crossings in 10 ticks suggests manipulation
        return zero_crossings > 3
    
    def generate_signal(self, book: OrderBookSnapshot, 
                       trade_volume: float = 0) -> Optional[TradeSignal]:
        """
        Generate trading signal based on order book state.
        
        Args:
            book: Current order book snapshot
            trade_volume: Volume of most recent trade
            
        Returns:
            TradeSignal if conditions met, None otherwise
        """
        self.tick_count += 1
        
        # Update price history and micro EMA
        self.price_history.append(book.mid_price)
        self.update_micro_ema(book.mid_price)
        
        # Calculate OBI metrics
        obi_l1 = self.calculate_obi_level1(book)
        obi_depth = self.calculate_obi_depth(book)
        
        # Calculate OFI if we have previous book
        ofi = 0.0
        if self.last_book is not None:
            ofi = self.calculate_ofi(book, self.last_book)
        self.ofi_history.append(ofi)
        self.last_book = book
        
        # Calculate derived metrics
        ofi_momentum = self.calculate_ofi_momentum()
        vol_velocity = self.calculate_volume_velocity(trade_volume)
        
        # Calculate spread in basis points
        spread_bps = (book.spread / book.mid_price) * 10_000
        
        # Store OBI history
        self.ob_history.append(obi_l1)
        
        # Check spoofing filter
        if self.detect_spoofing(list(self.ob_history)):
            return None
        
        # Micro-trend filter
        micro_trend_bullish = book.mid_price > self.micro_ema if self.micro_ema else True
        
        metadata = {
            'obi_l1': obi_l1,
            'obi_depth': obi_depth,
            'ofi_momentum': ofi_momentum,
            'vol_velocity': vol_velocity,
            'spread_bps': spread_bps,
            'micro_trend_bullish': micro_trend_bullish
        }
        
        # Check for long signal
        if (obi_l1 > self.obi_long_threshold or obi_depth > self.obi_depth_threshold):
            if (ofi_momentum > 0 and 
                self.check_persistence(obi_l1, self.obi_long_threshold, 
                                      self.persistence_ticks) and
                micro_trend_bullish and
                spread_bps < self.spread_max_bps and
                vol_velocity > self.vol_velocity_threshold):
                
                confidence = min(abs(obi_l1) * 0.8 + abs(ofi_momentum) * 0.2, 1.0)
                
                signal = TradeSignal(
                    signal_type=SignalType.LONG,
                    timestamp=book.timestamp,
                    price=book.mid_price,
                    confidence=confidence,
                    obi_l1=obi_l1,
                    obi_depth=obi_depth,
                    ofi_momentum=ofi_momentum,
                    metadata=metadata
                )
                self.signals.append(signal)
                return signal
        
        # Check for short signal
        elif (obi_l1 < self.obi_short_threshold or obi_depth < -self.obi_depth_threshold):
            if (ofi_momentum < 0 and 
                self.check_persistence(obi_l1, self.obi_short_threshold, 
                                      self.persistence_ticks) and
                not micro_trend_bullish and
                spread_bps < self.spread_max_bps and
                vol_velocity > self.vol_velocity_threshold):
                
                confidence = min(abs(obi_l1) * 0.8 + abs(ofi_momentum) * 0.2, 1.0)
                
                signal = TradeSignal(
                    signal_type=SignalType.SHORT,
                    timestamp=book.timestamp,
                    price=book.mid_price,
                    confidence=confidence,
                    obi_l1=obi_l1,
                    obi_depth=obi_depth,
                    ofi_momentum=ofi_momentum,
                    metadata=metadata
                )
                self.signals.append(signal)
                return signal
        
        return None
    
    def should_exit(self, current_price: float, 
                   entry_price: float,
                   entry_time: pd.Timestamp,
                   current_time: pd.Timestamp,
                   current_obi: float) -> Tuple[bool, str]:
        """
        Determine if position should be exited.
        
        Args:
            current_price: Current market price
            entry_price: Position entry price
            entry_time: Position entry timestamp
            current_time: Current timestamp
            current_obi: Current OBI value
            
        Returns:
            Tuple of (should_exit, reason)
        """
        position_type = np.sign(current_price - entry_price)  # Simplified
        pnl_bps = abs(current_price - entry_price) / entry_price * 10_000
        
        # Time-based exit
        time_held = (current_time - entry_time).total_seconds()
        if time_held >= self.max_holding_seconds:
            return True, "time_exit"
        
        # Profit target
        if pnl_bps >= self.profit_target_bps:
            return True, "profit_target"
        
        # Stop loss
        if pnl_bps <= -self.stop_loss_bps:
            return True, "stop_loss"
        
        # OBI reversal exit
        if position_type > 0 and current_obi < 0:  # Long position, OBI flipped
            return True, "obi_reversal"
        if position_type < 0 and current_obi > 0:  # Short position, OBI flipped
            return True, "obi_reversal"
        
        return False, ""
    
    def reset(self):
        """Reset strategy state."""
        self.ob_history.clear()
        self.ofi_history.clear()
        self.price_history.clear()
        self.volume_history.clear()
        self.last_book = None
        self.tick_count = 0
        self.signals.clear()
        self.active_position = None
        self.consecutive_long_signals = 0
        self.consecutive_short_signals = 0
        self.micro_ema = None
