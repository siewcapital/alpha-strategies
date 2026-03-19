"""
Data Loader for Options Dispersion Trading Strategy
Generates synthetic options data for backtesting
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
import yfinance as yf


class SyntheticOptionsDataGenerator:
    """
    Generates synthetic options data for backtesting
    
    In a real implementation, this would fetch actual options data
    from a provider like Polygon, OptionMetrics, or broker APIs
    """
    
    def __init__(
        self,
        index_symbol: str = 'SPY',
        n_constituents: int = 30,
        correlation_base: float = 0.3,
        volatility_premium: float = 0.02
    ):
        self.index_symbol = index_symbol
        self.n_constituents = n_constituents
        self.correlation_base = correlation_base
        self.volatility_premium = volatility_premium
        
        # Synthetic constituent list (S&P 500-like)
        self.constituent_symbols = [
            'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'NVDA', 'JPM',
            'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'BAC', 'ABBV', 'PFE', 'KO',
            'PEP', 'COST', 'TMO', 'AVGO', 'DIS', 'WMT', 'ABT', 'ACN', 'ADBE',
            'WFC', 'VZ', 'MRK'
        ][:n_constituents]
        
        # Generate synthetic weights (market cap weighted)
        np.random.seed(42)
        raw_weights = np.random.exponential(1, n_constituents)
        self.weights = raw_weights / raw_weights.sum()
        
    def fetch_historical_prices(
        self,
        start_date: str,
        end_date: str
    ) -> Tuple[pd.Series, pd.DataFrame]:
        """
        Fetch historical price data
        """
        try:
            # Fetch index data
            index_data = yf.download(
                self.index_symbol,
                start=start_date,
                end=end_date,
                progress=False
            )
            
            if len(index_data) == 0:
                raise ValueError(f"No data fetched for {self.index_symbol}")
            
            index_prices = index_data['Close'].squeeze()
            
            # Fetch constituent data
            constituent_data = yf.download(
                self.constituent_symbols,
                start=start_date,
                end=end_date,
                progress=False
            )
            
            if len(constituent_data) == 0:
                raise ValueError("No constituent data fetched")
            
            # Handle multi-index columns
            if isinstance(constituent_data.columns, pd.MultiIndex):
                constituent_prices = constituent_data['Close']
            else:
                constituent_prices = constituent_data['Close'].to_frame()
                constituent_prices.columns = self.constituent_symbols
            
            # Align dates
            common_dates = index_prices.index.intersection(constituent_prices.index)
            index_prices = index_prices.loc[common_dates]
            constituent_prices = constituent_prices.loc[common_dates]
            
            return index_prices, constituent_prices
            
        except Exception as e:
            print(f"Error fetching data: {e}")
            # Generate synthetic data as fallback
            return self._generate_synthetic_prices(start_date, end_date)
    
    def _generate_synthetic_prices(
        self,
        start_date: str,
        end_date: str
    ) -> Tuple[pd.Series, pd.DataFrame]:
        """
        Generate synthetic price data if fetch fails
        """
        dates = pd.date_range(start=start_date, end=end_date, freq='B')
        n_days = len(dates)
        
        np.random.seed(42)
        
        # Generate correlated returns
        # Create correlation matrix
        corr_matrix = np.full((self.n_constituents, self.n_constituents), self.correlation_base)
        np.fill_diagonal(corr_matrix, 1.0)
        
        # Cholesky decomposition for correlated random variables
        L = np.linalg.cholesky(corr_matrix)
        
        # Generate random returns
        random_returns = np.random.normal(0.0005, 0.016, (n_days, self.n_constituents))
        correlated_returns = random_returns @ L.T
        
        # Generate constituent prices
        initial_prices = np.random.uniform(50, 500, self.n_constituents)
        prices = np.zeros((n_days, self.n_constituents))
        prices[0] = initial_prices
        
        for i in range(1, n_days):
            prices[i] = prices[i-1] * (1 + correlated_returns[i])
        
        constituent_prices = pd.DataFrame(
            prices,
            index=dates,
            columns=self.constituent_symbols
        )
        
        # Calculate index as weighted average
        index_prices = (constituent_prices * self.weights).sum(axis=1)
        index_prices.name = self.index_symbol
        
        return index_prices, constituent_prices
    
    def generate_implied_volatility_surface(
        self,
        realized_vols: pd.Series,
        is_index: bool = False
    ) -> pd.Series:
        """
        Generate synthetic implied volatility from realized vol
        
        Index IV typically trades at a premium to realized
        Single stock IV closer to realized
        """
        if is_index:
            # Index IV = Realized + volatility premium + noise
            iv = realized_vols + self.volatility_premium + np.random.normal(0, 0.01, len(realized_vols))
        else:
            # Single stock IV = Realized + smaller premium + more noise
            iv = realized_vols + np.random.normal(0.005, 0.02, len(realized_vols))
        
        # Ensure positive
        iv = np.maximum(iv, 0.05)
        
        return pd.Series(iv, index=realized_vols.index)
    
    def generate_options_data(
        self,
        index_prices: pd.Series,
        constituent_prices: pd.DataFrame,
        vix_data: Optional[pd.Series] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Generate synthetic options market data
        """
        from src.indicators import VolatilityIndicators
        
        data = {
            'index': pd.DataFrame(index=index_prices.index),
            'constituents': {},
            'vix': pd.Series(index=index_prices.index)
        }
        
        # Calculate realized volatility
        index_returns = np.log(index_prices / index_prices.shift(1)).dropna()
        index_realized_vol = index_returns.rolling(30).std() * np.sqrt(252)
        
        # Generate implied volatility for index
        index_implied_vol = self.generate_implied_volatility_surface(
            index_realized_vol, is_index=True
        )
        
        data['index']['price'] = index_prices
        data['index']['realized_vol'] = index_realized_vol
        data['index']['implied_vol'] = index_implied_vol
        
        # Generate VIX proxy if not provided
        if vix_data is None:
            vix_proxy = index_implied_vol * 100 + np.random.normal(0, 2, len(index_implied_vol))
            data['vix'] = pd.Series(vix_proxy, index=index_prices.index)
        else:
            data['vix'] = vix_data.reindex(index_prices.index)
        
        # Generate data for constituents
        for symbol in constituent_prices.columns:
            prices = constituent_prices[symbol]
            returns = np.log(prices / prices.shift(1)).dropna()
            realized_vol = returns.rolling(30).std() * np.sqrt(252)
            implied_vol = self.generate_implied_volatility_surface(
                realized_vol, is_index=False
            )
            
            data['constituents'][symbol] = pd.DataFrame({
                'price': prices,
                'realized_vol': realized_vol,
                'implied_vol': implied_vol
            })
        
        return data
    
    def get_weights(self) -> pd.Series:
        """Return constituent weights"""
        return pd.Series(self.weights, index=self.constituent_symbols)
    
    def prepare_backtest_data(
        self,
        start_date: str,
        end_date: str
    ) -> Dict:
        """
        Prepare all data needed for backtesting
        """
        print(f"Fetching data from {start_date} to {end_date}...")
        
        # Fetch historical prices
        index_prices, constituent_prices = self.fetch_historical_prices(
            start_date, end_date
        )
        
        print(f"Fetched {len(index_prices)} days of data")
        
        # Generate options data
        options_data = self.generate_options_data(
            index_prices, constituent_prices
        )
        
        # Calculate returns for correlation analysis
        index_returns = np.log(index_prices / index_prices.shift(1)).dropna()
        constituent_returns = pd.DataFrame({
            symbol: np.log(options_data['constituents'][symbol]['price'] / 
                          options_data['constituents'][symbol]['price'].shift(1))
            for symbol in self.constituent_symbols
        }).dropna()
        
        return {
            'index_prices': index_prices,
            'constituent_prices': constituent_prices,
            'index_returns': index_returns,
            'constituent_returns': constituent_returns,
            'options_data': options_data,
            'weights': self.get_weights(),
            'symbols': self.constituent_symbols
        }


class DataLoader:
    """
    Main data loader interface
    """
    
    def __init__(self, use_synthetic: bool = True):
        self.use_synthetic = use_synthetic
        self.generator = SyntheticOptionsDataGenerator()
    
    def load(
        self,
        start_date: str,
        end_date: str
    ) -> Dict:
        """
        Load all required data for backtesting
        """
        return self.generator.prepare_backtest_data(start_date, end_date)
