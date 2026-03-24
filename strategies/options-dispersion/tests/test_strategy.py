"""
Unit tests for Options Dispersion Trading Strategy
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '/Users/siewbrayden/.openclaw/agents/atlas/workspace/strategies/options-dispersion')

from src.indicators import (
    CorrelationCalculator,
    CorrelationMetrics,
    VolatilityIndicators,
    SignalGenerator
)
from src.risk_manager import (
    RiskManager,
    Position,
    Greeks,
    PositionStatus
)
from src.strategy import DispersionStrategy, Trade


class TestCorrelationCalculator(unittest.TestCase):
    """Test correlation calculation logic"""
    
    def setUp(self):
        self.calc = CorrelationCalculator(lookback_window=30)
        
    def test_implied_correlation_calculation(self):
        """Test implied correlation calculation"""
        index_vol = 0.20
        constituent_vols = pd.Series([0.25, 0.30, 0.28, 0.22, 0.26])
        weights = pd.Series([0.2, 0.2, 0.2, 0.2, 0.2])
        
        implied_corr = self.calc.calculate_implied_correlation(
            index_vol, constituent_vols, weights
        )
        
        # Implied correlation should be between 0 and 1
        self.assertGreaterEqual(implied_corr, 0)
        self.assertLessEqual(implied_corr, 1)
        
    def test_basket_volatility(self):
        """Test basket volatility calculation"""
        constituent_vols = pd.Series([0.25, 0.30, 0.28])
        weights = pd.Series([0.33, 0.33, 0.34])
        
        basket_vol = self.calc.calculate_basket_volatility(
            constituent_vols, weights
        )
        
        # Basket vol should be reasonable
        self.assertGreater(basket_vol, 0)
        self.assertLess(basket_vol, 1)
        
    def test_correlation_zscore(self):
        """Test z-score calculation"""
        current = 0.5
        historical = [0.4, 0.42, 0.38, 0.45, 0.41] * 10  # 50 data points
        
        zscore, percentile = self.calc.calculate_correlation_zscore(
            current, historical
        )
        
        # With current higher than mean, zscore should be positive
        self.assertGreater(zscore, 0)
        self.assertGreater(percentile, 50)


class TestVolatilityIndicators(unittest.TestCase):
    """Test volatility indicator calculations"""
    
    def test_realized_volatility(self):
        """Test realized volatility calculation"""
        # Generate synthetic price series
        np.random.seed(42)
        returns = np.random.normal(0.0005, 0.02, 100)
        prices = 100 * np.exp(np.cumsum(returns))
        price_series = pd.Series(prices)
        
        vol = VolatilityIndicators.calculate_realized_volatility(
            price_series, window=30
        )
        
        # Volatility should be positive and reasonable
        self.assertGreater(vol, 0)
        self.assertLess(vol, 2)  # Less than 200%
        
    def test_volatility_regime(self):
        """Test volatility regime detection"""
        # Low vol series
        low_vol_prices = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0, 0.005, 100))))
        
        regime = VolatilityIndicators.calculate_volatility_regime(low_vol_prices)
        self.assertIn(regime, ['low', 'normal', 'high'])


class TestSignalGenerator(unittest.TestCase):
    """Test signal generation logic"""
    
    def setUp(self):
        self.generator = SignalGenerator(
            z_score_threshold_long=2.0,
            z_score_threshold_exit=0.0,
            z_score_threshold_short=-2.0,
            vix_max=35.0,
            vix_min=10.0,
            max_atr_multiple=2.0
        )
        
    def test_entry_signal_long(self):
        """Test long dispersion entry signal"""
        metrics = CorrelationMetrics(
            implied_correlation=0.7,
            realized_correlation=0.5,
            correlation_zscore=2.5,  # Above threshold
            correlation_percentile=95,
            basket_volatility=0.25,
            index_volatility=0.20,
            timestamp=pd.Timestamp.now()
        )
        
        signal, info = self.generator.generate_signal(
            metrics, 0, vix=20, recent_index_move=5, atr=10
        )
        
        self.assertEqual(signal, 'ENTER_LONG')
        
    def test_exit_signal(self):
        """Test exit signal for long position"""
        metrics = CorrelationMetrics(
            implied_correlation=0.4,
            realized_correlation=0.4,
            correlation_zscore=-0.5,  # Reverted to mean
            correlation_percentile=40,
            basket_volatility=0.25,
            index_volatility=0.20,
            timestamp=pd.Timestamp.now()
        )
        
        signal, info = self.generator.generate_signal(
            metrics, 1, vix=20, recent_index_move=5, atr=10
        )
        
        self.assertEqual(signal, 'EXIT')


class TestRiskManager(unittest.TestCase):
    """Test risk management logic"""
    
    def setUp(self):
        self.rm = RiskManager(
            portfolio_value=1_000_000,
            target_vega_exposure=0.001,
            max_vega_exposure=0.005,
            max_loss_per_trade=0.02
        )
        
    def test_portfolio_greeks(self):
        """Test portfolio Greeks calculation"""
        # Create sample positions
        pos1 = Position(
            underlying='INDEX',
            option_type='call',
            strike=100,
            expiration=pd.Timestamp.now() + timedelta(days=30),
            quantity=10,
            entry_price=5.0,
            entry_date=pd.Timestamp.now(),
            greeks=Greeks(delta=0.5, gamma=0.05, theta=-0.1, vega=0.2)
        )
        
        self.rm.positions = [pos1]
        greeks = self.rm.calculate_portfolio_greeks()
        
        self.assertAlmostEqual(greeks.delta, 5.0)  # 10 * 0.5
        self.assertAlmostEqual(greeks.vega, 2.0)   # 10 * 0.2
        
    def test_position_sizing(self):
        """Test position size calculation"""
        sizes = self.rm.calculate_position_size(
            index_vega=0.2,
            avg_constituent_vega=0.25,
            signal_type='ENTER_LONG'
        )
        
        self.assertIn('index_contracts', sizes)
        self.assertIn('constituent_contracts_per', sizes)
        self.assertGreater(sizes['index_contracts'], 0)
        
    def test_stop_loss(self):
        """Test stop loss calculation"""
        should_exit, reason = self.rm.check_exit_conditions(
            current_correlation=0.5,
            current_zscore=0.0,
            unrealized_pnl=-25000,  # -2.5% loss
            days_in_trade=10
        )
        
        self.assertTrue(should_exit)
        self.assertEqual(reason, 'stop_loss')


class TestDispersionStrategy(unittest.TestCase):
    """Test main strategy logic"""
    
    def setUp(self):
        self.params = {
            'signals': {
                'correlation': {
                    'lookback_window': 30,
                    'z_score_threshold_long': 2.0,
                    'z_score_threshold_exit': 0.0,
                    'z_score_threshold_short': -2.0
                },
                'volatility': {
                    'vix_max': 35,
                    'vix_min': 10
                },
                'trend_filter': {
                    'max_atr_multiple': 2.0
                }
            },
            'position_sizing': {
                'target_vega_exposure': 0.001,
                'max_vega_exposure': 0.005
            },
            'options': {
                'days_to_expiration': 30,
                'delta_target': 0.5
            },
            'risk_management': {
                'stop_loss': {
                    'max_loss_per_trade': 0.02,
                    'implied_correlation_move': 3.0
                },
                'time_stop': {
                    'max_hold_days': 30
                },
                'delta_hedge': {
                    'threshold': 0.10
                }
            }
        }
        
        self.strategy = DispersionStrategy(
            params=self.params,
            initial_capital=1_000_000
        )
        
    def test_option_greeks_calculation(self):
        """Test option Greeks calculation"""
        greeks = self.strategy.calculate_option_greeks(
            underlying_price=100,
            strike=100,
            time_to_expiry=30/365,
            implied_vol=0.25,
            option_type='call'
        )
        
        # ATM call should have delta ~0.5
        self.assertGreater(greeks.delta, 0.4)
        self.assertLess(greeks.delta, 0.6)
        
        # Greeks should be positive where expected
        self.assertGreater(greeks.gamma, 0)
        self.assertGreater(greeks.vega, 0)


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestCorrelationCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestVolatilityIndicators))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManager))
    suite.addTests(loader.loadTestsFromTestCase(TestDispersionStrategy))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
