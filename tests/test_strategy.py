"""
StatArb Alpha: Unit Tests
-------------------------
Verification tests for strategy components.
"""

import unittest
import numpy as np
import os
import sys

# Local imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(project_root, "src"))

try:
    from kalman_filter import KalmanFilter
    from cointegration import CointegrationTest
    from signal_generator import SignalGenerator
except ImportError:
    from .kalman_filter import KalmanFilter
    from .cointegration import CointegrationTest
    from .signal_generator import SignalGenerator

class TestStatArbAlpha(unittest.TestCase):
    """
    Unit tests for core strategy modules.
    """
    def test_kalman_filter_initialization(self):
        """Test if Kalman Filter initializes with correct dimensions."""
        kf = KalmanFilter()
        self.assertEqual(kf.theta.shape, (2,))
        self.assertEqual(kf.P.shape, (2, 2))

    def test_kalman_filter_step(self):
        """Test if Kalman Filter can process a single step."""
        kf = KalmanFilter()
        y_est, error, f_var = kf.step(100.0, 50.0)
        self.assertIsInstance(y_est, float)
        self.assertIsInstance(error, float)
        self.assertIsInstance(f_var, float)

    def test_cointegration_half_life(self):
        """Test if half-life calculation returns reasonable values."""
        ct = CointegrationTest()
        # Simulated mean-reverting spread
        n = 1000
        spread = np.zeros(n)
        for i in range(1, n):
            # OU process: dS = -0.5 * S * dt + noise
            spread[i] = 0.5 * spread[i-1] + np.random.normal(0, 0.1)
        
        hl = ct.calculate_half_life(spread)
        self.assertLess(hl, 10.0)
        self.assertGreater(hl, 0.0)

    def test_signal_generator_entry(self):
        """Test if Signal Generator triggers entry on high Z-score."""
        sg = SignalGenerator(z_threshold=2.0)
        signal, reason = sg.generate_signal(2.5)
        self.assertEqual(signal, -1)
        self.assertIn("Entry", reason)

    def test_signal_generator_exit(self):
        """Test if Signal Generator triggers exit on mean reversion."""
        sg = SignalGenerator(z_threshold=2.0, exit_threshold=0.0)
        # Entry
        sg.generate_signal(2.5)
        self.assertEqual(sg.current_position, -1)
        # Reversion
        signal, reason = sg.generate_signal(-0.1)
        self.assertEqual(signal, 0)
        self.assertIn("Exit", reason)

if __name__ == '__main__':
    unittest.main()
