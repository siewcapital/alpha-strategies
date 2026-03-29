"""
Risk Manager for IV Skew Mean Reversion Strategy

Handles position sizing, delta hedging, portfolio-level risk controls,
and circuit breakers.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

from .strategy import TradeDirection, SkewTrade, StrategyState


logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Set of risk limits for the strategy."""
    max_portfolio_options_exposure: float  # Max % of portfolio in options
    max_single_trade_risk: float          # Max % of portfolio per trade
    max_drawdown_cutoff: float             # Portfolio drawdown hard stop
    max_correlated_positions: int         # Max positions in same direction
    max_daily_loss_cutoff: float           # Daily loss halt threshold
    skew_widening_stop_pp: float           # Exit if skew widens N pp


@dataclass
class PositionRisk:
    """Risk metrics for a single position."""
    trade: SkewTrade
    delta: float              # Position delta
    gamma: float              # Position gamma
    vega: float               # Position vega
    theta: float              # Daily theta decay
    unrealized_pnl: float
    max_adverse_excursion: float
    max_favorable_excursion: float


class RiskManager:
    """
    Centralized risk management for IV skew strategy.

    Responsibilities:
    1. Position sizing (Kelly-based with cap)
    2. Delta hedging calculations
    3. Portfolio-level risk aggregation
    4. Circuit breaker monitoring
    5. Drawdown tracking and enforcement
    """

    def __init__(
        self,
        params: Dict,
        initial_capital: float = 1_000_000,
    ):
        self.params = params
        self.initial_capital = initial_capital

        # Risk limits from params
        risk = params["risk"]
        pos = params["position"]

        self.limits = RiskLimits(
            max_portfolio_options_exposure=pos["max_portfolio_options_exposure"],
            max_single_trade_risk=pos["portfolio_risk_per_trade"],
            max_drawdown_cutoff=risk["max_drawdown_portfolio"],
            max_correlated_positions=pos["max_concurrent_trades"],
            max_daily_loss_cutoff=risk["max_daily_loss_cutoff"],
            skew_widening_stop_pp=risk["skew_widening_stop"],
        )

        # State
        self._peak_equity = initial_capital
        self._daily_pnl = 0.0
        self._trading_halted = False
        self._halt_reason = ""
        self._position_risks: Dict[int, PositionRisk] = {}

    def calculate_position_size(
        self,
        signal_strength: float,
        portfolio_value: float,
        skew: float,
        rv_30d: float,
        trade_direction: TradeDirection,
        implied_vol: float,
        days_to_expiry: int = 21,
    ) -> Tuple[int, float]:
        """
        Calculate optimal position size using volatility-adjusted Kelly.

        Kelly criterion: f* = (bp - q) / b
        Where b = odds, p = win prob, q = 1-p

        We use fractional Kelly (25%) to reduce volatility of returns.

        Args:
            signal_strength: Signal strength (0-1)
            portfolio_value: Current portfolio value
            skew: Current skew level
            rv_30d: Realized vol (annualized)
            trade_direction: LONG_SKEW or SHORT_SKEW
            implied_vol: ATM implied vol
            days_to_expiry: Days until option expiry

        Returns:
            Tuple of (number_of_contracts, estimated_premium_per_contract)
        """
        if signal_strength <= 0:
            return 0, 0.0

        # Kelly win rate estimate based on skew level
        # Extreme skew (very negative) → higher probability of reversion
        # Normal skew → lower probability
        skew_mean = self.params["signals"]["skew_mean_reversion"]
        skew_extreme = abs(skew - skew_mean)

        # Estimate win probability: higher when skew is more extreme
        if trade_direction == TradeDirection.LONG_SKEW:
            # We're selling puts expecting skew to normalize
            # Win if skew rises toward mean
            skew_advantage = max(0, (abs(skew) - abs(skew_mean)) / 100.0)
            win_prob = min(0.75, 0.55 + skew_advantage * 0.5)
        else:
            # We're buying puts expecting skew to widen further
            win_prob = 0.45  # Mean reversion is more reliable than continuation

        # Kelly fraction (25% = conservative)
        kelly_fraction = 0.25

        # Base Kelly
        b = 2.0  # Assume 2:1 reward-risk ratio
        q = 1 - win_prob
        kelly = (b * win_prob - q) / b
        kelly = max(0, kelly) * kelly_fraction

        # Adjust for volatility (inverse vol scaling)
        vol_scalar = 0.80 / max(rv_30d, 0.30)
        vol_scalar = min(vol_scalar, 2.0)  # Cap at 2x

        # Risk per trade (2% max)
        max_risk_amount = portfolio_value * self.limits.max_single_trade_risk

        # Option premium estimate (rough)
        # For a straddle at ATM with IV and DTE days to expiry:
        # Premium ≈ 0.4 * IV * S * sqrt(DTE/365) * contract_size
        # This is simplified BS approximation
        time_fraction = days_to_expiry / 365.0
        premium_pct_est = 0.40 * implied_vol * np.sqrt(time_fraction)
        premium_per_contract = 100 * premium_pct_est  # Notional × premium%

        # Calculate contracts based on Kelly sizing
        if premium_per_contract > 0:
            kelly_contracts = int(kelly * portfolio_value / premium_per_contract)
        else:
            kelly_contracts = 1

        # Cap at max risk amount
        risk_adjusted = int(max_risk_amount / (premium_per_contract * 0.5))  # Assume 50% max loss
        contracts = min(kelly_contracts, risk_adjusted, 100)  # Max 100 contracts
        contracts = max(1, contracts)

        return contracts, premium_per_contract

    def calculate_delta_hedge(
        self,
        position: SkewTrade,
        current_spot: float,
        current_vol: float,
        days_to_expiry: float,
        rate: float = 0.05,
    ) -> Tuple[float, float]:
        """
        Calculate delta hedge ratio for a skew trade.

        For a SHORT SKEW position (selling OTM puts):
        - We are LONG delta (negative delta position is hedged)
        - Need to sell futures to neutralize

        For a LONG SKEW position (buying OTM puts):
        - We are SHORT delta
        - Need to buy futures to neutralize

        Uses Black-Scholes delta approximation:
        Delta_put ≈ -N(-d1) where d1 = (ln(S/K) + (r + σ²/2)T) / (σ√T)

        Args:
            position: The trade to hedge
            current_spot: Current spot price
            current_vol: Current implied vol
            days_to_expiry: Days remaining
            rate: Risk-free rate

        Returns:
            Tuple of (delta_hedge_contracts, hedge_ratio)
        """
        T = days_to_expiry / 365.0
        K = position.strike
        S = current_spot
        sigma = current_vol
        r = rate

        if T <= 0 or sigma <= 0:
            return 0.0, 0.0

        # Black-Scholes d1
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

        # Standard normal CDF
        from scipy.stats import norm
        delta_put = -norm.cdf(-d1)  # Delta of put option

        # Position delta (per contract)
        # For short put: delta = +|delta_put| (gain if spot rises)
        # For long put: delta = -|delta_put| (lose if spot rises)
        if position.direction == TradeDirection.LONG_SKEW:
            # Long put → negative delta
            position_delta = delta_put * position.contracts * 100
        else:
            # Short put → positive delta (we benefit from rising prices)
            position_delta = -delta_put * position.contracts * 100

        # Hedge ratio: 50% delta hedge (from params)
        hedge_ratio = 0.50
        hedge_contracts = -position_delta * hedge_ratio / current_spot  # Futures contracts

        return hedge_contracts, hedge_ratio

    def check_portfolio_risk(
        self,
        positions: List[SkewTrade],
        portfolio_value: float,
    ) -> Dict:
        """
        Check aggregated portfolio risk metrics.

        Args:
            positions: List of open positions
            portfolio_value: Current portfolio value

        Returns:
            Dict with risk metrics and any limit breaches
        """
        if not positions:
            return {
                "total_exposure": 0.0,
                "max_exposure_ok": True,
                "correlated_positions_ok": True,
                "drawdown_ok": True,
                "daily_loss_ok": True,
                "breaches": [],
            }

        # Total options notional exposure
        total_notional = sum(abs(p.notional) for p in positions)
        total_exposure_pct = total_notional / portfolio_value

        # Direction grouping
        long_skew_count = sum(1 for p in positions if p.direction == TradeDirection.LONG_SKEW)
        short_skew_count = sum(1 for p in positions if p.direction == TradeDirection.SHORT_SKEW)

        # Drawdown check
        current_dd = (self._peak_equity - portfolio_value) / self._peak_equity
        drawdown_ok = current_dd < self.limits.max_drawdown_cutoff

        # Exposure check
        exposure_ok = total_exposure_pct < self.limits.max_portfolio_options_exposure

        # Correlation check (no more than max concurrent in same direction)
        corr_ok = (long_skew_count <= self.limits.max_correlated_positions and
                   short_skew_count <= self.limits.max_correlated_positions)

        # Daily loss check
        daily_loss_ok = abs(self._daily_pnl) < self.limits.max_daily_loss_cutoff * portfolio_value

        breaches = []
        if not exposure_ok:
            breaches.append(f"EXPOSURE: {total_exposure_pct:.1%} > {self.limits.max_portfolio_options_exposure:.1%}")
        if not drawdown_ok:
            breaches.append(f"DRAWDOWN: {current_dd:.1%} > {self.limits.max_drawdown_cutoff:.1%}")
        if not corr_ok:
            breaches.append(f"CORRELATED: {long_skew_count}L/{short_skew_count}S > {self.limits.max_correlated_positions}")
        if not daily_loss_ok:
            breaches.append(f"DAILY_LOSS: ${abs(self._daily_pnl):.0f} > ${self.limits.max_daily_loss_cutoff * portfolio_value:.0f}")

        return {
            "total_exposure": total_exposure_pct,
            "long_skew_positions": long_skew_count,
            "short_skew_positions": short_skew_count,
            "max_exposure_ok": exposure_ok,
            "correlated_positions_ok": corr_ok,
            "drawdown_ok": drawdown_ok,
            "daily_loss_ok": daily_loss_ok,
            "breaches": breaches,
            "current_drawdown": current_dd,
        }

    def update_peak_equity(self, portfolio_value: float) -> None:
        """Update peak equity for drawdown tracking."""
        if portfolio_value > self._peak_equity:
            self._peak_equity = portfolio_value

    def record_daily_pnl(self, pnl: float) -> None:
        """Record daily PnL for daily loss cutoff tracking."""
        self._daily_pnl += pnl

    def reset_daily_pnl(self) -> None:
        """Reset daily PnL counter at start of new day."""
        self._daily_pnl = 0.0

    def check_trading_halt(self, portfolio_value: float) -> Tuple[bool, str]:
        """
        Check if trading should be halted due to risk breaches.

        Args:
            portfolio_value: Current portfolio value

        Returns:
            Tuple of (should_halt, reason)
        """
        # Drawdown halt
        current_dd = (self._peak_equity - portfolio_value) / self._peak_equity
        if current_dd >= self.limits.max_drawdown_cutoff:
            self._trading_halted = True
            self._halt_reason = f"MAX_DRAWDOWN: {current_dd:.1%} >= {self.limits.max_drawdown_cutoff:.1%}"
            return True, self._halt_reason

        # Daily loss halt
        if abs(self._daily_pnl) >= self.limits.max_daily_loss_cutoff * self._peak_equity:
            self._trading_halted = True
            self._halt_reason = f"DAILY_LOSS: ${abs(self._daily_pnl):.0f}"
            return True, self._halt_reason

        return False, ""

    def is_trading_halted(self) -> bool:
        """Return whether trading is currently halted."""
        return self._trading_halted

    def resume_trading(self) -> None:
        """Manually resume trading after halt."""
        self._trading_halted = False
        self._halt_reason = ""
        logger.info("Trading resumed manually")

    def get_risk_summary(self, portfolio_value: float) -> Dict:
        """Get comprehensive risk summary."""
        self.update_peak_equity(portfolio_value)
        current_dd = (self._peak_equity - portfolio_value) / self._peak_equity

        return {
            "peak_equity": self._peak_equity,
            "current_equity": portfolio_value,
            "current_drawdown": current_dd,
            "daily_pnl": self._daily_pnl,
            "trading_halted": self._trading_halted,
            "halt_reason": self._halt_reason,
            "limits": {
                "max_drawdown": self.limits.max_drawdown_cutoff,
                "max_daily_loss": self.limits.max_daily_loss_cutoff,
                "max_options_exposure": self.limits.max_portfolio_options_exposure,
            },
        }


def calculate_greeks(
    option_type: str,
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    rate: float,
) -> Dict[str, float]:
    """
    Calculate Black-Scholes Greeks for an option.

    Args:
        option_type: 'call' or 'put'
        spot: Spot price
        strike: Strike price
        time_to_expiry: Time to expiry (years)
        volatility: Implied vol (annualized)
        rate: Risk-free rate

    Returns:
        Dict with delta, gamma, vega, theta, rho
    """
    from scipy.stats import norm

    if time_to_expiry <= 0 or volatility <= 0:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0, "rho": 0}

    d1 = (np.log(spot / strike) + (rate + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * np.sqrt(time_to_expiry))
    d2 = d1 - volatility * np.sqrt(time_to_expiry)

    phi = norm.pdf(d1)
    Phi = norm.cdf(d1)
    Phi_minus = norm.cdf(-d1) if option_type == 'put' else norm.cdf(d1)
    Phi_delta = -norm.cdf(-d1) if option_type == 'put' else norm.cdf(d1)

    # Delta
    delta = Phi_delta

    # Gamma (same for calls and puts)
    gamma = phi / (spot * volatility * np.sqrt(time_to_expiry))

    # Vega (same for calls and puts, per 1% vol move)
    vega = spot * phi * np.sqrt(time_to_expiry) / 100

    # Theta (per day, negative = decay)
    if option_type == 'call':
        theta = (-spot * phi * volatility / (2 * np.sqrt(time_to_expiry))
                 - rate * strike * np.exp(-rate * time_to_expiry) * norm.cdf(d2)) / 365
    else:
        theta = (-spot * phi * volatility / (2 * np.sqrt(time_to_expiry))
                 + rate * strike * np.exp(-rate * time_to_expiry) * norm.cdf(-d2)) / 365

    # Rho (per 1% rate change)
    rho = strike * time_to_expiry * np.exp(-rate * time_to_expiry) * Phi_minus / 100

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
        "d1": d1,
        "d2": d2,
    }
