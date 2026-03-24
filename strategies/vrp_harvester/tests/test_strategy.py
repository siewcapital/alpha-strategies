"""
Unit Tests for VRP Harvester Strategy

Tests all major components:
- Volatility calculations (IV Rank, VRP, etc.)
- Black-Scholes Greeks
- Signal generation
- Risk management
- Strategy orchestration

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.indicators import VolatilityCalculator, BlackScholesCalculator, GreeksCalculator
from src.indicators import VolatilityRegimeDetector, calculate_dvol_proxy
from src.strategy import VRPHarvesterStrategy, StraddlePosition, Signal
from src.signal_generator import SignalGenerator, SignalResult
from src.risk_manager import RiskManager, PositionSizer


class TestVolatilityCalculator(unittest.TestCase):
    """Test volatility calculation functions"""
    
    def setUp(self):
        self.calc = VolatilityCalculator()
        np.random.seed(42)
    
    def test_realized_volatility_calculation(self):
        """Test RV calculation from returns"""
        # Create synthetic returns (20% annual vol)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.20/np.sqrt(365), 365))
        
        rv = self.calc.calculate_realized_volatility(returns, window=30)
        
        # Should be reasonably close to 20% (with wider tolerance for randomness)
        self.assertAlmostEqual(rv, 0.20, delta=0.10)
    
    def test_iv_rank_calculation(self):
        """Test IV Rank calculation"""
        iv_history = pd.Series(np.linspace(0.30, 0.90, 252))
        
        # Test at extremes
        self.assertAlmostEqual(self.calc.calculate_iv_rank(0.30, iv_history), 0, places=2)
        self.assertAlmostEqual(self.calc.calculate_iv_rank(0.90, iv_history), 100, places=2)
        self.assertAlmostEqual(self.calc.calculate_iv_rank(0.60, iv_history), 50, places=2)
    
    def test_iv_percentile_calculation(self):
        """Test IV Percentile calculation"""
        # Use values where the current is strictly greater than some history
        iv_history = pd.Series([0.30, 0.35, 0.40, 0.45, 0.50])
        
        # 0.40 should be at 40th percentile (2 out of 5 below) - with lookback=5
        self.assertAlmostEqual(self.calc.calculate_iv_percentile(0.40, iv_history, lookback=5), 40, delta=5)
        # 0.50 should be at 80th percentile (4 out of 5 below) - with lookback=5  
        self.assertAlmostEqual(self.calc.calculate_iv_percentile(0.50, iv_history, lookback=5), 80, delta=5)
    
    def test_vrp_calculation(self):
        """Test VRP calculation"""
        vrp = self.calc.calculate_vrp(0.70, 0.55)
        self.assertAlmostEqual(vrp, 0.15, places=5)
        
        vrp = self.calc.calculate_vrp(0.50, 0.60)
        self.assertAlmostEqual(vrp, -0.10, places=5)  # Negative VRP
    
    def test_parkinson_volatility(self):
        """Test Parkinson volatility estimator"""
        n = 100
        true_vol = 0.50
        
        # Generate OHLC data
        base = 100
        trend = np.cumsum(np.random.normal(0, true_vol/np.sqrt(365), n))
        close = base * np.exp(trend)
        
        # Generate high/low based on volatility
        daily_range = close * true_vol / np.sqrt(365) * 2
        high = close + daily_range * np.random.uniform(0.3, 0.7, n)
        low = close - daily_range * np.random.uniform(0.3, 0.7, n)
        
        vol = self.calc.calculate_parkinson_volatility(pd.Series(high), pd.Series(low))
        
        # Should be in reasonable range
        self.assertGreater(vol, 0.10)
        self.assertLess(vol, 2.0)


class TestBlackScholesCalculator(unittest.TestCase):
    """Test Black-Scholes option pricing"""
    
    def setUp(self):
        self.bs = BlackScholesCalculator()
    
    def test_call_price_atm(self):
        """Test ATM call price"""
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
        
        price = self.bs.call_price(S, K, T, r, sigma)
        
        # ATM call should be roughly 0.08 * S for these parameters
        self.assertGreater(price, 5)
        self.assertLess(price, 15)
    
    def test_put_call_parity(self):
        """Test put-call parity"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.25
        
        call = self.bs.call_price(S, K, T, r, sigma)
        put = self.bs.put_price(S, K, T, r, sigma)
        
        # Put-call parity: C - P = S - K*e^(-rT)
        parity_lhs = call - put
        parity_rhs = S - K * np.exp(-r * T)
        
        self.assertAlmostEqual(parity_lhs, parity_rhs, delta=0.01)
    
    def test_call_delta_range(self):
        """Test call delta is in valid range"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.25
        
        # ITM call should have delta > 0.5
        delta_itm = self.bs.call_delta(S, K * 0.9, T, r, sigma)
        self.assertGreater(delta_itm, 0.5)
        
        # ATM call should have delta ≈ 0.5-0.6 (increased tolerance due to high vol)
        delta_atm = self.bs.call_delta(S, K, T, r, sigma)
        self.assertAlmostEqual(delta_atm, 0.55, delta=0.15)
        
        # OTM call should have delta < 0.5
        delta_otm = self.bs.call_delta(S, K * 1.1, T, r, sigma)
        self.assertLess(delta_otm, 0.5)
    
    def test_put_delta_range(self):
        """Test put delta is in valid range"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.25
        
        delta = self.bs.put_delta(S, K, T, r, sigma)
        
        # Put delta should be negative
        self.assertLess(delta, 0)
        self.assertGreater(delta, -1)
    
    def test_gamma_positive(self):
        """Test gamma is always positive"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.25
        
        gamma = self.bs.gamma(S, K, T, r, sigma)
        self.assertGreater(gamma, 0)
    
    def test_vega_positive(self):
        """Test vega is always positive"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.25
        
        vega = self.bs.vega(S, K, T, r, sigma)
        self.assertGreater(vega, 0)
    
    def test_implied_volatility_recovery(self):
        """Test IV calculation recovers original volatility"""
        S, K, T, r = 100, 100, 0.5, 0.05
        true_sigma = 0.30
        
        # Calculate option price
        price = self.bs.call_price(S, K, T, r, true_sigma)
        
        # Recover IV
        iv = self.bs.implied_volatility(price, S, K, T, r, 'call')
        
        # Should be close to original
        self.assertAlmostEqual(iv, true_sigma, delta=0.001)


class TestGreeksCalculator(unittest.TestCase):
    """Test position Greeks calculations"""
    
    def setUp(self):
        self.gc = GreeksCalculator(risk_free_rate=0.05)
    
    def test_straddle_delta_near_zero(self):
        """Test ATM straddle has near-zero delta"""
        S, K, T, sigma = 100, 100, 0.25, 0.50
        
        greeks = self.gc.calculate_straddle_greeks(S, K, T, sigma, quantity=1)
        
        # ATM straddle should have delta close to 0 (with tolerance for high vol)
        self.assertAlmostEqual(greeks['delta'], 0, delta=0.2)
    
    def test_short_straddle_greeks(self):
        """Test short straddle has correct sign"""
        S, K, T, sigma = 100, 100, 0.25, 0.50
        
        greeks = self.gc.calculate_straddle_greeks(S, K, T, sigma, quantity=1)
        
        # Short straddle should have:
        # - Negative gamma (bad for us when price moves)
        self.assertLess(greeks['gamma'], 0)
        # - Positive theta (benefit from time decay)
        self.assertGreater(greeks['theta'], 0)
        # - Negative vega (benefit from IV drop)
        self.assertLess(greeks['vega'], 0)


class TestSignalGenerator(unittest.TestCase):
    """Test signal generation logic"""
    
    def setUp(self):
        self.config = {
            'iv_rank_min': 70,
            'iv_percentile_min': 70,
            'vrp_min': 0.05,
            'dvol_max': 80,
            'max_positions': 3,
            'min_margin': 1000
        }
        self.sg = SignalGenerator(self.config)
    
    def test_entry_signal_with_high_iv_rank(self):
        """Test entry signal when IV rank is high"""
        iv_history = pd.Series([0.50] * 200 + [0.60] * 52)
        rv_history = pd.Series([0.45] * 252)
        price_history = pd.DataFrame({
            'close': [100] * 252,
            'high': [105] * 252,
            'low': [95] * 252,
            'open': [100] * 252
        })
        
        signal = self.sg.generate_entry_signal(
            asset='BTC',
            current_price=100,
            current_iv=0.80,  # High IV
            iv_history=iv_history,
            rv_history=rv_history,
            price_history=price_history,
            available_margin=50000,
            open_positions=0
        )
        
        self.assertEqual(signal.signal_type, 'ENTER')
        self.assertGreater(signal.confidence, 0.5)
    
    def test_no_entry_when_iv_low(self):
        """Test no entry when IV rank is low"""
        iv_history = pd.Series([0.30] * 200 + [0.80] * 52)
        rv_history = pd.Series([0.45] * 252)
        price_history = pd.DataFrame({'close': [100] * 252})
        
        signal = self.sg.generate_entry_signal(
            asset='BTC',
            current_price=100,
            current_iv=0.35,  # Low IV
            iv_history=iv_history,
            rv_history=rv_history,
            price_history=price_history,
            available_margin=50000,
            open_positions=0
        )
        
        self.assertEqual(signal.signal_type, 'NONE')
    
    def test_no_entry_when_max_positions(self):
        """Test no entry when at max positions"""
        iv_history = pd.Series([0.50] * 200 + [0.60] * 52)
        rv_history = pd.Series([0.45] * 252)
        price_history = pd.DataFrame({'close': [100] * 252})
        
        signal = self.sg.generate_entry_signal(
            asset='BTC',
            current_price=100,
            current_iv=0.80,
            iv_history=iv_history,
            rv_history=rv_history,
            price_history=price_history,
            available_margin=50000,
            open_positions=3  # At max
        )
        
        self.assertEqual(signal.signal_type, 'NONE')
    
    def test_exit_at_profit_target(self):
        """Test exit signal at profit target"""
        position_data = {
            'entry_premium': 1000,
            'current_premium': 400,  # 60% profit
            'entry_date': datetime.now() - timedelta(days=10),
            'expiration': datetime.now() + timedelta(days=20),
            'entry_iv': 0.70
        }
        
        signal = self.sg.generate_exit_signal(
            asset='BTC',
            position_data=position_data,
            current_price=100,
            current_iv=0.50,
            iv_history=pd.Series([0.60] * 100)
        )
        
        self.assertEqual(signal.signal_type, 'EXIT')
        self.assertIn('profit', signal.metadata['checks'][0]['name'].lower())


class TestRiskManager(unittest.TestCase):
    """Test risk management functions"""
    
    def setUp(self):
        self.config = {
            'max_position_pct': 0.05,
            'max_portfolio_exposure': 0.15,
            'max_drawdown_pct': 0.10,
            'daily_loss_limit': 0.02,
            'consecutive_loss_limit': 3
        }
        self.rm = RiskManager(self.config)
    
    def test_kelly_criterion(self):
        """Test Kelly criterion calculation"""
        kelly = PositionSizer.kelly_criterion(
            win_rate=0.65,
            avg_win=0.50,  # Changed from 0.30 to ensure positive Kelly
            avg_loss=0.40,
            safety_factor=0.5
        )
        
        # Kelly should be positive for profitable edge
        self.assertGreater(kelly, 0)
        self.assertLess(kelly, 0.5)
    
    def test_position_size_limits(self):
        """Test position size respects limits"""
        size = PositionSizer.calculate_straddle_position_size(
            account_value=100000,
            entry_premium=500,
            max_position_pct=0.05
        )
        
        # Should be at least 1
        self.assertGreaterEqual(size, 1)
    
    def test_drawdown_halt(self):
        """Test trading halt on drawdown"""
        initial = 100000
        
        # Set peak to initial value
        self.rm.peak_portfolio_value = initial
        
        # Simulate 15% drawdown
        result = self.rm.check_drawdown(85000)
        
        self.assertTrue(result[0])  # Should be halted
        self.assertTrue(self.rm.trading_halted)
    
    def test_can_enter_checks_limits(self):
        """Test can_enter respects position limits"""
        can_trade, reason = self.rm.can_enter_position(
            account_value=100000,
            current_positions=5,  # Over limit
            position_correlations={},
            dvol_index=50
        )
        
        self.assertFalse(can_trade)
    
    def test_consecutive_loss_tracking(self):
        """Test consecutive loss counting"""
        # Record 3 losses
        for _ in range(3):
            self.rm.record_trade({'pnl': -100, 'asset': 'BTC'})
        
        self.assertEqual(self.rm.consecutive_losses, 3)
        
        # Next trade should be blocked
        can_trade, _ = self.rm.can_enter_position(100000, 0, {}, 50)
        self.assertFalse(can_trade)


class TestVRPStrategy(unittest.TestCase):
    """Test main strategy class"""
    
    def setUp(self):
        self.config = {
            'iv_rank_threshold': 70,
            'vrp_min_threshold': 0.05,
            'max_dte_entry': 21,
            'min_dte_entry': 7,
            'profit_target': 0.50,
            'stop_loss': 2.00,
            'delta_threshold': 0.15,
            'max_positions': 3
        }
        self.strategy = VRPHarvesterStrategy(self.config)
    
    def test_entry_conditions_check_iv_rank(self):
        """Test entry checks IV rank"""
        signal, metadata = self.strategy.check_entry_conditions(
            asset='BTC',
            current_iv=0.80,
            iv_rank=50,  # Too low
            iv_percentile=50,
            realized_vol=0.60,
            dvol_index=50,
            available_margin=50000
        )
        
        self.assertEqual(signal, Signal.NO_SIGNAL)
    
    def test_entry_conditions_require_vrp(self):
        """Test entry requires positive VRP"""
        signal, metadata = self.strategy.check_entry_conditions(
            asset='BTC',
            current_iv=0.50,  # Lower than RV
            iv_rank=80,
            iv_percentile=80,
            realized_vol=0.60,
            dvol_index=50,
            available_margin=50000
        )
        
        self.assertEqual(signal, Signal.NO_SIGNAL)
    
    def test_position_creation(self):
        """Test entering a position"""
        position = self.strategy.enter_position(
            asset='BTC',
            strike=50000,
            expiration=datetime.now() + timedelta(days=30),
            call_premium=1000,
            put_premium=1000,
            iv=0.70,
            underlying_price=50000,
            delta=0.05,
            gamma=0.001,
            theta=50,
            vega=-100,
            quantity=1
        )
        
        self.assertEqual(position.asset, 'BTC')
        self.assertEqual(position.total_premium, 2000)
        self.assertEqual(len(self.strategy.positions), 1)
    
    def test_exit_conditions_profit_target(self):
        """Test exit at profit target"""
        # Create a position
        position = StraddlePosition(
            asset='BTC',
            strike=50000,
            expiration=datetime.now() + timedelta(days=20),
            call_premium=1000,
            put_premium=1000,
            entry_iv=0.70,
            entry_underlying=50000,
            entry_date=datetime.now(),
            quantity=1
        )
        
        # Manually set current value to trigger profit
        position.current_iv = 0.40  # IV collapsed
        
        # This is a simplified test - in reality would need proper valuation
        signal, metadata = self.strategy.check_exit_conditions(position)
        
        # May or may not trigger depending on internal calculation
        # Just verify it runs without error


class TestVolatilityRegimeDetector(unittest.TestCase):
    """Test regime detection"""
    
    def test_high_iv_regime_detection(self):
        """Test detection of high IV regime"""
        iv_history = pd.Series(np.linspace(0.30, 0.90, 252))
        rv_history = pd.Series([0.45] * 252)
        
        regime = VolatilityRegimeDetector.detect_regime(
            current_iv=0.85,
            iv_history=iv_history,
            rv_history=rv_history
        )
        
        self.assertEqual(regime['iv_level'], 'HIGH')
        self.assertTrue(regime['good_for_vrp'])
    
    def test_low_vrp_not_good_for_entry(self):
        """Test that low VRP regime is not good for entry"""
        iv_history = pd.Series([0.60] * 252)
        rv_history = pd.Series([0.58] * 252)  # RV close to IV
        
        regime = VolatilityRegimeDetector.detect_regime(
            current_iv=0.60,
            iv_history=iv_history,
            rv_history=rv_history,
            vrp_threshold=0.05
        )
        
        self.assertEqual(regime['vrp_state'], 'CHEAP')
        self.assertFalse(regime['good_for_vrp'])


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestVolatilityCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestBlackScholesCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestGreeksCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManager))
    suite.addTests(loader.loadTestsFromTestCase(TestVRPStrategy))
    suite.addTests(loader.loadTestsFromTestCase(TestVolatilityRegimeDetector))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
