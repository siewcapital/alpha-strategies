"""
IV Skew Indicators Module

Calculates volatility surface metrics including:
- IV Skew (put-call vol differential)
- Realized volatility (Garman-Klass)
- IV-RV spread
- Skew Z-score for adaptive thresholding
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class VolSurfaceMetrics:
    """Volatility surface snapshot for one asset."""
    timestamp: pd.Timestamp
    atm_iv: float           # ATM implied vol (straddle midpoint)
    otm_put_iv: float       # OTM put implied vol
    otm_call_iv: float     # OTM call implied vol
    skew: float             # IV Skew: (OTM_put_IV - ATM_IV) / ATM_IV * 100
    forward_skew: float     # Forward skew (30-dte vs 60-dte)
    risk_reversal: float    # 25-delta risk reversal
    butterfly: float        # ATM butterfly (vol convexity)
    spot_price: float
    rv_30d: float           # 30-day realized vol (annualized)
    iv_rv_spread: float     # IV - RV spread


class VolSurfaceCalculator:
    """
    Calculates volatility surface metrics from options and price data.

    The key metric is IV Skew — the difference between OTM put implied vol
    and ATM implied vol, expressed as a percentage of ATM vol.

    Crypto skew is typically NEGATIVE (puts trade at discount to ATM calls
    in normal conditions) but can become extremely negative during crashes.
    Mean reversion trades on the observation that extreme skew eventually normalizes.
    """

    def __init__(
        self,
        skew_window: int = 60,
        rv_window: int = 30,
        otm_moneyness: float = 0.90,
    ):
        self.skew_window = skew_window
        self.rv_window = rv_window
        self.otm_moneyness = otm_moneyness

        self._skew_history: list[float] = []
        self._rv_history: list[float] = []

    def calculate_garman_klass_rv(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        open_: Optional[np.ndarray] = None,
        window: int = 30,
    ) -> float:
        """
        Calculate realized volatility using Garman-Klass estimator.

        Garman-Klass is ~5x more efficient than close-to-close RV.
        Formula:
        GK = sqrt(0.5 * (log(H/L))^2 - (2*ln(2)-1) * (log(CO))^2)

        Args:
            high: High prices (intraday)
            low: Low prices
            close: Close prices
            open_: Open prices (optional, enables full Garman-Klass)
            window: Lookback window in bars

        Returns:
            Annualized realized volatility (as decimal, e.g., 0.80 = 80%)
        """
        if len(close) < window:
            return 0.0

        close_arr = np.array(close[-window:])
        high_arr = np.array(high[-window:])
        low_arr = np.array(low[-window:])

        log_hl = np.log(high_arr / low_arr)
        log_hl_sq = log_hl ** 2

        if open_ is not None:
            open_arr = np.array(open_[-window:])
            log_co = np.log(close_arr / open_arr)
            log_co_sq = log_co ** 2
            var = 0.5 * log_hl_sq - (2 * np.log(2) - 1) * log_co_sq
        else:
            # Parkinson estimator (uses only H/L)
            var = 0.5 * log_hl_sq

        # Annualize: assume 365 days, ~6.5 trading hours per day (crypto: 24h)
        # For crypto: 365 days × 24 hours = 8760 hours per year
        # If data is hourly: multiply by sqrt(8760/window)
        periods_per_year = 8760  # Hourly data
        var_annualized = var.mean() * (periods_per_year / window)
        rv = np.sqrt(var_annualized)

        return float(rv)

    def calculate_skew(
        self,
        atm_iv: float,
        otm_put_iv: float,
    ) -> float:
        """
        Calculate IV Skew metric.

        Skew = (OTM_put_IV - ATM_IV) / ATM_IV × 100

        Negative values mean OTM puts are CHEAPER than ATM (normal skew).
        Extreme negative values (e.g., < -40) indicate crash premium in puts.

        Args:
            atm_iv: ATM implied vol (as decimal, e.g., 0.80 = 80%)
            otm_put_iv: OTM put implied vol

        Returns:
            Skew in percentage points (e.g., -35.0 = puts 35% cheaper than ATM)
        """
        if atm_iv <= 0:
            return 0.0
        skew = (otm_put_iv - atm_iv) / atm_iv * 100.0
        return float(skew)

    def calculate_iv_rv_spread(
        self,
        iv: float,
        rv: float,
    ) -> float:
        """
        Calculate IV-RV Spread (Variance Risk Premium component).

        Positive spread = options are overpriced (selling premium works)
        Negative spread = options are underpriced (buying premium works)

        Args:
            iv: Implied vol (annualized, decimal)
            rv: Realized vol (annualized, decimal)

        Returns:
            IV-RV spread in percentage points
        """
        return float((iv - rv) * 100.0)

    def update_skew_history(self, skew: float) -> None:
        """Add skew to rolling history for Z-score calculation."""
        self._skew_history.append(skew)
        if len(self._skew_history) > self.skew_window * 2:
            self._skew_history.pop(0)

    def update_rv_history(self, rv: float) -> None:
        """Add RV to rolling history."""
        self._rv_history.append(rv)
        if len(self._rv_history) > self.rv_window * 2:
            self._rv_history.pop(0)

    def get_skew_z_score(self, current_skew: float) -> float:
        """
        Calculate Z-score of current skew relative to history.

        Z-score > 2: Skew is extremely negative (crash premium elevated)
        Z-score < -2: Skew is elevated (unusual calm)

        Args:
            current_skew: Current IV skew value

        Returns:
            Z-score (standard deviations from mean)
        """
        if len(self._skew_history) < 20:
            return 0.0

        history = np.array(self._skew_history[-self.skew_window:])
        mean = history.mean()
        std = history.std()

        if std < 0.1:
            return 0.0

        return float((current_skew - mean) / std)

    def get_rv_percentile(self, current_rv: float) -> float:
        """
        Get percentile rank of current RV in history.

        High percentile (>80%): Vol regime is elevated
        Low percentile (<20%): Vol regime is compressed

        Args:
            current_rv: Current realized vol

        Returns:
            Percentile (0-100)
        """
        if len(self._rv_history) < 20:
            return 50.0

        history = np.array(self._rv_history[-self.rv_window:])
        percentile = (history < current_rv).mean() * 100.0
        return float(percentile)

    def calculate_vol_surface_metrics(
        self,
        timestamp: pd.Timestamp,
        spot_price: float,
        atm_straddle_iv: float,
        otm_put_iv: float,
        otm_call_iv: float,
        rv_30d: float,
        high_prices: Optional[np.ndarray] = None,
        low_prices: Optional[np.ndarray] = None,
        close_prices: Optional[np.ndarray] = None,
    ) -> VolSurfaceMetrics:
        """
        Calculate comprehensive volatility surface metrics.

        Args:
            timestamp: Current timestamp
            spot_price: Current spot price
            atm_straddle_iv: ATM straddle implied vol (approximates ATM IV)
            otm_put_iv: OTM put (10-delta equivalent) implied vol
            otm_call_iv: OTM call implied vol
            rv_30d: 30-day realized vol (pre-calculated)
            high_prices: Intraday highs for RV calculation
            low_prices: Intraday lows for RV calculation
            close_prices: Closing prices for RV calculation

        Returns:
            VolSurfaceMetrics dataclass
        """
        skew = self.calculate_skew(atm_straddle_iv, otm_put_iv)
        iv_rv_spread = self.calculate_iv_rv_spread(atm_straddle_iv, rv_30d)

        # Update histories
        self.update_skew_history(skew)
        self.update_rv_history(rv_30d)

        # Calculate forward skew (30d vs 60d ratio approximation)
        # In real implementation, would use actual term structure
        forward_skew = 0.0  # Placeholder

        # Risk reversal: (25-delta put IV - 25-delta call IV) / ATM IV * 100
        risk_reversal = (otm_put_iv - otm_call_iv) / atm_straddle_iv * 100.0 if atm_straddle_iv > 0 else 0.0

        # Butterfly: measure vol convexity
        # (butterfly = ATM_vol - 0.5*(put_vol + call_vol)) / ATM_vol * 100
        if atm_straddle_iv > 0:
            butterfly = (atm_straddle_iv - 0.5 * (otm_put_iv + otm_call_iv)) / atm_straddle_iv * 100.0
        else:
            butterfly = 0.0

        return VolSurfaceMetrics(
            timestamp=timestamp,
            atm_iv=atm_straddle_iv,
            otm_put_iv=otm_put_iv,
            otm_call_iv=otm_call_iv,
            skew=skew,
            forward_skew=forward_skew,
            risk_reversal=risk_reversal,
            butterfly=butterfly,
            spot_price=spot_price,
            rv_30d=rv_30d,
            iv_rv_spread=iv_rv_spread,
        )


class SkewSignalGenerator:
    """
    Generates trading signals based on IV skew mean reversion.

    Entry Logic:
    - LONG skew reversion: Skew is extremely negative (crash premium inflated)
      → Sell puts (expensive), expect skew to normalize upward
    - SHORT skew reversion: Skew is near zero (unusual calm)
      → Buy puts, expect crash premium to emerge

    Key insight: Extreme skew is a better predictor than skew direction alone.
    """

    def __init__(
        self,
        skew_entry_long: float = -20.0,
        skew_entry_short: float = -50.0,
        skew_mean_reversion: float = -35.0,
        skew_stop_loss: float = -65.0,
        rv_min_entry: float = 0.50,
        skew_z_threshold: float = 2.0,
    ):
        self.skew_entry_long = skew_entry_long
        self.skew_entry_short = skew_entry_short
        self.skew_mean = skew_mean_reversion
        self.skew_stop = skew_stop_loss
        self.rv_min = rv_min_entry
        self.skew_z_threshold = skew_z_threshold

        # Allow entry when z-score can't be reliably computed
        self._z_score_history_len = 0

        self.calculator = VolSurfaceCalculator()

    def compute_signals(
        self,
        metrics: VolSurfaceMetrics,
        skew_z_score: Optional[float] = None,
    ) -> Dict:
        """
        Compute skew-based trading signals.

        Args:
            metrics: Current vol surface metrics
            skew_z_score: Pre-computed skew Z-score (optional)

        Returns:
            Dict with signal type, direction, strength, and metadata
        """
        if skew_z_score is None:
            skew_z_score = self.calculator.get_skew_z_score(metrics.skew)

        # Regime filter: only trade in high-vol environments
        rv_pass = metrics.rv_30d >= self.rv_min

        # Primary signal: skew level
        skew_extreme = metrics.skew < self.skew_entry_long  # Extreme negative skew
        skew_compressed = metrics.skew > self.skew_entry_short  # Near-zero skew

        # Z-score confirmation: must be extreme (disabled for synthetic data)
        # Note: In real data with proper history, require z >= 2.0
        # For synthetic/early history, allow entry based on skew level alone
        z_confirm = abs(skew_z_score) >= self.skew_z_threshold if len(self.calculator._skew_history) >= 60 else True

        signals = {
            "timestamp": metrics.timestamp,
            "skew": metrics.skew,
            "skew_z_score": skew_z_score,
            "rv_30d": metrics.rv_30d,
            "rv_percentile": self.calculator.get_rv_percentile(metrics.rv_30d),
            "iv_rv_spread": metrics.iv_rv_spread,
            "regime_ok": rv_pass,
            "long_reversion_signal": False,
            "short_reversion_signal": False,
            "exit_signal": False,
            "signal_strength": 0.0,
            "action": "HOLD",
        }

        # STOP LOSS signal: skew has widened past stop (highest priority)
        if metrics.skew < self.skew_stop:
            signals["exit_signal"] = True
            signals["action"] = "STOP_LOSS"

        # EXIT signal: skew has reverted to mean
        elif abs(metrics.skew - self.skew_mean) < 10.0:
            signals["exit_signal"] = True
            signals["action"] = "EXIT"

        # LONG SKEW REVERSION entry
        # Skew is extremely negative → sell puts, expect normalization
        elif skew_extreme and rv_pass and z_confirm and skew_z_score > 0:
            signals["long_reversion_signal"] = True
            signals["action"] = "LONG_SKEW_REVERSION"
            # Strength based on how extreme
            distance_from_mean = abs(metrics.skew - self.skew_mean)
            signals["signal_strength"] = min(distance_from_mean / 30.0, 1.0)

        # SHORT SKEW REVERSION entry
        # Skew is near zero (compressed) → buy puts, expect expansion
        elif skew_compressed and rv_pass and z_confirm and skew_z_score < 0:
            signals["short_reversion_signal"] = True
            signals["action"] = "SHORT_SKEW_REVERSION"
            distance_from_mean = abs(metrics.skew - self.skew_mean)
            signals["signal_strength"] = min(distance_from_mean / 20.0, 1.0)

        return signals

    def calculate_position_size(
        self,
        signal_strength: float,
        portfolio_value: float,
        max_risk_pct: float = 0.02,
        option_premium_pct: float = 0.05,
    ) -> int:
        """
        Calculate number of option contracts to trade.

        Args:
            signal_strength: Signal strength (0-1)
            portfolio_value: Total portfolio value
            max_risk_pct: Maximum % of portfolio to risk per trade
            option_premium_pct: Expected premium as % of notional

        Returns:
            Number of option contracts (round lot = 1)
        """
        if signal_strength <= 0:
            return 0

        max_risk_amount = portfolio_value * max_risk_pct
        risk_per_contract = 100 * option_premium_pct  # Approximate

        if risk_per_contract <= 0:
            return 0

        n_contracts = int(max_risk_amount / risk_per_contract)
        return max(1, min(n_contracts, 100))  # 1-100 contracts


def black_scholes_iv(
    option_type: str,
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    price: float,
    volatility: float,
) -> float:
    """
    Calculate implied volatility using Black-Scholes and Newton-Raphson.

    This is the inverse: given option price, solve for volatility.

    Args:
        option_type: 'call' or 'put'
        spot: Spot price
        strike: Strike price
        time_to_expiry: Time to expiry (years)
        rate: Risk-free rate
        price: Observed option price
        volatility: Initial guess for Newton-Raphson

    Returns:
        Implied volatility
    """
    from scipy.stats import norm

    def bs_price(iv):
        d1 = (np.log(spot / strike) + (rate + 0.5 * iv ** 2) * time_to_expiry) / (iv * np.sqrt(time_to_expiry))
        d2 = d1 - iv * np.sqrt(time_to_expiry)
        if option_type == 'call':
            return spot * norm.cdf(d1) - strike * np.exp(-rate * time_to_expiry) * norm.cdf(d2)
        else:
            return strike * np.exp(-rate * time_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)

    def bs_vega(iv):
        d1 = (np.log(spot / strike) + (rate + 0.5 * iv ** 2) * time_to_expiry) / (iv * np.sqrt(time_to_expiry))
        return spot * norm.pdf(d1) * np.sqrt(time_to_expiry) / 100

    iv = volatility
    for _ in range(50):
        price_calc = bs_price(iv)
        vega = bs_vega(iv)
        if abs(vega) < 1e-10:
            break
        diff = price_calc - price
        if abs(diff) < 1e-8:
            break
        iv -= diff / vega

    return max(0.01, min(iv, 5.0))
