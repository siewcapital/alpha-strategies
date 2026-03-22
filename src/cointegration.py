"""
StatArb Alpha: Cointegration and Half-Life Estimation
This module provides statistical tests for the pair's relationship.
"""

import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller, coint
from typing import Tuple

class CointegrationTest:
    def __init__(self, p_value_threshold: float = 0.05):
        self.p_value_threshold = p_value_threshold

    def check_cointegration(self, x: np.ndarray, y: np.ndarray) -> bool:
        """
        Check if asset prices x and y are cointegrated using Engle-Granger.
        :return: True if cointegrated (p < p_value_threshold).
        """
        score, p_value, _ = coint(x, y)
        return p_value < self.p_value_threshold

    def calculate_half_life(self, spread: np.ndarray) -> float:
        """
        Calculate the half-life of mean reversion using OU process logic.
        :param spread: The spread time series.
        :return: Half-life in days (float).
        """
        # Linear regression of change in spread on lagged spread
        delta_spread = np.diff(spread)
        lagged_spread = spread[:-1]
        
        # dy = theta * (mu - y) * dt + sigma * dW
        # dy = -theta * y + (theta * mu)
        X = sm.add_constant(lagged_spread)
        model = sm.OLS(delta_spread, X)
        results = model.fit()
        
        # lambda is the coefficient on the lagged spread (theta in OU)
        lambda_val = results.params[1]
        
        if lambda_val >= 0:
            return 9999.0  # Not mean reverting
        
        half_life = -np.log(2) / lambda_val
        return half_life

    def calculate_z_score(self, spread: np.ndarray, window: int = 24) -> np.ndarray:
        """
        Calculate rolling Z-score of the spread.
        :param spread: The spread time series.
        :param window: Rolling window for mean and std.
        :return: Rolling Z-score series.
        """
        # Using a rolling window to normalize the spread
        # spread = PriceA - (beta * PriceB + intercept)
        mean = np.zeros_like(spread)
        std = np.zeros_like(spread)
        z_score = np.zeros_like(spread)
        
        for i in range(window, len(spread)):
            window_slice = spread[i-window:i]
            mean[i] = np.mean(window_slice)
            std[i] = np.std(window_slice)
            if std[i] != 0:
                z_score[i] = (spread[i] - mean[i]) / std[i]
                
        return z_score
