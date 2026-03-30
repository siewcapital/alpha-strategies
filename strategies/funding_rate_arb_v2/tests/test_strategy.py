"""
Test Suite for Funding Rate Arbitrage Strategy

Tests for FundingAnalyzer, SignalGenerator, RiskManager, and integration.

Author: ATLAS
Date: March 30, 2026
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "backtest"))

import unittest
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from strategy import (
    FundingAnalyzer, SignalGenerator, RiskManager, FundingArbitrageStrategy,
    FundingPrediction, FundingOpportunity, Signal, Position, Portfolio,
    SignalType, PositionSide
)


class TestFundingAnalyzer(unittest.TestCase):
    """Tests for FundingAnalyzer class."""
    
    def setUp(self):
        self.analyzer = FundingAnalyzer(lookback_window=30, min_observations=5)
    
    def test_update_funding_history(self):
        """Test funding history updates."""
        self.analyzer.update_funding_history(
            "binance", "BTCUSDT", datetime(2024, 1, 1), 0.0001
        )
        
        key = ("binance", "BTCUSDT")
        self.assertIn(key, self.analyzer.funding_history)
        self.assertEqual(len(self.analyzer.funding_history[key]), 1)
    
    def test_calculate_persistence(self):
        """Test persistence calculation."""
        # Create synthetic AR(1) series with known persistence
        np.random.seed(42)
        n = 100
        phi = 0.8  # AR(1) coefficient
        series = np.zeros(n)
        series[0] = np.random.normal()
        
        for t in range(1, n):
            series[t] = phi * series[t-1] + np.random.normal(0, 0.1)
        
        funding_series = pd.Series(series, index=pd.date_range('2024-01-01', periods=n, freq='8H'))
        persistence = self.analyzer.calculate_persistence(funding_series)
        
        # Persistence should be close to phi (allowing for estimation error)
        self.assertGreater(persistence, 0.5)
        self.assertLess(persistence, 1.0)
    
    def test_predict_funding_rate_insufficient_data(self):
        """Test prediction with insufficient data."""
        pred = self.analyzer.predict_funding_rate("binance", "BTCUSDT")
        
        self.assertEqual(pred.exchange, "binance")
        self.assertEqual(pred.symbol, "BTCUSDT")
        self.assertEqual(pred.predicted_rate, 0.0)  # Default
        self.assertEqual(pred.confidence, 0.3)  # Low confidence
    
    def test_predict_funding_rate_with_history(self):
        """Test prediction with sufficient history."""
        # Add synthetic history
        np.random.seed(42)
        base_rate = 0.0001
        
        for i in range(20):
            rate = base_rate + np.random.normal(0, 0.0001)
            self.analyzer.update_funding_history(
                "binance", "BTCUSDT",
                datetime(2024, 1, 1) + timedelta(hours=8*i),
                rate
            )
        
        pred = self.analyzer.predict_funding_rate("binance", "BTCUSDT")
        
        self.assertIsNotNone(pred.predicted_rate)
        self.assertGreater(pred.confidence, 0.3)
        self.assertGreaterEqual(pred.persistence_score, 0)
        self.assertLessEqual(pred.persistence_score, 1)
    
    def test_calculate_cross_exchange_spread(self):
        """Test cross-exchange spread calculation."""
        predictions = [
            FundingPrediction("binance", "BTCUSDT", 0.0001, 0.8, 0.7, datetime.now()),
            FundingPrediction("bybit", "BTCUSDT", 0.0004, 0.8, 0.7, datetime.now()),
            FundingPrediction("binance", "ETHUSDT", 0.0002, 0.8, 0.7, datetime.now()),
            FundingPrediction("bybit", "ETHUSDT", 0.0002, 0.8, 0.7, datetime.now()),
        ]
        
        opportunities = self.analyzer.calculate_cross_exchange_spread(
            predictions, min_annualized_spread=0.15
        )
        
        # Should find BTC opportunity (spread = 0.0003 * 3 * 365 = 32.85%)
        self.assertGreater(len(opportunities), 0)
        
        # Check BTC opportunity
        btc_opps = [o for o in opportunities if o.symbol == "BTCUSDT"]
        self.assertEqual(len(btc_opps), 1)
        self.assertGreater(btc_opps[0].spread_annualized, 0.15)


class TestSignalGenerator(unittest.TestCase):
    """Tests for SignalGenerator class."""
    
    def setUp(self):
        self.config = {
            "entry_threshold": 0.15,
            "exit_threshold": 0.05,
            "min_persistence": 0.7,
            "max_positions": 3,
            "max_position_usd": 50000,
            "min_position_usd": 5000,
            "default_leverage": 2.0,
            "max_utilization": 0.5,
            "max_hold_hours": 48,
            "flip_threshold": 0.3
        }
        self.generator = SignalGenerator(self.config)
    
    def test_check_entry_criteria_spread_threshold(self):
        """Test entry criteria with spread threshold."""
        opp = FundingOpportunity(
            symbol="BTCUSDT",
            long_exchange="binance",
            short_exchange="bybit",
            long_funding=FundingPrediction("binance", "BTCUSDT", 0.0001, 0.8, 0.8, datetime.now()),
            short_funding=FundingPrediction("bybit", "BTCUSDT", 0.00015, 0.8, 0.8, datetime.now()),
            spread_annualized=0.05,  # Below threshold
            entry_threshold_met=False,
            timestamp=datetime.now()
        )
        
        result = self.generator._check_entry_criteria(opp)
        self.assertFalse(result)  # Below entry threshold
    
    def test_check_entry_criteria_persistence(self):
        """Test entry criteria with persistence check."""
        opp = FundingOpportunity(
            symbol="BTCUSDT",
            long_exchange="binance",
            short_exchange="bybit",
            long_funding=FundingPrediction("binance", "BTCUSDT", 0.0001, 0.8, 0.5, datetime.now()),
            short_funding=FundingPrediction("bybit", "BTCUSDT", 0.0003, 0.8, 0.5, datetime.now()),
            spread_annualized=0.20,  # Above threshold
            entry_threshold_met=True,
            timestamp=datetime.now()
        )
        
        result = self.generator._check_entry_criteria(opp)
        self.assertFalse(result)  # Persistence too low
    
    def test_calculate_position_size(self):
        """Test position size calculation."""
        opp = FundingOpportunity(
            symbol="BTCUSDT",
            long_exchange="binance",
            short_exchange="bybit",
            long_funding=FundingPrediction("binance", "BTCUSDT", 0.0001, 0.8, 0.8, datetime.now()),
            short_funding=FundingPrediction("bybit", "BTCUSDT", 0.0003, 0.8, 0.8, datetime.now()),
            spread_annualized=0.20,
            entry_threshold_met=True,
            timestamp=datetime.now()
        )
        
        portfolio = Portfolio(cash=100000)
        
        size = self.generator._calculate_position_size(opp, portfolio)
        
        self.assertGreaterEqual(size, self.config["min_position_usd"])
        self.assertLessEqual(size, self.config["max_position_usd"])
    
    def test_estimate_flip_risk(self):
        """Test funding flip risk estimation."""
        opp = FundingOpportunity(
            symbol="BTCUSDT",
            long_exchange="binance",
            short_exchange="bybit",
            long_funding=FundingPrediction("binance", "BTCUSDT", -0.001, 0.8, 0.8, datetime.now()),
            short_funding=FundingPrediction("bybit", "BTCUSDT", 0.0003, 0.8, 0.8, datetime.now()),
            spread_annualized=0.50,
            entry_threshold_met=True,
            timestamp=datetime.now()
        )
        
        flip_risk = self.generator._estimate_flip_risk(opp)
        
        # Long funding is negative (-0.1%), so low flip risk
        self.assertLess(flip_risk, 0.5)


class TestRiskManager(unittest.TestCase):
    """Tests for RiskManager class."""
    
    def setUp(self):
        self.config = {
            "max_drawdown": 0.10,
            "daily_loss_limit": 0.03,
            "max_consecutive_losses": 3
        }
        self.manager = RiskManager(self.config)
    
    def test_check_risk_limits_normal(self):
        """Test risk limits in normal conditions."""
        portfolio = Portfolio(cash=100000, total_pnl=1000)
        
        status = self.manager.check_risk_limits(portfolio)
        
        self.assertTrue(status["can_trade"])
        self.assertFalse(status["circuit_breaker"])
    
    def test_check_risk_limits_drawdown(self):
        """Test risk limits with drawdown."""
        self.manager.peak_value = 100000
        portfolio = Portfolio(cash=85000, total_pnl=-15000)  # 15% drawdown
        
        status = self.manager.check_risk_limits(portfolio)
        
        self.assertFalse(status["can_trade"])
        self.assertTrue(status["circuit_breaker"])
    
    def test_record_trade_result_consecutive_losses(self):
        """Test consecutive loss tracking."""
        # Record 3 losses
        for _ in range(3):
            self.manager.record_trade_result(-100)
        
        self.assertEqual(self.manager.consecutive_losses, 3)
        
        # Record a win
        self.manager.record_trade_result(100)
        self.assertEqual(self.manager.consecutive_losses, 0)


class TestIntegration(unittest.TestCase):
    """Integration tests for the full strategy."""
    
    def setUp(self):
        self.config = {
            "initial_capital": 100000,
            "entry_threshold": 0.15,
            "exit_threshold": 0.05,
            "min_persistence": 0.7,
            "max_positions": 5,
            "max_position_usd": 50000,
            "min_position_usd": 5000,
            "default_leverage": 2.0,
            "max_utilization": 0.5,
            "max_hold_hours": 48,
            "lookback_window": 30
        }
        self.strategy = FundingArbitrageStrategy(config=self.config)
    
    def test_full_cycle(self):
        """Test a full strategy cycle."""
        # Simulate funding data
        funding_data = []
        base_time = datetime(2024, 1, 1)
        
        # Generate 20 periods of data
        for i in range(20):
            timestamp = base_time + timedelta(hours=8*i)
            
            # BTC: Binance lower funding than Bybit
            funding_data.append({
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "timestamp": timestamp.isoformat(),
                "funding_rate": 0.0001 if i < 10 else 0.0002
            })
            funding_data.append({
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "timestamp": timestamp.isoformat(),
                "funding_rate": 0.0003 if i < 10 else 0.00015
            })
            
            # ETH: No spread
            funding_data.append({
                "exchange": "binance",
                "symbol": "ETHUSDT",
                "timestamp": timestamp.isoformat(),
                "funding_rate": 0.0001
            })
            funding_data.append({
                "exchange": "bybit",
                "symbol": "ETHUSDT",
                "timestamp": timestamp.isoformat(),
                "funding_rate": 0.0001
            })
        
        # Run cycle
        result = self.strategy.run_cycle(
            funding_data=funding_data,
            exchanges=["binance", "bybit"],
            symbols=["BTCUSDT", "ETHUSDT"]
        )
        
        self.assertIn("predictions_count", result)
        self.assertIn("signals_generated", result)
        self.assertGreater(result["predictions_count"], 0)


class TestBacktestEngine(unittest.TestCase):
    """Tests for backtest engine."""
    
    def setUp(self):
        from backtest_engine import BacktestConfig, BacktestEngine
        
        self.config = BacktestConfig(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            initial_capital=100000
        )
        self.engine = BacktestEngine(self.config)
    
    def test_generate_synthetic_data(self):
        """Test synthetic data generation."""
        df = self.engine.generate_synthetic_data(
            exchanges=["binance", "bybit"],
            symbols=["BTCUSDT"],
            days=30
        )
        
        self.assertGreater(len(df), 0)
        self.assertIn("timestamp", df.columns)
        self.assertIn("exchange", df.columns)
        self.assertIn("symbol", df.columns)
        self.assertIn("funding_rate", df.columns)
    
    def test_calculate_execution_cost(self):
        """Test execution cost calculation."""
        cost, fees = self.engine._calculate_execution_cost(10000, use_maker=True)
        
        expected_fees = 10000 * 0.0002  # maker fee
        expected_slippage = 10000 * 0.0002  # 2 bps
        
        self.assertAlmostEqual(fees, expected_fees)
        self.assertAlmostEqual(cost, expected_fees + expected_slippage)


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestFundingAnalyzer))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestBacktestEngine))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
