"""
Synthetic Order Book Data Generator

Generates realistic Level 2 order book data for backtesting the OBI strategy.
Simulates microstructure dynamics including liquidity clustering, order flow,
and price discovery processes.

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional, Generator
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class OrderBookTick:
    """Represents a single order book tick."""
    timestamp: pd.Timestamp
    bids: List[Tuple[float, float]]  # (price, volume) list
    asks: List[Tuple[float, float]]  # (price, volume) list
    mid_price: float
    spread: float
    trade_volume: float
    trade_side: int  # 1 = buy, -1 = sell, 0 = none


class SyntheticOrderBookGenerator:
    """
    Generates synthetic order book data with realistic microstructure.
    """
    
    def __init__(self, 
                 base_price: float = 50000.0,
                 tick_size: float = 0.1,
                 volatility_annual: float = 0.6,
                 mean_reversion_speed: float = 0.1,
                 random_seed: int = 42):
        """
        Initialize the generator.
        
        Args:
            base_price: Starting price
            tick_size: Minimum price increment
            volatility_annual: Annualized volatility
            mean_reversion_speed: Speed of mean reversion
            random_seed: Random seed for reproducibility
        """
        self.base_price = base_price
        self.tick_size = tick_size
        self.volatility = volatility_annual
        self.mean_reversion_speed = mean_reversion_speed
        
        np.random.seed(random_seed)
        
        # Microstructure parameters
        self.base_spread_bps = 2.0  # Base spread in basis points
        self.volume_lambda = 5.0  # Poisson arrival rate for trades
        self.order_arrival_rate = 10.0  # Orders per second
        
        # OBI dynamics
        self.obi_persistence = 0.95  # AR(1) coefficient for OBI
        self.obi_noise_std = 0.15
        
    def _generate_base_price_path(self, 
                                  n_ticks: int,
                                  tick_duration_ms: int = 100) -> np.ndarray:
        """
        Generate base price path using Ornstein-Uhlenbeck process.
        
        Args:
            n_ticks: Number of ticks
            tick_duration_ms: Duration of each tick in milliseconds
            
        Returns:
            Array of prices
        """
        dt = tick_duration_ms / (1000 * 60 * 60 * 24 * 365)  # Convert to years
        
        prices = np.zeros(n_ticks)
        prices[0] = self.base_price
        
        for i in range(1, n_ticks):
            # Mean reversion
            mean_rev = self.mean_reversion_speed * (self.base_price - prices[i-1]) * dt
            
            # Random walk
            dW = np.random.normal(0, np.sqrt(dt))
            diffusion = self.volatility * prices[i-1] * dW
            
            prices[i] = prices[i-1] + mean_rev + diffusion
            
            # Ensure positive price
            prices[i] = max(prices[i], self.tick_size)
        
        # Round to tick size
        prices = np.round(prices / self.tick_size) * self.tick_size
        
        return prices
    
    def _generate_obi_series(self, n_ticks: int) -> np.ndarray:
        """
        Generate realistic OBI series with persistence.
        
        Args:
            n_ticks: Number of ticks
            
        Returns:
            Array of OBI values in [-1, 1]
        """
        obi = np.zeros(n_ticks)
        obi[0] = np.random.uniform(-0.2, 0.2)
        
        for i in range(1, n_ticks):
            # AR(1) process with mean reversion to 0
            obi[i] = (self.obi_persistence * obi[i-1] + 
                     np.random.normal(0, self.obi_noise_std))
        
        # Add occasional strong imbalances (information events)
        event_prob = 0.02
        for i in range(n_ticks):
            if np.random.random() < event_prob:
                obi[i] = np.random.choice([-1, 1]) * np.random.uniform(0.5, 0.9)
        
        return np.clip(obi, -1, 1)
    
    def _generate_liquidity_profile(self, 
                                    mid_price: float,
                                    obi: float,
                                    base_depth: float = 100.0) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        """
        Generate bid/ask liquidity based on OBI.
        
        Args:
            mid_price: Current mid price
            obi: Current OBI value
            base_depth: Base liquidity depth
            
        Returns:
            Tuple of (bids, asks) where each is list of (price, volume)
        """
        n_levels = 5
        
        # Adjust base depth based on OBI
        if obi > 0:
            bid_depth = base_depth * (1 + obi)
            ask_depth = base_depth * (1 - obi * 0.5)
        else:
            bid_depth = base_depth * (1 + obi * 0.5)
            ask_depth = base_depth * (1 - obi)
        
        # Generate bids (descending from mid)
        bids = []
        for i in range(n_levels):
            price = mid_price - (i + 1) * self.tick_size
            # Volume decreases with distance from mid
            vol = bid_depth * np.exp(-i * 0.3) * (1 + np.random.uniform(-0.2, 0.2))
            bids.append((price, max(vol, 1.0)))
        
        # Generate asks (ascending from mid)
        asks = []
        for i in range(n_levels):
            price = mid_price + (i + 1) * self.tick_size
            vol = ask_depth * np.exp(-i * 0.3) * (1 + np.random.uniform(-0.2, 0.2))
            asks.append((price, max(vol, 1.0)))
        
        return bids, asks
    
    def _generate_trades(self, 
                         obi: float, 
                         n_trades: int = 1) -> Tuple[float, int]:
        """
        Generate trade volume and direction based on OBI.
        
        Args:
            obi: Current OBI value
            n_trades: Number of trades to generate
            
        Returns:
            Tuple of (total_volume, net_side)
        """
        if n_trades == 0:
            return 0.0, 0
        
        total_volume = 0.0
        buy_volume = 0.0
        
        for _ in range(n_trades):
            # Trade size follows log-normal distribution
            size = np.random.lognormal(2, 1) * 0.1
            
            # Trade direction biased by OBI
            buy_prob = 0.5 + obi * 0.3  # OBI +ve = more buying
            side = 1 if np.random.random() < buy_prob else -1
            
            total_volume += size
            if side == 1:
                buy_volume += size
        
        sell_volume = total_volume - buy_volume
        net_side = 1 if buy_volume > sell_volume else -1 if sell_volume > buy_volume else 0
        
        return total_volume, net_side
    
    def generate_data(self,
                      duration_hours: float = 24,
                      tick_frequency_ms: int = 100) -> Generator[OrderBookTick, None, None]:
        """
        Generate synthetic order book data.
        
        Args:
            duration_hours: Duration of data to generate
            tick_frequency_ms: Time between ticks in milliseconds
            
        Yields:
            OrderBookTick objects
        """
        n_ticks = int(duration_hours * 60 * 60 * 1000 / tick_frequency_ms)
        
        logger.info(f"Generating {n_ticks} ticks over {duration_hours} hours")
        
        # Generate base price path
        prices = self._generate_base_price_path(n_ticks, tick_frequency_ms)
        
        # Generate OBI series
        obi_series = self._generate_obi_series(n_ticks)
        
        # Generate timestamps
        start_time = pd.Timestamp('2024-01-01 00:00:00')
        timestamps = pd.date_range(
            start=start_time,
            periods=n_ticks,
            freq=f'{tick_frequency_ms}ms'
        )
        
        for i in range(n_ticks):
            mid_price = prices[i]
            obi = obi_series[i]
            
            # Generate spread
            spread_bps = self.base_spread_bps * (1 + np.random.uniform(-0.3, 0.5))
            spread = mid_price * spread_bps / 10000
            
            # Generate liquidity
            bids, asks = self._generate_liquidity_profile(mid_price, obi)
            
            # Generate trades
            n_trades = np.random.poisson(self.volume_lambda / 10)  # Scaled for tick frequency
            trade_volume, trade_side = self._generate_trades(obi, n_trades)
            
            # Adjust best bid/ask based on OBI
            if obi > 0.3:
                # Buying pressure - tighter bid, wider ask
                bids[0] = (bids[0][0], bids[0][1] * 1.5)
            elif obi < -0.3:
                # Selling pressure - tighter ask, wider bid
                asks[0] = (asks[0][0], asks[0][1] * 1.5)
            
            tick = OrderBookTick(
                timestamp=timestamps[i],
                bids=bids,
                asks=asks,
                mid_price=mid_price,
                spread=spread,
                trade_volume=trade_volume,
                trade_side=trade_side
            )
            
            yield tick
        
        logger.info("Data generation complete")


def create_dataframe_from_ticks(ticks: List[OrderBookTick]) -> pd.DataFrame:
    """
    Convert ticks to DataFrame for analysis.
    
    Args:
        ticks: List of OrderBookTick
        
    Returns:
        DataFrame with order book columns
    """
    data = {
        'timestamp': [],
        'mid_price': [],
        'spread': [],
        'best_bid': [],
        'best_ask': [],
        'best_bid_vol': [],
        'best_ask_vol': [],
        'trade_volume': [],
        'trade_side': [],
    }
    
    for tick in ticks:
        data['timestamp'].append(tick.timestamp)
        data['mid_price'].append(tick.mid_price)
        data['spread'].append(tick.spread)
        data['best_bid'].append(tick.bids[0][0] if tick.bids else None)
        data['best_ask'].append(tick.asks[0][0] if tick.asks else None)
        data['best_bid_vol'].append(tick.bids[0][1] if tick.bids else None)
        data['best_ask_vol'].append(tick.asks[0][1] if tick.asks else None)
        data['trade_volume'].append(tick.trade_volume)
        data['trade_side'].append(tick.trade_side)
    
    return pd.DataFrame(data)


if __name__ == '__main__':
    # Test data generation
    gen = SyntheticOrderBookGenerator(base_price=65000.0, random_seed=123)
    
    ticks = []
    for tick in gen.generate_data(duration_hours=1, tick_frequency_ms=100):
        ticks.append(tick)
    
    df = create_dataframe_from_ticks(ticks)
    print(f"Generated {len(df)} ticks")
    print(df.head(10))
    print("\nPrice statistics:")
    print(df['mid_price'].describe())
