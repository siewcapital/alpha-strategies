"""
Cross-Exchange Funding Rate Arbitrage - Unit Tests
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators import (
    FundingRateCalculator, OpportunityFilter, FundingRate, FundingDifferential
)
from src.signal_generator import SignalGenerator, Signal, SignalType, ExitReason
from src.risk_manager import RiskManager, RiskLimits, PortfolioState, RiskLevel
from src.strategy import FundingArbitrageStrategy, StrategyConfig, PerformanceMetrics


class TestFundingRateCalculator(unittest.TestCase):
    """Test funding rate calculation logic."""
    
    def setUp(self):
        self.calculator = FundingRateCalculator(min_differential=0.0001)
        
    def test_add_funding_data(self):
        """Test adding funding data to history."""
        ts = datetime.now()
        self.calculator.add_funding_data('binance', 'BTCUSDT', ts, 0.0001, 0.00005)
        
        key = 'binance:BTCUSDT'
        self.assertIn(key, self.calculator._funding_history)
        self.assertEqual(len(self.calculator._funding_history[key]), 1)
    
    def test_annualized_rate_calculation(self):
        """Test annualized rate conversion."""
        rate = FundingRate(
            exchange='binance',
            symbol='BTCUSDT',
            funding_rate=0.0001,  # 0.01% per 8 hours
            next_funding_time=datetime.now()
        )
        
        # 0.01% * 3 times/day * 365 days = 10.95%
        expected_annual = 0.0001 * 3 * 365
        self.assertAlmostEqual(rate.annualized_rate, expected_annual, places=6)
    
    def test_calculate_differentials(self):
        """Test differential calculation between exchanges."""
        ts = datetime.now()
        
        rates = {
            'binance': FundingRate('binance', 'BTCUSDT', 0.0003, ts),
            'bybit': FundingRate('bybit', 'BTCUSDT', 0.0001, ts)
        }
        
        opportunities = self.calculator.calculate_differentials(
            'BTCUSDT', ['binance', 'bybit'], rates
        )
        
        self.assertEqual(len(opportunities), 1)
        opp = opportunities[0]
        
        # Should short binance (high funding), long bybit (low funding)
        self.assertEqual(opp.short_exchange, 'binance')
        self.assertEqual(opp.long_exchange, 'bybit')
        self.assertAlmostEqual(opp.differential, 0.0002, places=6)
    
    def test_differential_threshold_filtering(self):
        """Test that small differentials are filtered."""
        ts = datetime.now()
        
        rates = {
            'binance': FundingRate('binance', 'BTCUSDT', 0.00001, ts),
            'bybit': FundingRate('bybit', 'BTCUSDT', 0.000015, ts)
        }
        
        opportunities = self.calculator.calculate_differentials(
            'BTCUSDT', ['binance', 'bybit'], rates
        )
        
        # Differential of 0.000005 is below threshold
        self.assertEqual(len(opportunities), 0)


class TestOpportunityFilter(unittest.TestCase):
    """Test opportunity filtering logic."""
    
    def setUp(self):
        self.filter = OpportunityFilter(
            min_annualized_return=0.05,
            min_confidence=0.6
        )
    
    def test_filter_by_annualized_return(self):
        """Test filtering by minimum annualized return."""
        ts = datetime.now()
        
        opportunities = [
            FundingDifferential(
                symbol='BTCUSDT',
                long_exchange='bybit',
                short_exchange='binance',
                long_funding=0.0001,
                short_funding=0.0003,
                differential=0.0002,  # Small differential
                annualized_diff=0.0,
                opportunity_score=0.0,
                confidence=0.8
            )
        ]
        # Force annualized diff calculation - 0.02% per 8h = 21.9% annual (below 50% threshold)
        opportunities[0].annualized_diff = opportunities[0].differential * 3 * 365
        
        filtered = self.filter.filter_opportunities(opportunities, portfolio_heat=0.0)
        
        # 21.9% annual return is above 5% threshold, should pass
        self.assertEqual(len(filtered), 1)
    
    def test_filter_by_confidence(self):
        """Test filtering by minimum confidence."""
        ts = datetime.now()
        
        opportunities = [
            FundingDifferential(
                symbol='BTCUSDT',
                long_exchange='bybit',
                short_exchange='binance',
                long_funding=0.0001,
                short_funding=0.0005,
                differential=0.0004,
                annualized_diff=0.0,
                opportunity_score=0.0,
                confidence=0.3  # Below threshold
            )
        ]
        opportunities[0].annualized_diff = opportunities[0].differential * 3 * 365
        
        filtered = self.filter.filter_opportunities(opportunities, portfolio_heat=0.0)
        
        # Low confidence should be filtered
        self.assertEqual(len(filtered), 0)
    
    def test_rank_opportunities(self):
        """Test opportunity ranking."""
        opportunities = [
            FundingDifferential(
                symbol='BTCUSDT',
                long_exchange='bybit',
                short_exchange='binance',
                long_funding=0.0001,
                short_funding=0.0003,
                differential=0.0,
                annualized_diff=0.0,
                opportunity_score=0.2,
                confidence=0.8
            ),
            FundingDifferential(
                symbol='ETHUSDT',
                long_exchange='okx',
                short_exchange='binance',
                long_funding=0.0001,
                short_funding=0.0004,
                differential=0.0,
                annualized_diff=0.0,
                opportunity_score=0.5,
                confidence=0.9
            )
        ]
        
        ranked = self.filter.rank_opportunities(opportunities)
        
        # Higher score should be rank 1
        self.assertEqual(ranked[0][0], 1)
        self.assertEqual(ranked[0][1].symbol, 'ETHUSDT')


class TestSignalGenerator(unittest.TestCase):
    """Test signal generation logic."""
    
    def setUp(self):
        self.generator = SignalGenerator(
            entry_threshold=0.0002,
            exit_threshold=0.00005
        )
    
    def test_generate_entry_signal(self):
        """Test entry signal generation."""
        ts = datetime.now()
        
        opportunities = [
            FundingDifferential(
                symbol='BTCUSDT',
                long_exchange='bybit',
                short_exchange='binance',
                long_funding=0.0001,
                short_funding=0.0005,
                differential=0.0,
                annualized_diff=0.0,
                opportunity_score=0.3,
                confidence=0.8
            )
        ]
        opportunities[0].differential = 0.0004
        opportunities[0].annualized_diff = opportunities[0].differential * 3 * 365
        
        signals = self.generator.generate_entry_signals(
            opportunities=opportunities,
            current_time=ts,
            available_capital=100000,
            max_positions=5
        )
        
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, SignalType.ENTER_LONG)
        self.assertEqual(signals[0].symbol, 'BTCUSDT')
    
    def test_generate_exit_on_convergence(self):
        """Test exit signal on funding convergence."""
        ts = datetime.now()
        
        # First register a position
        entry_signal = Signal(
            timestamp=ts - timedelta(hours=16),
            symbol='BTCUSDT',
            signal_type=SignalType.ENTER_LONG,
            long_exchange='bybit',
            short_exchange='binance',
            size_usd=10000,
            confidence=0.8,
            expected_funding_diff=0.0004
        )
        
        self.generator.register_position_entry(entry_signal)
        self.generator._funding_periods_held[f"BTCUSDT:bybit:binance"] = 3
        
        # Simulate converged funding rates
        current_rates = {
            'BTCUSDT': {
                'bybit': FundingRate('bybit', 'BTCUSDT', 0.00025, ts),
                'binance': FundingRate('binance', 'BTCUSDT', 0.00028, ts)
            }
        }
        
        exit_signals = self.generator.generate_exit_signals(
            current_rates=current_rates,
            current_time=ts
        )
        
        # Differential of 0.00003 is below exit threshold
        self.assertEqual(len(exit_signals), 1)
        self.assertEqual(exit_signals[0].exit_reason, ExitReason.FUNDING_CONVERGENCE)
    
    def test_time_stop_exit(self):
        """Test exit after maximum hold time."""
        ts = datetime.now()
        
        entry_signal = Signal(
            timestamp=ts - timedelta(hours=80),  # Exceeds 72h max
            symbol='BTCUSDT',
            signal_type=SignalType.ENTER_LONG,
            long_exchange='bybit',
            short_exchange='binance',
            size_usd=10000,
            confidence=0.8,
            expected_funding_diff=0.0004
        )
        
        self.generator.register_position_entry(entry_signal)
        self.generator._funding_periods_held[f"BTCUSDT:bybit:binance"] = 10
        
        current_rates = {
            'BTCUSDT': {
                'bybit': FundingRate('bybit', 'BTCUSDT', 0.00005, ts),
                'binance': FundingRate('binance', 'BTCUSDT', 0.00045, ts)  # 0.04% diff maintained
            }
        }
        
        exit_signals = self.generator.generate_exit_signals(
            current_rates=current_rates,
            current_time=ts
        )
        
        self.assertEqual(len(exit_signals), 1)
        self.assertEqual(exit_signals[0].exit_reason, ExitReason.TIME_STOP)
    
    def test_position_tracking(self):
        """Test position state tracking."""
        ts = datetime.now()
        
        entry_signal = Signal(
            timestamp=ts,
            symbol='BTCUSDT',
            signal_type=SignalType.ENTER_LONG,
            long_exchange='bybit',
            short_exchange='binance',
            size_usd=10000,
            confidence=0.8,
            expected_funding_diff=0.0004
        )
        
        self.generator.register_position_entry(entry_signal)
        
        positions = self.generator.get_active_positions()
        self.assertEqual(len(positions), 1)
        
        position_key = 'BTCUSDT:bybit:binance'
        self.assertIn(position_key, positions)


class TestRiskManager(unittest.TestCase):
    """Test risk management logic."""
    
    def setUp(self):
        self.limits = RiskLimits(
            max_position_size_usd=50000,
            max_total_exposure_usd=200000,
            max_total_positions=5
        )
        self.risk_manager = RiskManager(self.limits)
    
    def test_kelly_criterion(self):
        """Test Kelly Criterion position sizing."""
        confidence = 0.7
        kelly_fraction = self.risk_manager._kelly_criterion(confidence)
        
        # Kelly should be positive for confidence > 0.5
        self.assertGreater(kelly_fraction, 0)
        # Half-Kelly should be capped at 0.5
        self.assertLessEqual(kelly_fraction, 0.5)
    
    def test_position_size_limits(self):
        """Test that position sizes respect limits."""
        size, risk_level, warnings = self.risk_manager.calculate_position_size(
            opportunity_score=0.5,
            confidence=0.8,
            funding_differential=0.0004,
            symbol='BTCUSDT',
            long_exchange='bybit',
            short_exchange='binance',
            base_size=60000  # Above max
        )
        
        # Should be capped at max_position_size_usd
        self.assertLessEqual(size, self.limits.max_position_size_usd)
    
    def test_entry_permissions(self):
        """Test entry permission checks."""
        # Test max positions limit
        self.risk_manager.state.positions_by_symbol = {
            'BTC': [{}, {}],
            'ETH': [{}, {}],
            'SOL': [{}]
        }
        
        permitted, reasons = self.risk_manager.check_entry_permissions(
            'BTC', 'bybit', 'binance', 10000
        )
        
        # Should have 5 positions, at limit
        self.assertFalse(permitted)
    
    def test_circuit_breaker_daily_loss(self):
        """Test circuit breaker on daily loss."""
        self.risk_manager.state.daily_pnl = -6000  # Above 5000 limit
        self.risk_manager._check_circuit_breakers()
        
        self.assertTrue(self.risk_manager._circuit_breaker_triggered)
        
        # Should block new entries
        permitted, _ = self.risk_manager.check_entry_permissions(
            'BTC', 'bybit', 'binance', 10000
        )
        self.assertFalse(permitted)
    
    def test_drawdown_size_reduction(self):
        """Test position size reduction during drawdown."""
        self.risk_manager.state.peak_equity = 100000
        self.risk_manager.state.total_equity = 92000  # 8% drawdown
        
        reduction = self.risk_manager._drawdown_size_reduction()
        
        # Should reduce size during drawdown
        self.assertLess(reduction, 1.0)
        self.assertGreaterEqual(reduction, 0.1)  # Minimum 10%
    
    def test_liquidation_buffer_calculation(self):
        """Test liquidation distance calculation."""
        entry_price = 50000
        leverage = 2.0
        
        liq_price = self.risk_manager.calculate_liquidation_price(
            entry_price, leverage, is_long=True
        )
        
        # Long liquidation should be below entry
        self.assertLess(liq_price, entry_price)
        
        buffer = self.risk_manager.calculate_liquidation_buffer(
            current_price=50000,
            liquidation_price=liq_price,
            is_long=True
        )
        
        # Buffer should be positive
        self.assertGreater(buffer, 0)


class TestStrategyIntegration(unittest.TestCase):
    """Integration tests for full strategy."""
    
    def setUp(self):
        self.config = StrategyConfig(
            entry_threshold=0.0002,
            exit_threshold=0.0001,
            max_positions=3,
            symbols=['BTCUSDT'],
            exchanges=['binance', 'bybit']
        )
        
        self.risk_limits = RiskLimits(
            max_position_size_usd=50000,
            max_total_exposure_usd=150000
        )
        
        self.strategy = FundingArbitrageStrategy(
            config=self.config,
            risk_limits=self.risk_limits
        )
    
    def test_strategy_initialization(self):
        """Test strategy initialization."""
        self.assertEqual(self.strategy.state.value, 'initialized')
        self.assertIsNotNone(self.strategy.calculator)
        self.assertIsNotNone(self.strategy.signal_generator)
        self.assertIsNotNone(self.strategy.risk_manager)
    
    def test_funding_data_processing(self):
        """Test funding data processing."""
        ts = datetime.now()
        
        self.strategy.process_funding_update(
            exchange='binance',
            symbol='BTCUSDT',
            funding_rate=0.0003,
            timestamp=ts,
            premium_index=0.00025
        )
        
        self.assertIn('BTCUSDT', self.strategy.current_rates)
        self.assertIn('binance', self.strategy.current_rates['BTCUSDT'])
    
    def test_strategy_lifecycle(self):
        """Test strategy start/stop lifecycle."""
        self.strategy.start()
        self.assertEqual(self.strategy.state.value, 'running')
        
        self.strategy.pause()
        self.assertEqual(self.strategy.state.value, 'paused')
        
        self.strategy.start()
        self.assertEqual(self.strategy.state.value, 'running')
        
        self.strategy.stop()
        self.assertEqual(self.strategy.state.value, 'shutdown')
    
    def test_performance_metrics(self):
        """Test performance metrics calculation."""
        # Simulate some trades
        trades = [
            {
                'total_pnl': 100,
                'duration_hours': 8,
                'funding_earned': 150,
                'exit_reason': 'funding_convergence'
            },
            {
                'total_pnl': -50,
                'duration_hours': 16,
                'funding_earned': 80,
                'exit_reason': 'stop_loss'
            },
            {
                'total_pnl': 200,
                'duration_hours': 24,
                'funding_earned': 250,
                'exit_reason': 'profit_target'
            }
        ]
        
        self.strategy.performance.update_from_trades(trades)
        
        self.assertEqual(self.strategy.performance.total_trades, 3)
        self.assertEqual(self.strategy.performance.winning_trades, 2)
        self.assertEqual(self.strategy.performance.losing_trades, 1)
        self.assertAlmostEqual(self.strategy.performance.win_rate, 2/3, places=4)
        self.assertEqual(self.strategy.performance.net_profit, 250)


class TestPerformanceMetrics(unittest.TestCase):
    """Test performance metrics calculations."""
    
    def test_empty_trades(self):
        """Test metrics with no trades."""
        metrics = PerformanceMetrics()
        metrics.update_from_trades([])
        
        self.assertEqual(metrics.total_trades, 0)
        self.assertEqual(metrics.win_rate, 0)
    
    def test_win_rate_calculation(self):
        """Test win rate calculation."""
        metrics = PerformanceMetrics()
        
        trades = [
            {'total_pnl': 100},
            {'total_pnl': 200},
            {'total_pnl': -50},
            {'total_pnl': 0}  # Breakeven counts as loss
        ]
        
        metrics.update_from_trades(trades)
        
        self.assertEqual(metrics.total_trades, 4)
        self.assertEqual(metrics.winning_trades, 2)
        self.assertEqual(metrics.losing_trades, 2)
        self.assertEqual(metrics.win_rate, 0.5)
    
    def test_profit_factor(self):
        """Test profit factor calculation."""
        metrics = PerformanceMetrics()
        
        trades = [
            {'total_pnl': 300},
            {'total_pnl': 200},
            {'total_pnl': -100},
            {'total_pnl': -50}
        ]
        
        metrics.update_from_trades(trades)
        
        # Gross profit = 500, Gross loss = 150
        expected_pf = 500 / 150
        self.assertAlmostEqual(metrics.profit_factor, expected_pf, places=4)
    
    def test_average_hold_time(self):
        """Test average hold time calculation."""
        metrics = PerformanceMetrics()
        
        trades = [
            {'total_pnl': 100, 'duration_hours': 8},
            {'total_pnl': 200, 'duration_hours': 16},
            {'total_pnl': -50, 'duration_hours': 24}
        ]
        
        metrics.update_from_trades(trades)
        
        expected_avg = (8 + 16 + 24) / 3
        self.assertEqual(metrics.avg_hold_time_hours, expected_avg)


if __name__ == '__main__':
    unittest.main(verbosity=2)
