"""
Cross-Exchange Funding Rate Arbitrage - Backtesting Data Loader
Generates synthetic funding rate data for backtesting.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class SyntheticFundingDataGenerator:
    """
    Generates realistic synthetic funding rate data for backtesting.
    
    Models:
    - Mean-reverting funding rates around interest rate
    - Exchange-specific biases and volatility
    - Cross-exchange correlations and divergences
    - Funding rate clustering and persistence
    """
    
    def __init__(
        self,
        seed: int = 42,
        base_interest_rate: float = 0.0001,  # 0.01%
        funding_interval_hours: float = 8.0
    ):
        self.seed = seed
        self.base_interest_rate = base_interest_rate
        self.funding_interval_hours = funding_interval_hours
        
        np.random.seed(seed)
        
    def generate_funding_series(
        self,
        exchange: str,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        mean_reversion_speed: float = 0.3,
        long_term_mean: Optional[float] = None,
        volatility: float = 0.0003,  # 0.03% per period
        exchange_bias: float = 0.0
    ) -> pd.DataFrame:
        """
        Generate synthetic funding rate series using Ornstein-Uhlenbeck process.
        
        Args:
            exchange: Exchange name
            symbol: Trading pair
            start_date: Start date
            end_date: End date
            mean_reversion_speed: Speed of mean reversion (theta)
            long_term_mean: Long-term mean (mu), defaults to base_interest_rate
            volatility: Volatility parameter (sigma)
            exchange_bias: Persistent bias for this exchange
        
        Returns:
            DataFrame with funding rate data
        """
        long_term_mean = long_term_mean or self.base_interest_rate
        
        # Generate time index (8-hour intervals)
        periods = int((end_date - start_date).total_seconds() / (3600 * self.funding_interval_hours))
        timestamps = [start_date + timedelta(hours=self.funding_interval_hours * i) 
                     for i in range(periods)]
        
        # Generate OU process
        funding_rates = self._generate_ou_process(
            n_steps=periods,
            theta=mean_reversion_speed,
            mu=long_term_mean + exchange_bias,
            sigma=volatility,
            initial_value=long_term_mean
        )
        
        # Generate premium index (correlated with funding)
        premium_indices = funding_rates + np.random.normal(0, volatility * 0.5, periods)
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'funding_rate': funding_rates,
            'premium_index': premium_indices,
            'exchange': exchange,
            'symbol': symbol
        })
        
        df.set_index('timestamp', inplace=True)
        return df
    
    def _generate_ou_process(
        self,
        n_steps: int,
        theta: float,
        mu: float,
        sigma: float,
        initial_value: float
    ) -> np.ndarray:
        """
        Generate Ornstein-Uhlenbeck process.
        
        dX = theta * (mu - X) * dt + sigma * dW
        """
        dt = 1.0  # One period
        x = np.zeros(n_steps)
        x[0] = initial_value
        
        for t in range(1, n_steps):
            dx = theta * (mu - x[t-1]) * dt + sigma * np.random.normal()
            x[t] = x[t-1] + dx
        
        return x
    
    def generate_cross_exchange_data(
        self,
        exchanges: List[str],
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        correlation_matrix: Optional[np.ndarray] = None,
        divergence_frequency: float = 0.1  # 10% of periods have divergence
    ) -> Dict[str, Dict[str, pd.DataFrame]]:
        """
        Generate correlated funding data across multiple exchanges.
        
        Args:
            exchanges: List of exchange names
            symbols: List of symbols
            start_date: Start date
            end_date: End date
            correlation_matrix: Correlation between exchanges
            divergence_frequency: How often divergences occur
        
        Returns:
            Nested dict: data[symbol][exchange] = DataFrame
        """
        data = {}
        
        # Default correlation matrix (high correlation between exchanges)
        n_exchanges = len(exchanges)
        if correlation_matrix is None:
            correlation_matrix = np.ones((n_exchanges, n_exchanges)) * 0.85
            np.fill_diagonal(correlation_matrix, 1.0)
        
        for symbol in symbols:
            data[symbol] = {}
            
            # Generate common factor (market-wide funding sentiment)
            periods = int((end_date - start_date).total_seconds() / (3600 * self.funding_interval_hours))
            common_factor = self._generate_ou_process(
                n_steps=periods,
                theta=0.2,
                mu=self.base_interest_rate,
                sigma=0.0002,
                initial_value=self.base_interest_rate
            )
            
            # Generate exchange-specific components with correlations
            for i, exchange in enumerate(exchanges):
                # Exchange-specific bias (some exchanges consistently higher/lower)
                bias = np.random.normal(0, 0.00005)  # Small random bias
                
                # Exchange-specific volatility
                vol = 0.0003 + np.random.uniform(-0.0001, 0.0001)
                
                # Combine common factor with idiosyncratic component
                idiosyncratic = np.random.normal(0, vol * np.sqrt(1 - correlation_matrix[i, 0]**2), periods)
                funding_rates = correlation_matrix[i, 0] * common_factor + idiosyncratic + bias
                
                # Add deliberate divergences for arbitrage opportunities
                funding_rates = self._add_divergences(
                    funding_rates,
                    frequency=divergence_frequency,
                    magnitude=0.0005  # 0.05% divergence
                )
                
                # Create DataFrame
                timestamps = [start_date + timedelta(hours=self.funding_interval_hours * i) 
                             for i in range(periods)]
                
                df = pd.DataFrame({
                    'timestamp': timestamps,
                    'funding_rate': funding_rates,
                    'premium_index': funding_rates + np.random.normal(0, 0.0001, periods),
                    'exchange': exchange,
                    'symbol': symbol
                })
                df.set_index('timestamp', inplace=True)
                
                data[symbol][exchange] = df
        
        return data
    
    def _add_divergences(
        self,
        funding_rates: np.ndarray,
        frequency: float,
        magnitude: float,
        persistence: int = 3
    ) -> np.ndarray:
        """
        Add temporary divergences to funding rate series.
        
        These create arbitrage opportunities.
        """
        rates = funding_rates.copy()
        n = len(rates)
        
        # Randomly select periods for divergence
        n_divergences = int(n * frequency / persistence)
        
        for _ in range(n_divergences):
            start_idx = np.random.randint(0, n - persistence)
            direction = np.random.choice([-1, 1])
            
            for j in range(persistence):
                if start_idx + j < n:
                    # Gradually add/remove divergence
                    factor = np.sin(np.pi * (j + 1) / (persistence + 1))
                    rates[start_idx + j] += direction * magnitude * factor
        
        return rates
    
    def add_market_stress_periods(
        self,
        data: Dict[str, Dict[str, pd.DataFrame]],
        stress_periods: List[Tuple[datetime, datetime]],
        stress_multiplier: float = 3.0
    ) -> Dict[str, Dict[str, pd.DataFrame]]:
        """
        Add market stress periods with elevated funding volatility.
        
        During stress:
        - Funding rates become more volatile
        - Cross-exchange divergences increase
        - Mean reversion slows
        """
        modified_data = {}
        
        for symbol, exchange_data in data.items():
            modified_data[symbol] = {}
            
            for exchange, df in exchange_data.items():
                df_modified = df.copy()
                
                for stress_start, stress_end in stress_periods:
                    mask = (df_modified.index >= stress_start) & (df_modified.index <= stress_end)
                    
                    if mask.any():
                        # Increase volatility during stress
                        current_rates = df_modified.loc[mask, 'funding_rate'].values
                        noise = np.random.normal(0, abs(current_rates) * 0.5, len(current_rates))
                        df_modified.loc[mask, 'funding_rate'] = current_rates * stress_multiplier + noise
                
                modified_data[symbol][exchange] = df_modified
        
        return modified_data


class FundingDataLoader:
    """
    Loads and processes funding rate data for backtesting.
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir
        self.generator = SyntheticFundingDataGenerator()
        self._cache: Dict[str, pd.DataFrame] = {}
    
    def load_synthetic_data(
        self,
        exchanges: List[str],
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        add_stress_periods: bool = True
    ) -> Dict[str, Dict[str, pd.DataFrame]]:
        """
        Load or generate synthetic funding data.
        """
        data = self.generator.generate_cross_exchange_data(
            exchanges=exchanges,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date
        )
        
        if add_stress_periods:
            # Add some stress periods (e.g., around known market events)
            stress_periods = [
                (start_date + timedelta(days=90), start_date + timedelta(days=100)),
                (start_date + timedelta(days=250), start_date + timedelta(days=270)),
            ]
            data = self.generator.add_market_stress_periods(data, stress_periods)
        
        return data
    
    def get_funding_differentials(
        self,
        data: Dict[str, Dict[str, pd.DataFrame]],
        symbol: str,
        exchange_a: str,
        exchange_b: str
    ) -> pd.DataFrame:
        """
        Calculate funding rate differential between two exchanges.
        """
        if symbol not in data:
            raise ValueError(f"Symbol {symbol} not in data")
        
        if exchange_a not in data[symbol] or exchange_b not in data[symbol]:
            raise ValueError(f"Exchange data missing for {symbol}")
        
        df_a = data[symbol][exchange_a]
        df_b = data[symbol][exchange_b]
        
        # Align timestamps
        merged = pd.merge(
            df_a[['funding_rate']].rename(columns={'funding_rate': f'{exchange_a}_rate'}),
            df_b[['funding_rate']].rename(columns={'funding_rate': f'{exchange_b}_rate'}),
            left_index=True,
            right_index=True,
            how='inner'
        )
        
        merged['differential'] = merged[f'{exchange_b}_rate'] - merged[f'{exchange_a}_rate']
        merged['abs_differential'] = merged['differential'].abs()
        merged['annualized_diff'] = merged['differential'] * 3 * 365
        
        return merged
    
    def calculate_summary_statistics(
        self,
        data: Dict[str, Dict[str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """
        Calculate summary statistics for the dataset.
        """
        stats = []
        
        for symbol, exchange_data in data.items():
            for exchange, df in exchange_data.items():
                stats.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'mean_funding': df['funding_rate'].mean(),
                    'std_funding': df['funding_rate'].std(),
                    'min_funding': df['funding_rate'].min(),
                    'max_funding': df['funding_rate'].max(),
                    'annualized_mean': df['funding_rate'].mean() * 3 * 365,
                    'positive_rate_pct': (df['funding_rate'] > 0).mean() * 100
                })
        
        return pd.DataFrame(stats)
