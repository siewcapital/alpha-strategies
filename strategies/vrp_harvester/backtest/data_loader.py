"""
Data Loader for VRP Harvester Strategy

Generates synthetic but realistic data for backtesting that captures:
- Mean-reverting volatility dynamics
- Persistent VRP (IV > RV)
- Volatility clustering
- Correlation between BTC and ETH vol

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class SyntheticDataGenerator:
    """
    Generate synthetic price and volatility data with realistic VRP characteristics
    
    Key features:
    1. Implied volatility typically exceeds realized volatility (positive VRP)
    2. Volatility mean-reverts to long-term average
    3. Volatility clustering (high vol periods persist)
    4. Correlation between crypto asset volatilities
    """
    
    def __init__(self, seed: int = 42):
        """
        Initialize data generator
        
        Args:
            seed: Random seed for reproducibility
        """
        self.seed = seed
        np.random.seed(seed)
    
    def generate_dataset(self,
                        assets: List[str],
                        start_date: datetime,
                        end_date: datetime,
                        freq: str = 'D',
                        base_prices: Optional[Dict[str, float]] = None) -> Dict[str, pd.DataFrame]:
        """
        Generate complete dataset for multiple assets
        
        Args:
            assets: List of asset symbols (e.g., ['BTC', 'ETH'])
            start_date: Start date
            end_date: End date
            freq: Frequency ('D' for daily, 'H' for hourly)
            base_prices: Starting prices for each asset
            
        Returns:
            Dictionary of DataFrames with OHLCV + IV + RV data
        """
        logger.info(f"Generating synthetic data from {start_date} to {end_date}")
        
        if base_prices is None:
            base_prices = {'BTC': 50000, 'ETH': 3000}
        
        # Generate date range
        dates = pd.date_range(start=start_date, end=end_date, freq=freq)
        
        # Generate correlated volatility processes
        vol_processes = self._generate_volatility_processes(assets, len(dates))
        
        # Generate price and options data for each asset
        data = {}
        for asset in assets:
            base_price = base_prices.get(asset, 1000)
            df = self._generate_asset_data(
                asset=asset,
                dates=dates,
                base_price=base_price,
                implied_vols=vol_processes[asset]['iv'],
                realized_vols=vol_processes[asset]['rv']
            )
            data[asset] = df
        
        logger.info(f"Generated {len(dates)} periods of data for {len(assets)} assets")
        return data
    
    def _generate_volatility_processes(self, assets: List[str], 
                                       n_periods: int) -> Dict[str, Dict[str, np.ndarray]]:
        """
        Generate correlated IV and RV processes with persistent VRP
        
        Uses a modified Heston-like approach with:
        - Mean-reverting volatility
        - Correlation between assets
        - Consistent VRP (IV = RV + premium + noise)
        - Occasional sustained high IV periods for entry signals
        """
        n_assets = len(assets)
        
        # Parameters for volatility processes
        # Long-term mean volatility for each asset
        mean_vols = {'BTC': 0.60, 'ETH': 0.75}  # Annualized vol
        
        # Mean reversion speed (lower = slower reversion, allowing sustained periods)
        kappa = 0.5  # Reduced from 2.0 to allow longer regimes
        
        # Volatility of volatility
        vol_of_vol = 0.3
        
        # Correlation between assets
        if n_assets == 2:
            corr_matrix = np.array([[1.0, 0.7], [0.7, 1.0]])
        else:
            corr_matrix = np.eye(n_assets)
        
        # Generate correlated random shocks
        shocks = np.random.multivariate_normal(
            mean=np.zeros(n_assets),
            cov=corr_matrix,
            size=n_periods
        )
        
        # Create occasional regime changes (high vol periods)
        regime_changes = np.random.random(n_periods) < 0.02  # 2% chance of regime change per day
        regime_multipliers = np.ones((n_periods, n_assets))
        current_multiplier = 1.0
        regime_duration = 0
        
        for t in range(n_periods):
            if regime_changes[t] or regime_duration > 0:
                if regime_changes[t] and regime_duration == 0:
                    # Start new regime: 50% chance of high vol, 50% low vol
                    current_multiplier = 1.5 if np.random.random() > 0.5 else 0.7
                    regime_duration = np.random.randint(20, 60)  # 20-60 days
                regime_multipliers[t] = current_multiplier
                regime_duration -= 1
            else:
                current_multiplier = 1.0
                regime_multipliers[t] = 1.0
        
        # VRP parameters - ensure positive bias
        vrp_mean = 0.10  # Average 10% VRP
        vrp_vol = 0.04   # VRP variability
        
        processes = {}
        for i, asset in enumerate(assets):
            mean_vol = mean_vols.get(asset, 0.60)
            
            # Generate realized volatility (mean-reverting with regime effects)
            rv = np.zeros(n_periods)
            rv[0] = mean_vol * regime_multipliers[0, i]
            
            for t in range(1, n_periods):
                target_vol = mean_vol * regime_multipliers[t, i]
                # Heston-like process: dV = k(θ-V)dt + σ√V dW
                drift = kappa * (target_vol - rv[t-1]) * (1/365)
                diffusion = vol_of_vol * np.sqrt(max(0.01, rv[t-1])) * shocks[t, i] * np.sqrt(1/365)
                rv[t] = max(0.05, rv[t-1] + drift + diffusion)  # Floor at 5%
            
            # Generate implied volatility (RV + VRP + noise)
            vrp = np.random.normal(vrp_mean, vrp_vol, n_periods)
            # Add extra VRP during high vol regimes
            for t in range(n_periods):
                if regime_multipliers[t, i] > 1.2:
                    vrp[t] += 0.05  # Extra premium during high vol
            
            iv_noise = np.random.normal(0, 0.02, n_periods)  # Additional IV noise
            
            iv = rv + vrp + iv_noise
            iv = np.clip(iv, 0.10, 3.00)  # Keep within realistic bounds
            
            processes[asset] = {
                'iv': iv,
                'rv': rv,
                'vrp': iv - rv
            }
        
        return processes
    
    def _generate_asset_data(self,
                            asset: str,
                            dates: pd.DatetimeIndex,
                            base_price: float,
                            implied_vols: np.ndarray,
                            realized_vols: np.ndarray) -> pd.DataFrame:
        """
        Generate OHLCV price data from volatility process
        
        Uses geometric Brownian motion with time-varying volatility
        """
        n_periods = len(dates)
        
        # Generate price returns using realized volatility
        returns = np.random.normal(0, realized_vols / np.sqrt(365), n_periods)
        
        # Add some drift (slight upward bias for crypto)
        drift = 0.0002  # ~7% annual drift
        returns += drift
        
        # Calculate price series
        log_prices = np.cumsum(returns)
        prices = base_price * np.exp(log_prices)
        
        # Generate OHLC from close prices
        # Use intraday volatility based on daily vol
        intraday_vol = realized_vols / np.sqrt(3)  # Assuming 3 periods per day for OHLC
        
        opens = prices * (1 + np.random.normal(0, intraday_vol/3, n_periods))
        highs = np.maximum(opens, prices) * (1 + np.abs(np.random.normal(0, intraday_vol/2, n_periods)))
        lows = np.minimum(opens, prices) * (1 - np.abs(np.random.normal(0, intraday_vol/2, n_periods)))
        closes = prices
        
        # Generate volume (correlated with volatility)
        base_volume = 10000 if asset == 'BTC' else 50000
        volume = base_volume * (1 + realized_vols * 2) * np.random.lognormal(0, 0.5, n_periods)
        
        # Create DataFrame
        df = pd.DataFrame({
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volume.astype(int),
            'iv': implied_vols,
            'rv': realized_vols,
            'vrp': implied_vols - realized_vols
        }, index=dates)
        
        # Calculate DVOL-like volatility index
        df['dvol'] = self._calculate_dvol_proxy(df)
        
        return df
    
    def _calculate_dvol_proxy(self, df: pd.DataFrame, window: int = 30) -> pd.Series:
        """Calculate a DVOL-like volatility index"""
        # Use close-to-close returns (annualized and converted to percentage)
        returns = np.log(df['close'] / df['close'].shift(1))
        # Annualized volatility in percentage terms (e.g., 50 = 50%)
        vol = returns.rolling(window).std() * np.sqrt(365) * 100
        return vol.fillna(50)
    
    def add_volatility_events(self,
                             data: Dict[str, pd.DataFrame],
                             events: List[Dict]) -> Dict[str, pd.DataFrame]:
        """
        Add specific volatility events (crashes, spikes) to the data
        
        Args:
            data: Existing data dictionary
            events: List of event dictionaries with:
                - date: Event date
                - asset: Target asset
                - type: 'crash' or 'spike'
                - magnitude: Size of event (e.g., -0.30 for 30% crash)
        """
        for event in events:
            date = event['date']
            asset = event['asset']
            event_type = event['type']
            magnitude = event['magnitude']
            
            if asset not in data or date not in data[asset].index:
                continue
            
            df = data[asset]
            idx = df.index.get_loc(date)
            
            if event_type == 'crash':
                # Simulate crash: sharp drop in price, spike in IV
                df.loc[date, 'close'] *= (1 + magnitude)
                df.loc[date, 'low'] = min(df.loc[date, 'low'], df.loc[date, 'close'] * 0.98)
                
                # IV spike
                for offset in range(5):
                    if idx + offset < len(df):
                        spike_date = df.index[idx + offset]
                        df.loc[spike_date, 'iv'] *= (1.5 - offset * 0.1)
                        df.loc[spike_date, 'dvol'] *= (1.3 - offset * 0.08)
            
            elif event_type == 'spike':
                # Volatility spike without directional move
                for offset in range(3):
                    if idx + offset < len(df):
                        spike_date = df.index[idx + offset]
                        df.loc[spike_date, 'iv'] *= (1.3 - offset * 0.1)
        
        return data


class YahooFinanceLoader:
    """
    Load real data from Yahoo Finance and estimate IV/RV
    
    Since Yahoo doesn't provide options IV, we estimate it from price volatility
    with an assumed VRP premium.
    """
    
    @staticmethod
    def load_data(tickers: List[str],
                  start_date: datetime,
                  end_date: datetime) -> Dict[str, pd.DataFrame]:
        """
        Load price data from Yahoo Finance
        
        Note: This is a placeholder - in production would use yfinance
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed, using synthetic data")
            return {}
        
        data = {}
        for ticker in tickers:
            try:
                df = yf.download(ticker, start=start_date, end=end_date, progress=False)
                if len(df) > 0:
                    # Calculate realized volatility
                    returns = np.log(df['Close'] / df['Close'].shift(1))
                    df['rv'] = returns.rolling(30).std() * np.sqrt(365)
                    
                    # Estimate implied volatility (RV + assumed premium)
                    vrp_estimate = 0.10  # 10% VRP
                    df['iv'] = df['rv'] * (1 + np.random.normal(vrp_estimate, 0.03, len(df)))
                    
                    # Rename columns
                    df = df.rename(columns={
                        'Open': 'open',
                        'High': 'high',
                        'Low': 'low',
                        'Close': 'close',
                        'Volume': 'volume'
                    })
                    
                    # Calculate DVOL proxy
                    log_hl = np.log(df['high'] / df['low']) ** 2
                    log_co = np.log(df['close'] / df['open']) ** 2
                    var = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
                    df['dvol'] = np.sqrt(var.rolling(30).mean() * 365) * 100
                    
                    data[ticker] = df
                    logger.info(f"Loaded {len(df)} rows for {ticker}")
            except Exception as e:
                logger.error(f"Error loading {ticker}: {e}")
        
        return data


def create_backtest_data(start_date: datetime = None,
                        end_date: datetime = None,
                        use_real_data: bool = False) -> Dict[str, pd.DataFrame]:
    """
    Convenience function to create backtest data
    
    Args:
        start_date: Start date (default: 3 years ago)
        end_date: End date (default: today)
        use_real_data: Whether to attempt loading real data
        
    Returns:
        Dictionary of DataFrames
    """
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=3*365)
    
    assets = ['BTC', 'ETH']
    
    if use_real_data:
        # Try to load real data
        loader = YahooFinanceLoader()
        data = loader.load_data(['BTC-USD', 'ETH-USD'], start_date, end_date)
        if data:
            # Rename keys
            data = {'BTC': data.get('BTC-USD'), 'ETH': data.get('ETH-USD')}
            data = {k: v for k, v in data.items() if v is not None}
            if data:
                return data
    
    # Fall back to synthetic data
    generator = SyntheticDataGenerator(seed=42)
    data = generator.generate_dataset(
        assets=assets,
        start_date=start_date,
        end_date=end_date,
        freq='D',
        base_prices={'BTC': 45000, 'ETH': 2800}
    )
    
    # Add some realistic volatility events
    events = [
        {'date': start_date + timedelta(days=100), 'asset': 'BTC', 'type': 'crash', 'magnitude': -0.25},
        {'date': start_date + timedelta(days=250), 'asset': 'ETH', 'type': 'spike', 'magnitude': 0},
        {'date': start_date + timedelta(days=500), 'asset': 'BTC', 'type': 'spike', 'magnitude': 0},
    ]
    data = generator.add_volatility_events(data, events)
    
    return data
