"""
Unit tests for Order Book Imbalance Strategy

Author: ATLAS Alpha Hunter
Date: 2026-03-16
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '/Users/siewbrayden/.openclaw/agents/atlas/workspace/obi_microstructure_strategy')

from src.strategy import (
    OrderBookImbalanceStrategy, OrderBookSnapshot, OrderBookLevel,
    SignalType, TradeSignal, OrderSide
)
from src.indicators import (
    calculate_ema, calculate_rsi, calculate_order_book_slope,
    OrderBookPressureIndex, calculate_microprice
)
from src.signal_generator import SignalGenerator
from src.risk_manager import RiskManager, RiskStatus


class TestOrderBookImbalanceStrategy(unittest.TestCase):
    """Test cases for main strategy."""
    
    def setUp(self):
        self.config = {
            'obi_long_threshold': 0.4,
            'obi_short_threshold': -0.4,
            'obi_depth_threshold': 0.3,
            'persistence_ticks': 3,
            'spread_max_bps': 5.0,
            'vol_velocity_threshold': 0.5,
            'max_holding_seconds': 30,
            'profit_target_bps': 5.0,
            'stop_loss_bps': 3.0,
            'micro_ema_span': 50
        }
        self.strategy = OrderBookImbalanceStrategy(self.config)
    
    def create_book(self, bid_vol: float, ask_vol: float, 
                   price: float = 50000.0) -> OrderBookSnapshot:
        """Helper to create order book."""
        bids = [OrderBookLevel(price=price-0.1, volume=bid_vol, side=OrderSide.BID)]
        asks = [OrderBookLevel(price=price+0.1, volume=ask_vol, side=OrderSide.ASK)]
        
        return OrderBookSnapshot(
            timestamp=pd.Timestamp.now(),
            bids=bids,
            asks=asks,
            mid_price=price,
            spread=0.2
        )
    
    def test_obi_calculation(self):
        """Test OBI calculation."""
        # Balanced book
        book = self.create_book(100, 100)
        obi = self.strategy.calculate_obi_level1(book)
        self.assertAlmostEqual(obi, 0.0, places=5)
        
        # Bid-heavy book
        book = self.create_book(200, 50)
        obi = self.strategy.calculate_obi_level1(book)
        self.assertGreater(obi, 0.5)
        
        # Ask-heavy book
        book = self.create_book(50, 200)
        obi = self.strategy.calculate_obi_level1(book)
        self.assertLess(obi, -0.5)
    
    def test_obi_bounds(self):
        """Test OBI is always in [-1, 1]."""
        for bid_vol in [1, 10, 100, 1000]:
            for ask_vol in [1, 10, 100, 1000]:
                book = self.create_book(bid_vol, ask_vol)
                obi = self.strategy.calculate_obi_level1(book)
                self.assertGreaterEqual(obi, -1.0)
                self.assertLessEqual(obi, 1.0)
    
    def test_depth_weighted_obi(self):
        """Test depth-weighted OBI calculation."""
        bids = [
            OrderBookLevel(price=49999.9, volume=200, side=OrderSide.BID),
            OrderBookLevel(price=49999.8, volume=100, side=OrderSide.BID),
            OrderBookLevel(price=49999.7, volume=50, side=OrderSide.BID),
        ]
        asks = [
            OrderBookLevel(price=50000.1, volume=100, side=OrderSide.ASK),
            OrderBookLevel(price=50000.2, volume=100, side=OrderSide.ASK),
            OrderBookLevel(price=50000.3, volume=100, side=OrderSide.ASK),
        ]
        
        book = OrderBookSnapshot(
            timestamp=pd.Timestamp.now(),
            bids=bids,
            asks=asks,
            mid_price=50000.0,
            spread=0.2
        )
        
        obi_depth = self.strategy.calculate_obi_depth(book, levels=3)
        # Should be positive (bid-heavy at L1)
        self.assertGreater(obi_depth, 0)
    
    def test_signal_generation_long(self):
        """Test long signal generation."""
        # Build up bid-heavy signals
        for i in range(5):
            book = self.create_book(200, 50, price=50000.0 + i * 10)
            book.timestamp = pd.Timestamp.now() + pd.Timedelta(milliseconds=i*100)
            
            self.strategy.volume_history.append(1.0)
            signal = self.strategy.generate_signal(book, trade_volume=1.0)
        
        # Should generate long signal after persistence
        self.assertIsNotNone(signal)
        if signal:
            self.assertEqual(signal.signal_type, SignalType.LONG)
            self.assertGreater(signal.confidence, 0)
    
    def test_signal_generation_short(self):
        """Test short signal generation."""
        self.strategy.reset()
        
        # Build up ask-heavy signals
        for i in range(5):
            book = self.create_book(50, 200, price=50000.0 - i * 10)
            book.timestamp = pd.Timestamp.now() + pd.Timedelta(milliseconds=i*100)
            
            self.strategy.volume_history.append(1.0)
            signal = self.strategy.generate_signal(book, trade_volume=1.0)
        
        # Should generate short signal after persistence
        self.assertIsNotNone(signal)
        if signal:
            self.assertEqual(signal.signal_type, SignalType.SHORT)
    
    def test_spoofing_detection(self):
        """Test spoofing detection."""
        # Create oscillating OBI pattern
        obi_history = [0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.5, -0.5]
        detected = self.strategy.detect_spoofing(obi_history)
        self.assertTrue(detected)
        
        # Create stable OBI pattern
        obi_history = [0.5, 0.52, 0.48, 0.51, 0.49, 0.50, 0.52, 0.48, 0.51, 0.49]
        detected = self.strategy.detect_spoofing(obi_history)
        self.assertFalse(detected)
    
    def test_exit_conditions(self):
        """Test position exit logic."""
        entry_time = pd.Timestamp.now()
        entry_price = 50000.0
        
        # Test time exit
        current_time = entry_time + pd.Timedelta(seconds=35)
        should_exit, reason = self.strategy.should_exit(
            current_price=50100.0,
            entry_price=entry_price,
            entry_time=entry_time,
            current_time=current_time,
            current_obi=0.5
        )
        self.assertTrue(should_exit)
        self.assertEqual(reason, "time_exit")
        
        # Test stop loss
        current_time = entry_time + pd.Timedelta(seconds=10)
        should_exit, reason = self.strategy.should_exit(
            current_price=49850.0,  # -0.3%
            entry_price=entry_price,
            entry_time=entry_time,
            current_time=current_time,
            current_obi=0.5
        )
        self.assertTrue(should_exit)
        self.assertEqual(reason, "stop_loss")
        
        # Test OBI reversal
        should_exit, reason = self.strategy.should_exit(
            current_price=50050.0,
            entry_price=entry_price,
            entry_time=entry_time,
            current_time=current_time,
            current_obi=-0.1  # Flipped negative
        )
        self.assertTrue(should_exit)
        self.assertEqual(reason, "obi_reversal")


class TestIndicators(unittest.TestCase):
    """Test cases for indicators module."""
    
    def test_ema_calculation(self):
        """Test EMA calculation."""
        prices = pd.Series([100, 101, 102, 101, 100, 99, 100, 101, 102, 103])
        ema = calculate_ema(prices, span=3)
        
        # EMA should be smoother than price
        self.assertEqual(len(ema), len(prices))
        self.assertGreater(ema.iloc[-1], ema.iloc[0])  # Overall uptrend
    
    def test_rsi_calculation(self):
        """Test RSI calculation."""
        # Strong uptrend
        prices = pd.Series([100 + i for i in range(20)])
        rsi = calculate_rsi(prices)
        self.assertGreater(rsi.iloc[-1], 50)  # Should be bullish
        
        # Strong downtrend
        prices = pd.Series([120 - i for i in range(20)])
        rsi = calculate_rsi(prices)
        self.assertLess(rsi.iloc[-1], 50)  # Should be bearish
    
    def test_rsi_bounds(self):
        """Test RSI is always in [0, 100]."""
        prices = pd.Series(np.random.randn(100).cumsum() + 100)
        rsi = calculate_rsi(prices, period=14)
        
        self.assertTrue((rsi >= 0).all())
        self.assertTrue((rsi <= 100).all())
    
    def test_microprice_calculation(self):
        """Test microprice calculation."""
        # Balanced book
        mp = calculate_microprice(100.0, 100.2, 100, 100)
        self.assertAlmostEqual(mp, 100.1, places=1)
        
        # Bid-heavy book (more weight to ask)
        mp = calculate_microprice(100.0, 100.2, 200, 100)
        self.assertGreater(mp, 100.1)
        
        # Ask-heavy book (more weight to bid)
        mp = calculate_microprice(100.0, 100.2, 100, 200)
        self.assertLess(mp, 100.1)
    
    def test_order_book_slope(self):
        """Test order book slope calculation."""
        # Steep bid curve, flat ask curve
        bid_vols = [200, 100, 50, 25, 10]
        ask_vols = [100, 90, 80, 70, 60]
        
        slope = calculate_order_book_slope(bid_vols, ask_vols)
        self.assertGreater(slope, 0)  # Positive slope = bullish
        
        # Flat bid curve, steep ask curve
        bid_vols = [100, 90, 80, 70, 60]
        ask_vols = [200, 100, 50, 25, 10]
        
        slope = calculate_order_book_slope(bid_vols, ask_vols)
        self.assertLess(slope, 0)  # Negative slope = bearish
    
    def test_pressure_index(self):
        """Test OrderBookPressureIndex."""
        index = OrderBookPressureIndex()
        
        # Strong bullish pressure
        score = index.calculate(
            obi_l1=0.8,
            obi_depth=0.6,
            ofi_momentum=0.5,
            liquidity_slope=50
        )
        self.assertGreater(score, 0.5)
        
        # Strong bearish pressure
        score = index.calculate(
            obi_l1=-0.8,
            obi_depth=-0.6,
            ofi_momentum=-0.5,
            liquidity_slope=-50
        )
        self.assertLess(score, -0.5)
        
        # Neutral
        score = index.calculate(
            obi_l1=0.0,
            obi_depth=0.0,
            ofi_momentum=0.0,
            liquidity_slope=0
        )
        self.assertAlmostEqual(score, 0.0, places=5)


class TestRiskManager(unittest.TestCase):
    """Test cases for risk manager."""
    
    def setUp(self):
        self.config = {
            'daily_loss_limit': 0.01,
            'hourly_loss_limit': 0.005,
            'max_drawdown_limit': 0.04,
            'max_consecutive_losses': 3,
            'base_position_pct': 0.01,
            'max_position_pct': 0.015
        }
        self.risk_manager = RiskManager(self.config)
    
    def test_position_sizing(self):
        """Test position size calculation."""
        sizing = self.risk_manager.calculate_position_size(
            confidence=0.8,
            obi_magnitude=0.7,
            current_volatility=0.4,
            avg_volatility=0.4
        )
        
        self.assertGreater(sizing.size_pct, 0)
        self.assertLessEqual(sizing.size_pct, self.config['max_position_pct'])
    
    def test_consecutive_loss_limit(self):
        """Test consecutive loss limit."""
        timestamp = pd.Timestamp.now()
        
        # Record consecutive losses
        for i in range(self.config['max_consecutive_losses']):
            can_trade, reason = self.risk_manager.can_trade(timestamp)
            self.assertTrue(can_trade)
            self.risk_manager.record_trade(-0.001, timestamp)
        
        # Should be in cooldown now
        can_trade, reason = self.risk_manager.can_trade(timestamp)
        self.assertFalse(can_trade)
        self.assertIn("cooldown", reason.lower())
    
    def test_daily_loss_limit(self):
        """Test daily loss limit."""
        timestamp = pd.Timestamp.now()
        
        # Record large loss
        self.risk_manager.record_trade(-self.config['daily_loss_limit'] * 1.1, timestamp)
        
        # Should be halted
        can_trade, reason = self.risk_manager.can_trade(timestamp)
        self.assertFalse(can_trade)
        self.assertEqual(self.risk_manager.status, RiskStatus.HALTED)
    
    def test_drawdown_limit(self):
        """Test max drawdown limit."""
        timestamp = pd.Timestamp.now()
        
        # Simulate drawdown
        self.risk_manager.peak_equity = 100000
        self.risk_manager.update_equity(95000, timestamp)  # -5% drawdown
        
        # Should exceed 4% limit
        self.assertGreaterEqual(self.risk_manager.current_drawdown, 0.04)
        self.assertEqual(self.risk_manager.status, RiskStatus.HALTED)
    
    def test_risk_metrics(self):
        """Test risk metrics calculation."""
        timestamp = pd.Timestamp.now()
        
        # Add some trades
        for i in range(10):
            self.risk_manager.record_trade(0.001, timestamp)
        
        metrics = self.risk_manager.get_risk_metrics()
        
        self.assertEqual(metrics.daily_pnl, 0.01)
        self.assertEqual(metrics.trades_today, 10)
        self.assertEqual(metrics.consecutive_losses, 0)
        self.assertEqual(metrics.status, RiskStatus.OK)


class TestSignalGenerator(unittest.TestCase):
    """Test cases for signal generator."""
    
    def setUp(self):
        self.config = {
            'use_rsi_confirmation': True,
            'use_volume_confirmation': True,
            'use_trend_confirmation': True,
            'rsi_overbought': 70,
            'rsi_oversold': 30,
            'volume_percentile_threshold': 60,
            'signal_cooldown_seconds': 5
        }
        self.generator = SignalGenerator(self.config)
    
    def test_rsi_confirmation(self):
        """Test RSI confirmation logic."""
        from src.strategy import SignalType
        
        # Good long signal (RSI not overbought)
        conf = self.generator.check_rsi_confirmation(50, SignalType.LONG)
        self.assertTrue(conf.confirmed)
        
        # Bad long signal (RSI overbought)
        conf = self.generator.check_rsi_confirmation(75, SignalType.LONG)
        self.assertFalse(conf.confirmed)
        
        # Good short signal (RSI not oversold)
        conf = self.generator.check_rsi_confirmation(50, SignalType.SHORT)
        self.assertTrue(conf.confirmed)
        
        # Bad short signal (RSI oversold)
        conf = self.generator.check_rsi_confirmation(25, SignalType.SHORT)
        self.assertFalse(conf.confirmed)
    
    def test_cooldown(self):
        """Test signal cooldown."""
        timestamp = pd.Timestamp.now()
        
        # Should be able to trade initially
        self.assertTrue(self.generator.check_cooldown(timestamp))
        
        # Record signal
        self.generator.last_signal_time = timestamp
        
        # Should not be able to trade immediately
        self.assertFalse(self.generator.check_cooldown(timestamp))
        
        # Should be able to trade after cooldown
        future = timestamp + pd.Timedelta(seconds=6)
        self.assertTrue(self.generator.check_cooldown(future))


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestOrderBookImbalanceStrategy))
    suite.addTests(loader.loadTestsFromTestCase(TestIndicators))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManager))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalGenerator))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
