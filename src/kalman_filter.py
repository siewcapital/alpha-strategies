"""
StatArb Alpha: Kalman Filter Module
This module implements the state-space model for dynamic hedge ratio estimation.
It uses the prices of two assets to estimate the latent relationship.
"""

import numpy as np
from typing import Tuple

class KalmanFilter:
    def __init__(self, delta: float = 1e-5, R: float = 1e-1):
        """
        Initialize the Kalman Filter with given parameters.
        :param delta: Transition covariance parameter (Q).
        :param R: Observation covariance parameter (R).
        """
        self.delta = delta
        self.R = R
        self.V_w = self.delta / (1 - self.delta) * np.eye(2)
        self.V_v = self.R
        
        # Initial states
        self.theta = np.zeros(2)  # [intercept, beta]
        self.P = np.zeros((2, 2))
        self.state_means = []
        self.state_covs = []

    def step(self, x: float, y: float) -> Tuple[float, float, float]:
        """
        Update the filter with a new observation (x, y).
        :param x: Price of asset X.
        :param y: Price of asset Y.
        :return: (Estimated Y, Error, Variance of Error)
        """
        # 1. Prediction Step
        # theta_t|t-1 = theta_t-1
        # P_t|t-1 = P_t-1 + V_w
        self.P = self.P + self.V_w
        
        # 2. Update Step
        # F = x_t.T * P_t|t-1 * x_t + V_v
        # e = y_t - x_t.T * theta_t|t-1
        # K = P_t|t-1 * x_t * inv(F)
        # theta_t = theta_t|t-1 + K * e
        # P_t = (I - K * x_t.T) * P_t|t-1
        
        F_input = np.array([1, x])
        y_est = np.dot(F_input, self.theta)
        error = y - y_est
        
        F_var = np.dot(F_input, np.dot(self.P, F_input.T)) + self.V_v
        K = np.dot(self.P, F_input.T) / F_var
        
        self.theta = self.theta + K * error
        self.P = self.P - np.outer(K, np.dot(F_input, self.P))
        
        self.state_means.append(self.theta.copy())
        self.state_covs.append(self.P.copy())
        
        return y_est, error, F_var

    def get_hedge_ratio(self) -> float:
        """Return the current estimated hedge ratio (beta)."""
        return self.theta[1]

    def get_intercept(self) -> float:
        """Return the current estimated intercept (alpha)."""
        return self.theta[0]

    def batch_process(self, x_series: np.ndarray, y_series: np.ndarray):
        """Process entire series of prices."""
        results = []
        for x, y in zip(x_series, y_series):
            results.append(self.step(x, y))
        return np.array(results)
