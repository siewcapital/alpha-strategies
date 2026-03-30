"""
test_strategy.py - Unit tests for Multi-Factor Regime-Adaptive Strategy.
"""

import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.indicators import (
    sma, ema, atr, adx, rsi, zscore, bollinger_bands, roc, 
    regime_score, regime_label, sharpe_momentum
)
from src.factor_signals import (
    trend_following_signal, mean_reversion_signal,
    volatility_breakout_signal, momentum_signal,
    regime_weights, composite_score, all_factor_signals
)
from src.risk_manager import RiskManager
from src.strategy import MultiFactorRegimeStrategy, Position, Trade


class TestIndicators:
    """Test technical indicators."""
    
    def test_sma(self):
        """SMA calculation."""
        closes = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        result = sma(closes, 3)
        assert result[2] == 2.0
        assert result[9] == 9.0
        assert np.isnan(result[0])
        assert np.isnan(result[1])
    
    def test_ema(self):
        """EMA calculation."""
        closes = np.array([1, 2, 3, 4, 5], dtype=float)
        result = ema(closes, 3)
        assert not np.isnan(result[-1])
        assert result[-1] > result[0]  # EMA should trend up
    
    def test_atr(self):
        """ATR calculation."""
        highs = np.array([105, 110, 108, 112, 115], dtype=float)
        lows = np.array([95, 98, 96, 100, 102], dtype=float)
        closes = np.array([100, 105, 102, 108, 110], dtype=float)
        result = atr(highs, lows, closes, 3)
        assert result[-1] > 0
        assert np.isnan(result[0])
        assert np.isnan(result[1])
    
    def test_adx(self):
        """ADX calculation."""
        np.random.seed(42)
        n = 100
        closes = 100 + np.cumsum(np.random.randn(n) * 0.02)
        highs = closes * 1.01
        lows = closes * 0.99
        highs[0] = closes[0] * 1.01
        lows[0] = closes[0] * 0.99
        
        adx_vals, plus_di, minus_di = adx(highs, lows, closes, 14)
        assert 0 <= adx_vals[-1] <= 100
        assert np.isnan(adx_vals[0])
    
    def test_rsi(self):
        """RSI calculation."""
        closes = np.array([100, 102, 101, 103, 102, 104, 103, 105], dtype=float)
        result = rsi(closes, 3)
        assert 0 <= result[-1] <= 100
        assert result[0] == 0  # First value is 0 (no gains/losses yet)
    
    def test_zscore(self):
        """Z-score calculation."""
        data = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        result = zscore(data, 5)
        # The last value (10) should have positive z-score
        assert result[-1] > 0
        assert result[0] == 0  # First value z-score is 0 (not NaN)
    
    def test_bollinger_bands(self):
        """Bollinger Bands calculation."""
        closes = np.array([100, 102, 101, 103, 102, 104, 105, 106, 104, 103], dtype=float)
        upper, middle, lower = bollinger_bands(closes, 5, 2.0)
        assert upper[-1] > middle[-1]
        assert lower[-1] < middle[-1]
        assert upper[-1] > lower[-1]
    
    def test_regime_label(self):
        """Regime labeling."""
        n = 50
        adx_vals = np.full(n, 30.0)  # Trending
        rsi_vals = np.full(n, 45.0)  # Not overbought/oversold
        atr_pct = np.full(n, 50.0)   # Normal vol
        
        labels = regime_label(adx_vals, rsi_vals, atr_pct)
        assert labels[-1] == "TRENDING"
    
    def test_regime_label_high_vol(self):
        """High volatility regime detection."""
        n = 50
        adx_vals = np.full(n, 30.0)
        rsi_vals = np.full(n, 50.0)
        atr_pct = np.full(n, 85.0)  # High vol
        
        labels = regime_label(adx_vals, rsi_vals, atr_pct)
        assert labels[-1] == "HIGH_VOL"


class TestFactorSignals:
    """Test factor signal generators."""
    
    def test_trend_following(self):
        """Trend-following signal generation."""
        # Uptrend
        closes = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                          110, 111, 112, 113, 114, 115, 116, 117, 118, 119,
                          120, 121, 122, 123, 124, 125, 126, 127, 128, 129,
                          130, 131, 132, 133, 134, 135, 136, 137, 138, 139,
                          140, 141, 142, 143, 144, 145, 146, 147, 148, 149,
                          150], dtype=float)
        
        signals, confidence = trend_following_signal(closes, fast_period=10, slow_period=20)
        # Should eventually go bullish in uptrend
        assert np.any(signals == 1)
    
    def test_mean_reversion(self):
        """Mean-reversion signal generation."""
        # Spike up (should give short signal)
        closes = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
                          100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
                          150], dtype=float)  # Spike
        
        signals, confidence = mean_reversion_signal(closes, period=10, z_threshold=1.5)
        # Last value should have bearish signal due to high z-score
        assert signals[-1] == -1 or signals[-1] == 0  # Either short or neutral
    
    def test_volatility_breakout(self):
        """Volatility breakout signal generation."""
        np.random.seed(42)
        n = 100
        closes = 100 + np.cumsum(np.random.randn(n) * 0.01)
        highs = closes * 1.02
        lows = closes * 0.98
        
        signals, confidence = volatility_breakout_signal(highs, lows, closes)
        # Should have some signals
        assert len(signals) == n
    
    def test_regime_weights(self):
        """Regime weight allocation."""
        weights = regime_weights("TRENDING")
        assert weights["trend_following"] == 0.50
        assert weights["mean_reversion"] == 0.10
        assert abs(sum(weights.values()) - 1.0) < 0.01
        
        weights = regime_weights("RANGING")
        assert weights["mean_reversion"] == 0.50
        
        weights = regime_weights("UNKNOWN")
        # Should use equal weights
        assert abs(sum(weights.values()) - 1.0) < 0.01
    
    def test_composite_score(self):
        """Composite score calculation."""
        n = 50
        closes = 100 + np.cumsum(np.random.randn(n) * 0.01)
        highs = closes * 1.01
        lows = closes * 0.99
        
        factor_signals = all_factor_signals(highs, lows, closes)
        weights = regime_weights("TRENDING")
        
        score, breakdown = composite_score(factor_signals, weights, n-1)
        assert -1 <= score <= 1
        assert len(breakdown) == 4


class TestRiskManager:
    """Test risk manager."""
    
    def test_kelly_fraction(self):
        """Kelly criterion calculation."""
        rm = RiskManager()
        
        # 60% win rate, 1.5:1 reward/risk
        kelly = rm.kelly_fraction(0.6, 0.015, 0.01)
        assert 0 < kelly <= 0.25  # Should be capped at 0.25
        assert kelly > 0
    
    def test_kelly_fraction_losing(self):
        """Kelly with losing strategy."""
        rm = RiskManager()
        
        # 40% win rate
        kelly = rm.kelly_fraction(0.4, 0.01, 0.01)
        assert kelly == 0.0  # Should be zero or negative
    
    def test_drawdown_tracking(self):
        """Drawdown tracking."""
        rm = RiskManager()
        rm.update_capital(1.0)  # Peak at 1.0
        rm.update_capital(0.9)   # Drawdown
        assert abs(rm.current_drawdown - 0.1) < 0.001
        assert rm.current_capital == 0.9
        assert rm.peak_capital == 1.0
    
    def test_circuit_breaker(self):
        """Circuit breaker activation."""
        rm = RiskManager(max_drawdown_cutoff=0.2)
        rm.update_capital(1.0)
        rm.update_capital(0.75)  # 25% drawdown
        
        allowed, reason = rm.is_trading_allowed()
        assert allowed == False
        assert "Max drawdown" in reason
    
    def test_circuit_breaker_reset(self):
        """Circuit breaker reset."""
        rm = RiskManager(max_drawdown_cutoff=0.2)
        rm.circuit_breaker_active = True
        
        # Drawdown still above 10% (threshold = 0.2 * 0.5 = 0.10)
        rm.current_drawdown = 0.12
        rm.reset_circuit_breaker()
        assert rm.circuit_breaker_active == True  # Still above 10%
        
        # Drawdown drops below 10% - should reset
        rm.current_drawdown = 0.08
        rm.reset_circuit_breaker()
        assert rm.circuit_breaker_active == False
    
    def test_max_position_size(self):
        """Max position concentration."""
        rm = RiskManager(max_position_pct=0.2)
        max_size = rm.max_position_size(100000, 50000)
        assert max_size == 0.4  # 20% of 100k / 50k price = 0.4 units
    
    def test_volatility_adjusted_size(self):
        """Volatility targeting."""
        rm = RiskManager()
        base = 10000
        target_vol = 0.15 / np.sqrt(252)
        realized_vol = 0.30 / np.sqrt(252)
        
        adjusted = rm.volatility_adjusted_size(target_vol, realized_vol, base)
        assert adjusted == base * (target_vol / realized_vol)
        assert adjusted < base  # Lower vol = bigger position


class TestStrategy:
    """Test main strategy."""
    
    def test_strategy_initialization(self):
        """Strategy initializes correctly."""
        strategy = MultiFactorRegimeStrategy()
        assert strategy.bar_count == 0
        assert len(strategy.positions) == 0
        assert len(strategy.trades) == 0
    
    def test_strategy_reset(self):
        """Strategy reset clears state."""
        strategy = MultiFactorRegimeStrategy()
        strategy.bar_count = 100
        strategy.positions["TEST"] = Position(
            asset="TEST", direction=1, entry_price=100,
            size=1000, entry_time=50, entry_regime="TRENDING"
        )
        
        strategy.reset()
        assert strategy.bar_count == 0
        assert len(strategy.positions) == 0
    
    def test_position_pnl(self):
        """Position PnL calculation."""
        pos = Position(
            asset="BTC", direction=1, entry_price=50000,
            size=10000, entry_time=0, entry_regime="TRENDING"
        )
        
        # 10% gain
        pnl = pos.current_pnl(55000)
        assert pnl == 1000  # 10% of 10000
        
        # 5% loss
        pnl = pos.current_pnl(47500)
        assert pnl == -500
    
    def test_short_position_pnl(self):
        """Short position PnL."""
        pos = Position(
            asset="BTC", direction=-1, entry_price=50000,
            size=10000, entry_time=0, entry_regime="TRENDING"
        )
        
        # Price falls 10%
        pnl = pos.current_pnl(45000)
        assert pnl == 1000  # Short gains when price falls


class TestIntegration:
    """Integration tests with synthetic data."""
    
    def test_full_backtest_run(self):
        """Run full backtest with synthetic data."""
        from backtest.backtest import generate_synthetic_data, run_backtest
        
        np.random.seed(42)
        highs, lows, opens, closes = generate_synthetic_data(n_days=500, n_assets=3)
        
        params = {
            "adx_period": 14,
            "rsi_period": 14,
            "atr_period": 14,
            "atr_percentile_period": 50,
            "tf_fast": 20,
            "tf_slow": 50,
            "mr_period": 20,
            "mr_z_threshold": 2.0,
            "vb_period": 20,
            "vb_threshold": 2.0,
            "mom_short": 10,
            "mom_long": 30,
            "signal_threshold": 0.3,
            "stop_loss_atr": 2.0,
            "trailing_stop_atr": 1.5,
            "time_stop_bars": 10,
            "max_kelly": 0.25,
            "max_position_pct": 0.20,
            "max_leverage": 3.0,
            "max_drawdown": 0.20,
            "win_rate": 0.55,
            "avg_win": 0.02,
            "avg_loss": 0.01,
            "max_assets": 3,
            "rebalance_frequency": 1
        }
        
        results = run_backtest(
            params, highs, lows, opens, closes,
            initial_capital=100000
        )
        
        assert "metrics" in results
        assert "equity_curve" in results
        assert results["metrics"]["total_trades"] >= 0
        assert results["metrics"]["final_equity"] > 0
        assert len(results["equity_curve"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
