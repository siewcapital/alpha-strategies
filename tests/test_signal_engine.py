"""
Tests for Polymarket 5-Min Signal Strategy

Tests cover:
1. Signal Engine - Momentum calculation and signal generation
2. Position Sizer - Kelly criterion calculations
3. Risk Manager - Circuit breakers and position limits
4. Strategy - Integration tests
"""

import pytest
import numpy as np
from datetime import datetime, timedelta
import sys
sys.path.insert(0, '..')

from src.signal_engine import SignalEngine, SignalType, Direction
from src.position_sizer import PositionSizer
from src.risk_manager import RiskManager, RiskConfig


class TestSignalEngine:
    """Tests for SignalEngine."""

    def test_compute_slope(self):
        """Test linear regression slope calculation."""
        engine = SignalEngine()

        # Linear upward trend
        prices = np.array([100, 101, 102, 103, 104])
        slope = engine.compute_slope(prices)
        assert slope > 0.9, f"Expected positive slope, got {slope}"

        # Linear downward trend
        prices = np.array([104, 103, 102, 101, 100])
        slope = engine.compute_slope(prices)
        assert slope < -0.9, f"Expected negative slope, got {slope}"

        # Flat
        prices = np.array([100, 100, 100, 100, 100])
        slope = engine.compute_slope(prices)
        assert abs(slope) < 0.1, f"Expected near-zero slope, got {slope}"

    def test_momentum_readings(self):
        """Test multi-timeframe momentum calculation."""
        engine = SignalEngine()

        # Create price buffers with upward trend
        price_buffers = {
            30: [100, 100.1, 100.2, 100.3],
            60: [100, 100.1, 100.2, 100.3, 100.4, 100.5],
            120: [100, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7],
            240: [100, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7, 100.8, 100.9],
        }

        readings, confidence, direction = engine.compute_momentum_readings(
            price_buffers, 101.0
        )

        assert len(readings) == 4, "Should have 4 timeframe readings"
        assert confidence > 0, "Confidence should be positive"
        assert direction == Direction.UP, f"Expected UP, got {direction}"

    def test_trend_calculation(self):
        """Test 10-minute trend calculation."""
        engine = SignalEngine()

        # Upward trend
        prices = [100, 100.2, 100.4, 100.6, 100.8]
        direction, strength = engine.compute_trend(prices)
        assert direction == Direction.UP, f"Expected UP, got {direction}"
        assert strength > 0, "Strength should be positive"

        # Downward trend
        prices = [100.8, 100.6, 100.4, 100.2, 100]
        direction, strength = engine.compute_trend(prices)
        assert direction == Direction.DOWN, f"Expected DOWN, got {direction}"

    def test_fair_probability(self):
        """Test fair probability calculation."""
        engine = SignalEngine()

        # Large move early in window
        fair = engine.compute_fair_probability(0.01, 250)  # 1% move, 250s remaining
        assert 0.5 < fair < 0.8, f"Fair prob {fair} out of expected range"

        # Small move late in window
        fair = engine.compute_fair_probability(0.001, 50)  # 0.1% move, 50s remaining
        assert fair > 0.5, f"Fair prob {fair} should be > 0.5"

    def test_dislocation_signal(self):
        """Test DISLOCATION signal detection."""
        engine = SignalEngine()

        # Should trigger: BTC moved, token hasn't adjusted, trend agrees
        valid, fair_prob, edge = engine.check_dislocation(
            btc_price_change_pct=0.008,  # 0.8% move
            current_token_price=0.50,
            token_has_adjusted=False,
            confidence=0.6,
            trend_agrees=True,
        )

        assert valid, "DISLOCATION should be valid"
        assert edge > 0, f"Edge should be positive, got {edge}"

    def test_dislocation_blocked_by_trend(self):
        """Test DISLOCATION blocked when opposing trend."""
        engine = SignalEngine()

        valid, fair_prob, edge = engine.check_dislocation(
            btc_price_change_pct=0.008,
            current_token_price=0.50,
            token_has_adjusted=False,
            confidence=0.6,
            trend_agrees=False,  # Blocked!
        )

        assert not valid, "DISLOCATION should be blocked when opposing trend"

    def test_noise_filter(self):
        """Test noise filtering."""
        engine = SignalEngine()

        # Small move, lots of time = noise
        is_noise = engine.filter_noise(0.0001, 200)  # 0.01% move, 200s left
        assert is_noise, "Should be filtered as noise"

        # Large move = not noise
        is_noise = engine.filter_noise(0.01, 200)  # 1% move
        assert not is_noise, "Should NOT be filtered as noise"


class TestPositionSizer:
    """Tests for PositionSizer."""

    def test_kelly_calculation(self):
        """Test Kelly criterion calculation."""
        sizer = PositionSizer()

        # Positive edge should give positive Kelly
        kelly = sizer.compute_kelly_bet(edge=0.1, win_prob=0.6)
        assert kelly > 0, f"Kelly should be positive, got {kelly}"

        # Negative edge should give zero Kelly
        kelly = sizer.compute_kelly_bet(edge=-0.1, win_prob=0.4)
        assert kelly <= 0, f"Kelly should be zero or negative, got {kelly}"

    def test_position_size_calculation(self):
        """Test full position size calculation."""
        sizer = PositionSizer()

        size = sizer.calculate_position_size(
            confidence=0.7,
            token_price=0.50,
            fee_adjusted_edge=0.08,
            budget=1000.0,
        )

        assert size.size > 0, f"Position size should be positive, got {size.size}"
        assert size.size <= 250, f"Position size should be capped at quarter-Kelly"

    def test_size_reduced_after_losses(self):
        """Test position size reduction after losses."""
        sizer = PositionSizer()

        # Normal sizing
        size_normal = sizer.calculate_position_size(
            confidence=0.7,
            token_price=0.50,
            fee_adjusted_edge=0.08,
            budget=1000.0,
            consecutive_losses=0,
        )

        # After 3 losses
        size_reduced = sizer.calculate_position_size(
            confidence=0.7,
            token_price=0.50,
            fee_adjusted_edge=0.08,
            budget=1000.0,
            consecutive_losses=3,
        )

        assert size_reduced.size < size_normal.size, \
            "Position should be reduced after consecutive losses"

    def test_minimum_edge_threshold(self):
        """Test minimum edge threshold."""
        sizer = PositionSizer(min_edge_for_trade=0.03)

        # Edge below threshold
        size = sizer.calculate_position_size(
            confidence=0.5,
            token_price=0.50,
            fee_adjusted_edge=0.01,  # Below 3%
            budget=1000.0,
        )

        assert size.size == 0, f"Size should be 0 when edge below threshold"


class TestRiskManager:
    """Tests for RiskManager."""

    def test_circuit_breaker_daily_loss(self):
        """Test circuit breaker on daily loss."""
        config = RiskConfig(
            starting_balance=1000.0,
            daily_loss_limit_pct=0.20,
        )
        manager = RiskManager(config)

        # Simulate 25% loss
        manager.record_outcome('w1', won=False, pnl=-250, resolution_price=0.0)

        can_trade, reason = manager.can_trade('w2', 100)
        assert not can_trade, "Should not trade after circuit breaker"
        assert 'Circuit breaker' in reason

    def test_no_duplicate_window(self):
        """Test no duplicate bets on same window."""
        config = RiskConfig()
        manager = RiskManager(config)

        # Record a trade on window
        manager.record_trade('w1', 'up', 100, 0.50)

        can_trade, reason = manager.can_trade('w1', 100)
        assert not can_trade, "Should not trade same window twice"
        assert 'Already traded' in reason

    def test_consecutive_loss_tracking(self):
        """Test consecutive loss streak tracking."""
        config = RiskConfig()
        manager = RiskManager(config)

        manager.record_outcome('w1', won=False, pnl=-10, resolution_price=0.0)
        manager.record_outcome('w2', won=False, pnl=-10, resolution_price=0.0)
        manager.record_outcome('w3', won=False, pnl=-10, resolution_price=0.0)

        assert manager.consecutive_losses == 3
        assert manager.consecutive_wins == 0

    def test_position_size_limit(self):
        """Test max position size limit."""
        config = RiskConfig(max_position_pct=0.25)
        manager = RiskManager(config)

        # Position exceeds limit
        can_trade, reason = manager.can_trade('w1', 300)
        assert not can_trade, "Should not allow oversized position"
        assert 'exceeds max' in reason


class TestStrategyIntegration:
    """Integration tests for the full strategy."""

    def test_full_trade_cycle(self):
        """Test complete trade → resolution → outcome cycle."""
        from src.strategy import PolymarketSignalStrategy

        strategy = PolymarketSignalStrategy(
            starting_balance=1000.0,
            llm_filter_enabled=False,
            save_trades=False,
        )

        ts = datetime(2026, 3, 26, 12, 0, 0)

        # Simulate price movement triggering signal
        btc_price = 105000.0
        token_price = 0.50

        # Add some price history
        for i in range(10):
            strategy.process_market_data(
                btc_price=btc_price - i * 100,
                token_price=0.50,
                timestamp=ts - timedelta(minutes=10-i),
            )

        # Now generate signal with price moving up
        signal, position = strategy.process_market_data(
            btc_price=btc_price + 500,  # BTC moving up
            token_price=0.50,  # Token hasn't adjusted yet
            timestamp=ts,
        )

        if signal and position and position.size > 0:
            # Execute trade
            window_id = strategy._get_window_id(ts)
            trade = strategy.execute_trade(signal, position, window_id, ts)

            # Record resolution
            strategy.record_resolution(
                window_id=window_id,
                won=True,  # BTC went up
                resolution_price=1.0,
                pnl=position.size * 0.5,  # Roughly 50% win
            )

            # Check state updated
            assert strategy.state.trades_executed == 1
            assert strategy.state.trades_won == 1

    def test_trend_filter_blocks_counter_trend(self):
        """Test that trend filter blocks counter-trend signals."""
        from src.strategy import PolymarketSignalStrategy

        strategy = PolymarketSignalStrategy(
            starting_balance=1000.0,
            llm_filter_enabled=False,
        )

        ts = datetime(2026, 3, 26, 12, 0, 0)

        # First, establish a DOWN trend
        for i in range(15):
            strategy.process_market_data(
                btc_price=100000 - i * 200,  # Consistent downtrend
                token_price=0.45,
                timestamp=ts - timedelta(minutes=15-i),
            )

        # Now try to generate UP signal (counter-trend)
        signal, position = strategy.process_market_data(
            btc_price=99500 + 50,  # Small bounce
            token_price=0.50,  # Token near even
            timestamp=ts,
        )

        # Signal should either be blocked or size reduced
        if signal and signal.signal_type != SignalType.NO_SIGNAL:
            # The trend filter should have blocked or reduced
            if position:
                assert position.size == 0 or position.size_factor < 1.0, \
                    "Counter-trend signal should be blocked or reduced"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
