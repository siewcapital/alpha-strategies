"""
Unit Tests for IV Skew Mean Reversion Strategy

Tests core components:
- VolSurfaceCalculator
- SkewSignalGenerator
- Position sizing
- Risk management
- Trade lifecycle
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import yaml
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.indicators import (
    VolSurfaceCalculator,
    VolSurfaceMetrics,
    SkewSignalGenerator,
    black_scholes_iv,
)
from src.strategy import (
    IVSkewReversionStrategy,
    TradeDirection,
    PositionStatus,
    SkewTrade,
)
from src.risk_manager import RiskManager, calculate_greeks


class TestVolSurfaceCalculator(unittest.TestCase):
    """Test volatility surface calculations."""

    def setUp(self):
        self.calc = VolSurfaceCalculator(skew_window=60, rv_window=30)

    def test_calculate_skew_normal(self):
        """Test skew calculation with normal values."""
        skew = self.calc.calculate_skew(atm_iv=0.80, otm_put_iv=0.65)
        # (0.65 - 0.80) / 0.80 * 100 = -18.75%
        self.assertAlmostEqual(skew, -18.75, places=1)

    def test_calculate_skew_extreme_negative(self):
        """Test skew in crisis (puts very expensive)."""
        skew = self.calc.calculate_skew(atm_iv=0.80, otm_put_iv=0.40)
        # (0.40 - 0.80) / 0.80 * 100 = -50%
        self.assertAlmostEqual(skew, -50.0, places=0)

    def test_calculate_skew_zero_atm(self):
        """Test skew with zero ATM IV (edge case)."""
        skew = self.calc.calculate_skew(atm_iv=0.0, otm_put_iv=0.5)
        self.assertEqual(skew, 0.0)

    def test_calculate_iv_rv_spread(self):
        """Test IV-RV spread calculation."""
        spread = self.calc.calculate_iv_rv_spread(iv=0.80, rv=0.60)
        # (0.80 - 0.60) * 100 = 20%
        self.assertAlmostEqual(spread, 20.0, places=1)

    def test_update_skew_history(self):
        """Test skew history tracking for Z-score."""
        for skew in [-35.0, -40.0, -45.0, -50.0, -55.0]:
            self.calc.update_skew_history(skew)

        self.assertEqual(len(self.calc._skew_history), 5)

    def test_get_skew_z_score(self):
        """Test skew Z-score calculation."""
        # Add 60 days of historical skew
        base_skew = -35.0
        for i in range(60):
            skew = base_skew + np.random.normal(0, 5)
            self.calc.update_skew_history(skew)

        # Current skew is extremely negative
        current_skew = -55.0
        z = self.calc.get_skew_z_score(current_skew)

        # Should be negative (extreme below mean)
        self.assertLess(z, 0)

    def test_garman_klass_rv(self):
        """Test Garman-Klass realized volatility."""
        np.random.seed(42)
        n = 100
        close = 50000 * np.exp(np.cumsum(np.random.normal(0, 0.02, n)))
        high = close * 1.01
        low = close * 0.99

        rv = self.calc.calculate_garman_klass_rv(high, low, close)
        self.assertGreater(rv, 0)
        self.assertLess(rv, 1.0)  # Should be reasonable vol


class TestSkewSignalGenerator(unittest.TestCase):
    """Test skew signal generation."""

    def setUp(self):
        self.sig_gen = SkewSignalGenerator(
            skew_entry_long=-20.0,
            skew_entry_short=-50.0,
            skew_mean_reversion=-35.0,
            skew_stop_loss=-65.0,
            rv_min_entry=0.50,
        )

    def _make_metrics(self, skew=-35.0, rv=0.80, spot=50000):
        """Helper to create vol surface metrics."""
        return VolSurfaceMetrics(
            timestamp=pd.Timestamp.today(),
            atm_iv=rv,
            otm_put_iv=rv * (1 + skew / 100),
            otm_call_iv=rv * 0.95,
            skew=skew,
            forward_skew=0.0,
            risk_reversal=0.0,
            butterfly=0.0,
            spot_price=spot,
            rv_30d=rv,
            iv_rv_spread=0.0,
        )

    def test_no_signal_at_mean(self):
        """Test exit signal when skew at mean (take profit)."""
        metrics = self._make_metrics(skew=-35.0)
        signals = self.sig_gen.compute_signals(metrics, skew_z_score=0.5)
        # When skew is exactly at mean, we should exit (take profit)
        self.assertEqual(signals["action"], "EXIT")
        self.assertTrue(signals["exit_signal"])

    def test_long_reversion_signal(self):
        """Test LONG SKEW REVERSION signal when skew extreme negative."""
        # Extreme negative skew (-55 < -50 threshold)
        metrics = self._make_metrics(skew=-55.0)
        signals = self.sig_gen.compute_signals(metrics, skew_z_score=2.5)
        self.assertEqual(signals["action"], "LONG_SKEW_REVERSION")
        self.assertTrue(signals["long_reversion_signal"])

    def test_short_reversion_signal(self):
        """Test SHORT SKEW REVERSION signal when skew near zero."""
        # Near-zero skew (-10 > -20 threshold)
        metrics = self._make_metrics(skew=-10.0)
        signals = self.sig_gen.compute_signals(metrics, skew_z_score=-2.5)
        self.assertEqual(signals["action"], "SHORT_SKEW_REVERSION")
        self.assertTrue(signals["short_reversion_signal"])

    def test_exit_signal_at_mean(self):
        """Test exit signal when skew reverts to mean."""
        # Position should exit when skew near -35
        metrics = self._make_metrics(skew=-35.0)
        signals = self.sig_gen.compute_signals(metrics, skew_z_score=0.0)
        self.assertEqual(signals["action"], "EXIT")
        self.assertTrue(signals["exit_signal"])

    def test_stop_loss_signal(self):
        """Test stop loss when skew widens past threshold."""
        metrics = self._make_metrics(skew=-70.0)
        signals = self.sig_gen.compute_signals(metrics, skew_z_score=5.0)
        self.assertEqual(signals["action"], "STOP_LOSS")
        self.assertTrue(signals["exit_signal"])

    def test_regime_filter_low_vol(self):
        """Test that low vol regime blocks signals."""
        # RV below minimum threshold
        metrics = self._make_metrics(skew=-55.0, rv=0.30)
        signals = self.sig_gen.compute_signals(metrics, skew_z_score=3.0)
        self.assertEqual(signals["action"], "HOLD")
        self.assertFalse(signals["regime_ok"])

    def test_calculate_position_size(self):
        """Test position sizing via RiskManager."""
        risk_mgr = RiskManager(self.sig_gen.params if hasattr(self.sig_gen, 'params') else {
            "risk": {"max_loss_per_trade": 0.03, "max_drawdown_portfolio": 0.20, "skew_widening_stop": 15.0, "max_daily_loss_cutoff": 0.05},
            "position": {"portfolio_risk_per_trade": 0.02, "max_portfolio_options_exposure": 0.20, "max_concurrent_trades": 3},
            "signals": {"skew_entry_long": -20.0, "skew_entry_short": -50.0, "skew_mean_reversion": -35.0, "skew_stop_loss": -65.0, "rv_min_entry": 50.0}
        }, initial_capital=1_000_000)
        contracts, premium = risk_mgr.calculate_position_size(
            signal_strength=0.8,
            portfolio_value=1_000_000,
            skew=-50.0,
            rv_30d=0.80,
            trade_direction=TradeDirection.LONG_SKEW,
            implied_vol=0.80,
        )
        self.assertGreater(contracts, 0)
        self.assertGreater(premium, 0)


class TestIVSkewReversionStrategy(unittest.TestCase):
    """Test main strategy orchestrator."""

    def setUp(self):
        config_dir = os.path.abspath(os.path.join(__file__, "..", ".."))
        config_path = os.path.join(config_dir, "config", "params.yaml")
        with open(config_path) as f:
            self.params = yaml.safe_load(f)

        self.strategy = IVSkewReversionStrategy(
            params=self.params,
            initial_capital=1_000_000,
            assets=["BTC", "ETH"],
        )

    def test_initialization(self):
        """Test strategy initializes correctly."""
        self.assertEqual(self.strategy.state.portfolio_value, 1_000_000)
        self.assertEqual(self.strategy.state.cash, 1_000_000)
        self.assertEqual(len(self.strategy.state.positions), 0)

    def test_process_market_data_basic(self):
        """Test basic market data processing."""
        result = self.strategy.process_market_data(
            timestamp=pd.Timestamp.today(),
            asset="BTC",
            spot_price=50000,
            atm_straddle_iv=0.80,
            otm_put_iv=0.65,
            otm_call_iv=0.76,
            rv_30d=0.75,
        )

        self.assertIsNotNone(result)
        self.assertIn("metrics", result)
        self.assertIn("signals", result)
        self.assertEqual(result["asset"], "BTC")

    def test_open_trade(self):
        """Test trade opening."""
        entry_signal = {
            "asset": "BTC",
            "direction": TradeDirection.LONG_SKEW,
            "signal": {"signal_strength": 0.8},
            "metrics": VolSurfaceMetrics(
                timestamp=pd.Timestamp.today(),
                atm_iv=0.80,
                otm_put_iv=0.65,
                otm_call_iv=0.76,
                skew=-18.75,
                forward_skew=0.0,
                risk_reversal=0.0,
                butterfly=0.0,
                spot_price=50000,
                rv_30d=0.75,
                iv_rv_spread=5.0,
            ),
        }

        trade = self.strategy.open_trade(
            entry_signal=entry_signal,
            spot_price=50000,
            skew=-18.75,
            premium_per_contract=500,
            contracts=10,
        )

        self.assertEqual(len(self.strategy.state.positions), 1)
        self.assertEqual(trade.asset, "BTC")
        self.assertEqual(trade.direction, TradeDirection.LONG_SKEW)
        self.assertEqual(trade.status, PositionStatus.OPEN)

    def test_get_performance_metrics_empty(self):
        """Test performance metrics with no trades."""
        metrics = self.strategy.get_performance_metrics()
        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["sharpe"], 0.0)


class TestRiskManager(unittest.TestCase):
    """Test risk manager."""

    def setUp(self):
        config_dir = os.path.abspath(os.path.join(__file__, "..", ".."))
        config_path = os.path.join(config_dir, "config", "params.yaml")
        with open(config_path) as f:
            self.params = yaml.safe_load(f)

        self.risk_mgr = RiskManager(self.params, initial_capital=1_000_000)

    def test_position_sizing_basic(self):
        """Test basic position sizing."""
        contracts, premium = self.risk_mgr.calculate_position_size(
            signal_strength=0.8,
            portfolio_value=1_000_000,
            skew=-50.0,
            rv_30d=0.80,
            trade_direction=TradeDirection.LONG_SKEW,
            implied_vol=0.80,
        )
        self.assertGreater(contracts, 0)

    def test_delta_hedge_calculation(self):
        """Test delta hedge calculation."""
        trade = SkewTrade(
            trade_id=1,
            timestamp=pd.Timestamp.today(),
            direction=TradeDirection.LONG_SKEW,
            asset="BTC",
            strike=45000,
            expiry=pd.Timestamp.today() + timedelta(days=21),
            premium_received=5000,
            notional=450000,
            contracts=10,
            entry_skew=-50.0,
            entry_spot=50000,
        )

        hedge_contracts, ratio = self.risk_mgr.calculate_delta_hedge(
            position=trade,
            current_spot=50000,
            current_vol=0.80,
            days_to_expiry=14,
        )

        self.assertGreater(abs(hedge_contracts), 0)

    def test_portfolio_risk_check(self):
        """Test portfolio risk aggregation."""
        risk = self.risk_mgr.check_portfolio_risk(
            positions=[],
            portfolio_value=1_000_000,
        )
        self.assertTrue(risk["max_exposure_ok"])
        self.assertTrue(risk["drawdown_ok"])

    def test_circuit_breaker(self):
        """Test trading halt on drawdown."""
        self.risk_mgr.update_peak_equity(1_000_000)
        halt, reason = self.risk_mgr.check_trading_halt(portfolio_value=750_000)
        # 25% drawdown should trigger halt
        self.assertTrue(halt)

    def test_greeks_calculation(self):
        """Test Black-Scholes Greeks."""
        greeks = calculate_greeks(
            option_type="put",
            spot=50000,
            strike=45000,
            time_to_expiry=21 / 365,
            volatility=0.80,
            rate=0.05,
        )

        self.assertIn("delta", greeks)
        self.assertIn("gamma", greeks)
        self.assertIn("vega", greeks)
        self.assertLess(greeks["delta"], 0)  # Put delta is negative


class TestBlackScholes(unittest.TestCase):
    """Test Black-Scholes IV calculation."""

    def test_iv_calculation(self):
        """Test implied volatility from option price."""
        # ATM put at 10% vol with 30 days to expiry
        spot = 50000
        strike = 50000
        T = 30 / 365
        r = 0.05
        sigma = 0.10

        # Calculate price first
        from scipy.stats import norm
        d1 = (np.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        put_price = strike * np.exp(-r * T) * norm.cdf(-d2) - spot * norm.cdf(-d1)

        # Now back-solve for IV
        iv = black_scholes_iv("put", spot, strike, T, r, put_price, volatility=0.10)
        self.assertAlmostEqual(iv, sigma, places=2)


if __name__ == "__main__":
    unittest.main()
