"""
Indicators module for Order Book Imbalance strategy.

Contains technical indicators and calculations for market microstructure analysis.

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Optional
from scipy import stats


def calculate_ema(series: pd.Series, span: int) -> pd.Series:
    """
    Calculate Exponential Moving Average.
    
    Args:
        series: Input price series
        span: EMA span (number of periods)
        
    Returns:
        EMA series
    """
    return series.ewm(span=span, adjust=False).mean()


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, 
                  period: int = 14) -> pd.Series:
    """
    Calculate Average True Range for volatility measurement.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period
        
    Returns:
        ATR series
    """
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    
    return atr


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index.
    
    Args:
        prices: Price series
        period: RSI period
        
    Returns:
        RSI series [0, 100]
    """
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_bollinger_bands(prices: pd.Series, period: int = 20, 
                               num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.
    
    Args:
        prices: Price series
        period: Moving average period
        num_std: Number of standard deviations
        
    Returns:
        Tuple of (upper_band, middle_band, lower_band)
    """
    middle = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    
    return upper, middle, lower


def calculate_volume_profile(volume: pd.Series, price: pd.Series, 
                             bins: int = 50) -> pd.DataFrame:
    """
    Calculate Volume Profile (volume distribution by price level).
    
    Args:
        volume: Volume series
        price: Price series (typically close)
        bins: Number of price bins
        
    Returns:
        DataFrame with price levels and volume distribution
    """
    price_bins = pd.cut(price, bins=bins)
    volume_profile = volume.groupby(price_bins).sum()
    
    bin_centers = [interval.mid for interval in volume_profile.index]
    
    return pd.DataFrame({
        'price_level': bin_centers,
        'volume': volume_profile.values
    })


def calculate_poc_value_area(volume_profile: pd.DataFrame, 
                             value_area_pct: float = 0.7) -> Tuple[float, float, float]:
    """
    Calculate Point of Control (POC) and Value Area.
    
    Args:
        volume_profile: Volume profile DataFrame
        value_area_pct: Percentage of volume to include in value area
        
    Returns:
        Tuple of (poc, value_area_high, value_area_low)
    """
    # Point of Control = price level with highest volume
    poc_idx = volume_profile['volume'].idxmax()
    poc = volume_profile.loc[poc_idx, 'price_level']
    
    # Calculate Value Area (X% of volume around POC)
    total_volume = volume_profile['volume'].sum()
    target_volume = total_volume * value_area_pct
    
    sorted_by_volume = volume_profile.sort_values('volume', ascending=False)
    cumulative_volume = sorted_by_volume['volume'].cumsum()
    
    value_area = sorted_by_volume[cumulative_volume <= target_volume]
    value_area_high = value_area['price_level'].max()
    value_area_low = value_area['price_level'].min()
    
    return poc, value_area_high, value_area_low


def calculate_order_book_slope(bid_volumes: List[float], 
                                ask_volumes: List[float],
                                price_increment: float = 1.0) -> float:
    """
    Calculate slope of order book depth profile.
    
    Steeper slope indicates more concentrated liquidity near best bid/ask.
    
    Args:
        bid_volumes: List of bid volumes (L1, L2, L3...)
        ask_volumes: List of ask volumes (L1, L2, L3...)
        price_increment: Tick size
        
    Returns:
        Slope metric (positive = more bid concentration)
    """
    levels = np.arange(len(bid_volumes))
    
    # Fit linear regression to bid and ask volumes
    bid_slope, _, _, _, _ = stats.linregress(levels * price_increment, bid_volumes)
    ask_slope, _, _, _, _ = stats.linregress(levels * price_increment, ask_volumes)
    
    # Return difference (positive = bids steeper = bullish)
    return bid_slope - ask_slope


def calculate_vwap(prices: pd.Series, volumes: pd.Series) -> pd.Series:
    """
    Calculate Volume-Weighted Average Price.
    
    Args:
        prices: Price series
        volumes: Volume series
        
    Returns:
        VWAP series
    """
    typical_price = prices
    vwap = (typical_price * volumes).cumsum() / volumes.cumsum()
    return vwap


def calculate_order_flow_imbalance(trades: pd.DataFrame) -> pd.Series:
    """
    Calculate Order Flow Imbalance from trade data.
    
    Uses tick rule to classify trades as buyer or seller initiated.
    
    Args:
        trades: DataFrame with columns [price, volume, timestamp]
        
    Returns:
        OFI series
    """
    # Tick rule: trade is buyer-initiated if price > previous price
    price_changes = trades['price'].diff()
    
    # Classify trades
    trade_sign = np.where(price_changes > 0, 1,
                 np.where(price_changes < 0, -1, 0))
    
    # First trade has no classification, assume neutral
    trade_sign[0] = 0
    
    # Fill zeros with previous classification
    for i in range(1, len(trade_sign)):
        if trade_sign[i] == 0:
            trade_sign[i] = trade_sign[i-1]
    
    # Calculate signed volume
    signed_volume = trades['volume'] * trade_sign
    
    return signed_volume


def calculate_liquidity_imbalance_ratio(bid_volumes: List[float],
                                         ask_volumes: List[float]) -> float:
    """
    Calculate Liquidity Imbalance Ratio (LIR).
    
    Measures cumulative liquidity asymmetry across book levels.
    
    Args:
        bid_volumes: Bid volumes at each level
        ask_volumes: Ask volumes at each level
        
    Returns:
        LIR value [-1, 1]
    """
    cum_bid = np.cumsum(bid_volumes)
    cum_ask = np.cumsum(ask_volumes)
    
    # Calculate imbalance at each level and average
    imbalances = (cum_bid - cum_ask) / (cum_bid + cum_ask + 1e-10)
    
    return np.mean(imbalances)


def calculate_realized_volatility(returns: pd.Series, 
                                   window: int = 30) -> pd.Series:
    """
    Calculate realized volatility (annualized).
    
    Args:
        returns: Return series
        window: Rolling window
        
    Returns:
        Realized volatility series
    """
    # Calculate squared returns
    squared_returns = returns ** 2
    
    # Rolling sum of squared returns
    rv = squared_returns.rolling(window=window).sum()
    
    # Annualize (assuming intraday data, adjust accordingly)
    periods_per_year = 252 * 24 * 60 * 60  # seconds
    rv_annualized = np.sqrt(rv * periods_per_year / window)
    
    return rv_annualized


def detect_large_orders(book_depth: pd.DataFrame, 
                       threshold_std: float = 2.0) -> List[int]:
    """
    Detect anomalously large orders that may indicate institutional flow.
    
    Args:
        book_depth: DataFrame with price levels and volumes
        threshold_std: Standard deviation threshold
        
    Returns:
        List of indices where large orders detected
    """
    mean_vol = book_depth['volume'].mean()
    std_vol = book_depth['volume'].std()
    
    threshold = mean_vol + threshold_std * std_vol
    large_order_indices = book_depth[book_depth['volume'] > threshold].index.tolist()
    
    return large_order_indices


def calculate_microprice(bid_price: float, ask_price: float,
                         bid_size: float, ask_size: float) -> float:
    """
    Calculate microprice (volume-weighted mid).
    
    More accurate fair value estimate than simple mid.
    
    Args:
        bid_price: Best bid price
        ask_price: Best ask price
        bid_size: Best bid size
        ask_size: Best ask size
        
    Returns:
        Microprice
    """
    total_size = bid_size + ask_size
    if total_size == 0:
        return (bid_price + ask_price) / 2
    
    bid_weight = ask_size / total_size  # Inverse weighting
    ask_weight = bid_size / total_size
    
    microprice = bid_price * bid_weight + ask_price * ask_weight
    return microprice


def calculate_spread_percent(bid: float, ask: float) -> float:
    """
    Calculate spread as percentage of mid price.
    
    Args:
        bid: Bid price
        ask: Ask price
        
    Returns:
        Spread in basis points
    """
    mid = (bid + ask) / 2
    spread = ask - bid
    return (spread / mid) * 10_000  # Return in bps


def calculate_time_weighted_imbalance(obi_series: pd.Series, 
                                       timestamps: pd.Series) -> float:
    """
    Calculate time-weighted average of OBI.
    
    Gives more weight to imbalances that persist longer.
    
    Args:
        obi_series: Series of OBI values
        timestamps: Corresponding timestamps
        
    Returns:
        Time-weighted average OBI
    """
    if len(obi_series) < 2:
        return obi_series.iloc[0] if len(obi_series) > 0 else 0.0
    
    # Calculate time deltas
    time_deltas = timestamps.diff().dt.total_seconds().fillna(0)
    
    # Weight OBI by time held
    weighted_sum = (obi_series * time_deltas).sum()
    total_time = time_deltas.sum()
    
    if total_time == 0:
        return obi_series.mean()
    
    return weighted_sum / total_time


class OrderBookPressureIndex:
    """
    Composite index combining multiple order book pressure indicators.
    """
    
    def __init__(self):
        self.weights = {
            'obi_l1': 0.35,
            'obi_depth': 0.25,
            'ofi_momentum': 0.25,
            'liquidity_slope': 0.15
        }
    
    def calculate(self, obi_l1: float, obi_depth: float,
                 ofi_momentum: float, liquidity_slope: float) -> float:
        """
        Calculate composite pressure index.
        
        Returns:
            Index value in [-1, 1]
        """
        values = {
            'obi_l1': np.clip(obi_l1, -1, 1),
            'obi_depth': np.clip(obi_depth, -1, 1),
            'ofi_momentum': np.clip(ofi_momentum, -1, 1),
            'liquidity_slope': np.clip(liquidity_slope / 100, -1, 1)
        }
        
        composite = sum(self.weights[k] * values[k] for k in self.weights)
        return np.clip(composite, -1, 1)
