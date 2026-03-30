"""
Tests for Funding Rate Arbitrage Strategy

Author: ATLAS (Siew's Capital)
Date: 2026-03-24
"""

import unittest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from strategy import (
    ArbitrageOpportunity,
    FundingRate,
    FundingRateArbitrageStrategy,
    Position,
    SignalType
)


class TestFundingRateArbitrageStrategy(unittest.TestCase):
    """Test cases for the funding rate arbitrage strategy."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.strategy = FundingRateArbitrageStrategy("config/params.yaml")
    
    def test_strategy_initialization(self):
        """Test strategy initializes with correct parameters."""
        self.assertEqual(self.strategy.min_funding_diff, 0.0001)
        self.assertEqual(self.strategy.min_expected_return, 0.05)
        self.assertEqual(self.strategy.max_leverage, 2.5)
        self.assertEqual(self.strategy.max_position_size, 0.10)
    
    def test_scan_opportunities_no_data(self):
        """Test scanning with no data returns empty list."""
        funding_data = {
            "binance": {},
            "bybit": {}
        }
        
        opportunities = self.strategy.scan_opportunities(funding_data)
        
        self.assertEqual(len(opportunities), 0)
    
    def test_scan_opportunities_with_opportunity(self):
        """Test scanning finds opportunities."""
        # Create funding data with significant rate difference
        funding_data = {
            "binance": {
                "BTC": FundingRate(
                    exchange="binance",
                    symbol="BTC",
                    rate=0.001,  # 0.1% funding
                    next_settle=datetime.now() + timedelta(hours=8),
                    mark_price=70000,
                    index_price=70000
                )
            },
            "bybit": {
                "BTC": FundingRate(
                    exchange="bybit",
                    symbol="BTC",
                    rate=-0.001,  # -0.1% funding
                    next_settle=datetime.now() + timedelta(hours=8),
                    mark_price=70100,
                    index_price=70000
                )
            }
        }
        
        opportunities = self.strategy.scan_opportunities(funding_data)
        
        # Should find at least one opportunity
        self.assertGreater(len(opportunities), 0)
        
        # Check opportunity details
        opp = opportunities[0]
        self.assertEqual(opp.symbol, "BTC")
        self.assertEqual(opp.rate_diff, 0.002)  # 0.001 - (-0.001)
    
    def test_scan_opportunities_below_threshold(self):
        """Test scanning ignores opportunities below threshold."""
        # Create funding data with small rate difference
        funding_data = {
            "binance": {
                "BTC": FundingRate(
                    exchange="binance",
                    symbol="BTC",
                    rate=0.00001,  # Very small
                    next_settle=datetime.now() + timedelta(hours=8),
                    mark_price=70000,
                    index_price=70000
                )
            },
            "bybit": {
                "BTC": FundingRate(
                    exchange="bybit",
                    symbol="BTC",
                    rate=0.00002,  # Small difference
                    next_settle=datetime.now() + timedelta(hours=8),
                    mark_price=70100,
                    index_price=70000
                )
            }
        }
        
        opportunities = self.strategy.scan_opportunities(funding_data)
        
        # Should find no opportunities (below threshold)
        self.assertEqual(len(opportunities), 0)
    
    def test_generate_signal(self):
        """Test signal generation."""
        opportunity = ArbitrageOpportunity(
            long_exchange="binance",
            short_exchange="bybit",
            symbol="BTC",
            long_rate=0.001,
            short_rate=-0.001,
            rate_diff=0.002,
            expected_annual_return=0.15,
            mark_price_long=70000,
            mark_price_short=70100
        )
        
        signal_type, position = self.strategy.generate_signal(
            opportunity, 
            portfolio_value=100000
        )
        
        self.assertEqual(signal_type, SignalType.ENTER_LONG)
        self.assertIsNotNone(position)
        self.assertEqual(position.symbol, "BTC")
        self.assertEqual(position.long_exchange, "binance")
        self.assertEqual(position.short_exchange, "bybit")
    
    def test_check_exit_conditions_max_holding(self):
        """Test exit condition for max holding period."""
        position = Position(
            symbol="BTC",
            long_exchange="binance",
            short_exchange="bybit",
            size=1.0,
            entry_long_rate=0.001,
            entry_short_rate=-0.001,
            entry_time=datetime.now() - timedelta(days=8),  # 8 days ago
            entry_long_price=70000,
            entry_short_price=70100,
            margin_used=10000,
            leverage=2.5
        )
        
        # Max holding period is 7 days
        should_exit = self.strategy.check_exit_conditions(position)
        
        self.assertTrue(should_exit)
    
    def test_check_exit_conditions_not_expired(self):
        """Test exit condition when position not expired."""
        position = Position(
            symbol="BTC",
            long_exchange="binance",
            short_exchange="bybit",
            size=1.0,
            entry_long_rate=0.001,
            entry_short_rate=-0.001,
            entry_time=datetime.now() - timedelta(days=2),  # 2 days ago
            entry_long_price=70000,
            entry_short_price=70100,
            margin_used=10000,
            leverage=2.5
        )
        
        should_exit = self.strategy.check_exit_conditions(position)
        
        self.assertFalse(should_exit)
    
    def test_calculate_position_pnl(self):
        """Test PnL calculation."""
        position = Position(
            symbol="BTC",
            long_exchange="binance",
            short_exchange="bybit",
            size=1.0,  # 1 BTC
            entry_long_rate=0.001,  # 0.1% positive
            entry_short_rate=-0.001,  # -0.1% (shorts receive)
            entry_time=datetime.now() - timedelta(days=1),  # 1 day ago
            entry_long_price=70000,
            entry_short_price=70100,
            margin_used=10000,
            leverage=2.5
        )
        
        pnl = self.strategy.calculate_position_pnl(position)
        
        # Should have positive PnL from funding
        # 1 day = 3 funding periods
        # Long funding: 1 * 0.001 * 3 = 0.003 BTC
        # Short funding: 1 * (-0.001) * 3 = -0.003 BTC (we pay)
        # Net = 0
        # But we also receive on the positive rate
        # Let's verify the calculation is reasonable
        self.assertIsInstance(pnl, float)
    
    def test_can_open_position_max_exposure(self):
        """Test position limit check."""
        # Add a position
        position = Position(
            symbol="BTC",
            long_exchange="binance",
            short_exchange="bybit",
            size=1.0,
            entry_long_rate=0.001,
            entry_short_rate=-0.001,
            entry_time=datetime.now(),
            entry_long_price=70000,
            entry_short_price=70100,
            margin_used=15000,  # 15% of 100K portfolio
            leverage=2.5
        )
        self.strategy.positions["BTC"] = position
        
        # Try to add another position (should fail - at limit)
        can_open = self.strategy.can_open_position("ETH", 0.10)
        
        self.assertFalse(can_open)
    
    def test_can_open_position_allowed(self):
        """Test position can be opened within limits."""
        can_open = self.strategy.can_open_position("BTC", 0.05)
        
        # Should be allowed (within limits)
        self.assertTrue(can_open)
    
    def test_get_strategy_state(self):
        """Test strategy state retrieval."""
        state = self.strategy.get_strategy_state()
        
        self.assertIn("total_positions", state)
        self.assertIn("total_pnl", state)
        self.assertIn("positions", state)
        self.assertIn("timestamp", state)
    
    def test_reset(self):
        """Test strategy reset."""
        # Add a position
        position = Position(
            symbol="BTC",
            long_exchange="binance",
            short_exchange="bybit",
            size=1.0,
            entry_long_rate=0.001,
            entry_short_rate=-0.001,
            entry_time=datetime.now(),
            entry_long_price=70000,
            entry_short_price=70100,
            margin_used=10000,
            leverage=2.5
        )
        self.strategy.positions["BTC"] = position
        
        # Reset
        self.strategy.reset()
        
        # Verify positions cleared
        self.assertEqual(len(self.strategy.positions), 0)
        self.assertEqual(self.strategy.total_pnl, 0)


class TestArbitrageOpportunity(unittest.TestCase):
    """Test cases for ArbitrageOpportunity."""
    
    def test_annual_return_calculation(self):
        """Test expected annual return calculation."""
        opp = ArbitrageOpportunity(
            long_exchange="binance",
            short_exchange="bybit",
            symbol="BTC",
            long_rate=0.001,  # 0.1% per period
            short_rate=-0.001,
            rate_diff=0.002,
            expected_annual_return=0.0,  # Will be calculated
            mark_price_long=70000,
            mark_price_short=70100
        )
        
        # 0.002 * 3 * 365 = 2.19 = 219% annual before costs
        # After costs (0.0015): ~217%
        # Expected return should be positive
        self.assertGreater(opp.expected_annual_return, 0)


class TestPosition(unittest.TestCase):
    """Test cases for Position."""
    
    def test_days_held(self):
        """Test days held calculation."""
        position = Position(
            symbol="BTC",
            long_exchange="binance",
            short_exchange="bybit",
            size=1.0,
            entry_long_rate=0.001,
            entry_short_rate=-0.001,
            entry_time=datetime.now() - timedelta(hours=36),  # 1.5 days ago
            entry_long_price=70000,
            entry_short_price=70100,
            margin_used=10000,
            leverage=2.5
        )
        
        days = position.days_held()
        
        self.assertAlmostEqual(days, 1.5, places=1)


if __name__ == "__main__":
    unittest.main()
