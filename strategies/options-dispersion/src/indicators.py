"""
Indicators module for Options Dispersion Trading Strategy
Handles correlation calculations, volatility metrics, and technical indicators
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from scipy import stats


@dataclass
class CorrelationMetrics:
    """Container for correlation-related metrics"""
    implied_correlation: float
    realized_correlation: float
    correlation_zscore: float
    correlation_percentile: float
    basket_volatility: float
    index_volatility: float
    timestamp: pd.Timestamp


class CorrelationCalculator:
    """
    Calculates implied and realized correlation from index and constituent data
    """
    
    def __init__(self, lookback_window: int = 90):
        self.lookback_window = lookback_window
        self.correlation_history: List[CorrelationMetrics] = []
        
    def calculate_basket_volatility(
        self, 
        constituent_vols: pd.Series,
        weights: pd.Series,
        correlation_matrix: Optional[pd.DataFrame] = None
    ) -> float:
        """
        Calculate implied volatility of a basket of stocks
        
        If correlation_matrix is None, assumes average correlation
        """
        # Variance contribution from individual stocks
        weighted_var = (weights ** 2 * constituent_vols ** 2).sum()
        
        if correlation_matrix is not None:
            # Full correlation calculation
            cov_contribution = 0
            for i in range(len(constituent_vols)):
                for j in range(i+1, len(constituent_vols)):
                    cov_contribution += (
                        weights.iloc[i] * weights.iloc[j] * 
                        constituent_vols.iloc[i] * constituent_vols.iloc[j] *
                        correlation_matrix.iloc[i, j]
                    )
            basket_var = weighted_var + 2 * cov_contribution
        else:
            # Approximation using average correlation
            avg_correlation = 0.3  # Assumed average
            cross_terms = 0
            for i in range(len(constituent_vols)):
                for j in range(i+1, len(constituent_vols)):
                    cross_terms += (
                        weights.iloc[i] * weights.iloc[j] * 
                        constituent_vols.iloc[i] * constituent_vols.iloc[j]
                    )
            basket_var = weighted_var + 2 * avg_correlation * cross_terms
            
        return np.sqrt(basket_var)
    
    def calculate_implied_correlation(
        self,
        index_vol: float,
        constituent_vols: pd.Series,
        weights: pd.Series
    ) -> float:
        """
        Calculate "dirty" implied correlation from index and single-name vols
        
        Formula: ρ_implied ≈ (σ_index² - Σwᵢ²σᵢ²) / (ΣᵢΣⱼ≠ᵢ wᵢwⱼσᵢσⱼ)
        """
        index_var = index_vol ** 2
        
        # Weighted variance sum
        weighted_var_sum = (weights ** 2 * constituent_vols ** 2).sum()
        
        # Cross terms (approximation for denominator)
        cross_terms = 0
        for i in range(len(constituent_vols)):
            for j in range(i+1, len(constituent_vols)):
                cross_terms += (
                    weights.iloc[i] * weights.iloc[j] * 
                    constituent_vols.iloc[i] * constituent_vols.iloc[j]
                )
        
        if cross_terms == 0:
            return 0.0
            
        numerator = index_var - weighted_var_sum
        denominator = 2 * cross_terms
        
        implied_corr = numerator / denominator
        
        # Bound between 0 and 1
        return np.clip(implied_corr, 0.0, 1.0)
    
    def calculate_realized_correlation(
        self,
        returns: pd.DataFrame,
        weights: pd.Series,
        window: int = 30
    ) -> float:
        """
        Calculate realized correlation from historical returns
        """
        if len(returns) < window:
            return 0.5  # Default neutral value
            
        recent_returns = returns.iloc[-window:]
        
        # Calculate average pairwise correlation
        corr_matrix = recent_returns.corr()
        
        # Extract upper triangle (excluding diagonal)
        mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
        correlations = corr_matrix.values[mask]
        
        if len(correlations) == 0:
            return 0.5
            
        return np.mean(correlations)
    
    def calculate_correlation_zscore(
        self,
        current_correlation: float,
        historical_correlations: List[float]
    ) -> Tuple[float, float]:
        """
        Calculate z-score and percentile of current correlation
        """
        if len(historical_correlations) < 30:
            return 0.0, 50.0
            
        mean_corr = np.mean(historical_correlations)
        std_corr = np.std(historical_correlations)
        
        if std_corr == 0:
            return 0.0, 50.0
            
        z_score = (current_correlation - mean_corr) / std_corr
        percentile = stats.percentileofscore(historical_correlations, current_correlation)
        
        return z_score, percentile
    
    def update(
        self,
        timestamp: pd.Timestamp,
        index_vol: float,
        constituent_vols: pd.Series,
        weights: pd.Series,
        returns: Optional[pd.DataFrame] = None
    ) -> CorrelationMetrics:
        """
        Update correlation metrics with new data
        """
        # Calculate implied correlation
        implied_corr = self.calculate_implied_correlation(
            index_vol, constituent_vols, weights
        )
        
        # Calculate realized correlation
        realized_corr = 0.5
        if returns is not None and len(returns) > 0:
            realized_corr = self.calculate_realized_correlation(
                returns, weights, self.lookback_window
            )
        
        # Calculate basket volatility
        basket_vol = self.calculate_basket_volatility(
            constituent_vols, weights
        )
        
        # Update history
        historical_implied = [m.implied_correlation for m in self.correlation_history]
        
        z_score, percentile = self.calculate_correlation_zscore(
            implied_corr, historical_implied
        )
        
        metrics = CorrelationMetrics(
            implied_correlation=implied_corr,
            realized_correlation=realized_corr,
            correlation_zscore=z_score,
            correlation_percentile=percentile,
            basket_volatility=basket_vol,
            index_volatility=index_vol,
            timestamp=timestamp
        )
        
        self.correlation_history.append(metrics)
        
        # Keep only last lookback_window metrics
        if len(self.correlation_history) > self.lookback_window:
            self.correlation_history.pop(0)
            
        return metrics


class VolatilityIndicators:
    """
    Volatility-related calculations and indicators
    """
    
    @staticmethod
    def calculate_realized_volatility(
        prices: pd.Series,
        window: int = 30,
        annualize: bool = True
    ) -> float:
        """Calculate realized volatility from price series"""
        if len(prices) < 2:
            return 0.0
            
        log_returns = np.log(prices / prices.shift(1)).dropna()
        
        if len(log_returns) == 0:
            return 0.0
            
        vol = log_returns.std()
        
        if annualize:
            vol *= np.sqrt(252)
            
        return vol
    
    @staticmethod
    def calculate_atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 14
    ) -> pd.Series:
        """Calculate Average True Range"""
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=window).mean()
        
        return atr
    
    @staticmethod
    def calculate_volatility_regime(
        prices: pd.Series,
        short_window: int = 20,
        long_window: int = 60
    ) -> str:
        """
        Determine volatility regime
        Returns: 'low', 'normal', 'high'
        """
        short_vol = VolatilityIndicators.calculate_realized_volatility(
            prices, short_window
        )
        long_vol = VolatilityIndicators.calculate_realized_volatility(
            prices, long_window
        )
        
        ratio = short_vol / long_vol if long_vol > 0 else 1.0
        
        if ratio < 0.8:
            return 'low'
        elif ratio > 1.2:
            return 'high'
        else:
            return 'normal'


class SignalGenerator:
    """
    Generates trading signals based on correlation metrics and filters
    """
    
    def __init__(
        self,
        z_score_threshold_long: float = 2.0,
        z_score_threshold_exit: float = 0.0,
        z_score_threshold_short: float = -2.0,
        vix_max: float = 35.0,
        vix_min: float = 10.0,
        max_atr_multiple: float = 2.0
    ):
        self.z_score_threshold_long = z_score_threshold_long
        self.z_score_threshold_exit = z_score_threshold_exit
        self.z_score_threshold_short = z_score_threshold_short
        self.vix_max = vix_max
        self.vix_min = vix_min
        self.max_atr_multiple = max_atr_multiple
        
    def check_filters(
        self,
        metrics: CorrelationMetrics,
        vix: float,
        recent_index_move: float,
        atr: float
    ) -> Dict[str, bool]:
        """
        Check all entry/exit filters
        """
        filters = {
            'vix_in_range': self.vix_min < vix < self.vix_max,
            'no_large_move': abs(recent_index_move) < self.max_atr_multiple * atr,
            'valid_correlation': 0 < metrics.implied_correlation < 1,
            'sufficient_history': len(metrics.timestamp) > 30 if isinstance(metrics.timestamp, pd.DatetimeIndex) else True
        }
        
        return filters
    
    def generate_signal(
        self,
        metrics: CorrelationMetrics,
        current_position: int,  # 0 = none, 1 = long dispersion, -1 = short dispersion
        vix: float,
        recent_index_move: float,
        atr: float
    ) -> Tuple[str, Dict]:
        """
        Generate trading signal based on current state
        
        Returns:
            (signal, info_dict)
            signal: 'ENTER_LONG', 'ENTER_SHORT', 'EXIT', 'HOLD'
        """
        # Check filters
        filters = self.check_filters(metrics, vix, recent_index_move, atr)
        
        if not all(filters.values()):
            return 'HOLD', {'reason': 'filters_not_met', 'filters': filters}
        
        z_score = metrics.correlation_zscore
        
        # Decision logic
        if current_position == 0:
            # No position - look for entry
            if z_score > self.z_score_threshold_long:
                return 'ENTER_LONG', {
                    'reason': 'high_implied_correlation',
                    'z_score': z_score,
                    'implied_corr': metrics.implied_correlation
                }
            elif z_score < self.z_score_threshold_short:
                return 'ENTER_SHORT', {
                    'reason': 'low_implied_correlation',
                    'z_score': z_score,
                    'implied_corr': metrics.implied_correlation
                }
                
        elif current_position == 1:
            # Long dispersion position - look for exit
            if z_score <= self.z_score_threshold_exit:
                return 'EXIT', {
                    'reason': 'reversion_to_mean',
                    'z_score': z_score,
                    'implied_corr': metrics.implied_correlation
                }
                
        elif current_position == -1:
            # Short dispersion position - look for exit
            if z_score >= self.z_score_threshold_exit:
                return 'EXIT', {
                    'reason': 'reversion_to_mean',
                    'z_score': z_score,
                    'implied_corr': metrics.implied_correlation
                }
        
        return 'HOLD', {'reason': 'no_signal', 'z_score': z_score}
