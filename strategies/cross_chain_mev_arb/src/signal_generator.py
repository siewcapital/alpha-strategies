"""
Cross-Chain MEV Arbitrage - Signal Generator
Combines spread signals, risk, and opportunity quality into actionable trade signals.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SignalType(Enum):
    ENTRY_LONG = "entry_long"        # Buy on chain A, sell on chain B
    ENTRY_SHORT = "entry_short"      # Opposite direction
    EXIT = "exit"                    # Close existing position
    SKIP = "skip"                   # Opportunity exists but skip (risk/sizing)
    HOLD = "hold"                   # No action


@dataclass
class TradeSignal:
    """
    Actionable trading signal for cross-chain arbitrage.
    """
    signal_id: str
    signal_type: SignalType
    
    # Opportunity details
    opportunity: 'ArbitrageOpportunity'
    
    # Recommended sizing
    recommended_size_usd: float
    min_viable_size_usd: float
    max_size_usd: float
    
    # Quality metrics
    confidence: float              # 0-1
    expected_return_pct: float     # Expected return %
    expected_pnl_usd: float        # Expected net PnL
    risk_adjusted_return: float     # Sharpe-like ratio estimate
    
    # Entry/exit
    urgency: str                   # "immediate" | "within_1min" | "within_5min"
    valid_until: datetime
    
    # Warnings
    warnings: List[str] = field(default_factory=list)
    execution_notes: str = ""
    
    def __post_init__(self):
        if not self.signal_id:
            import uuid
            self.signal_id = str(uuid.uuid4())[:8]
    
    def size_recommendation(self, capital_usd: float) -> float:
        """Recommend position size as % of capital"""
        pct = self.recommended_size_usd / capital_usd if capital_usd > 0 else 0
        return min(pct, 0.15)  # Cap at 15%
    
    def is_actionable(self) -> bool:
        return self.signal_type in [SignalType.ENTRY_LONG, SignalType.ENTRY_SHORT]
    
    def breakeven_spread_bps(self) -> float:
        """Minimum spread needed to be profitable"""
        opp = self.opportunity
        costs = opp.buy_gas_usd + opp.sell_gas_usd + opp.bridge_fee_usd + opp.slippage_usd
        size = self.recommended_size_usd
        if size == 0:
            return float('inf')
        return costs / size * 10000


class SignalGenerator:
    """
    Generates actionable trade signals from detected opportunities.
    
    Combines:
    - Spread analysis (z-score, percentile)
    - Risk assessment (Kelly sizing, bridge risk)
    - Market conditions (gas, timing)
    - Historical performance
    """
    
    def __init__(
        self,
        config: Dict,
        arb_detector: Optional['ArbitrageDetector'] = None,
        risk_manager: Optional['RiskManager'] = None,
        gas_estimator: Optional['GasEstimator'] = None,
    ):
        self.config = config
        self.trading_config = config.get('trading', {})
        self.risk_config = config.get('risk', {})
        
        self.arb_detector = arb_detector
        self.risk_manager = risk_manager
        self.gas_estimator = gas_estimator
        
        # Parameters
        self.min_confidence = 0.60
        self.min_profit_usd = 50.0
        self.max_position_age_secs = 1800
        
        # Signal tracking
        self._signal_counter = 0
        self._active_signals: Dict[str, TradeSignal] = {}
    
    def generate_signal(
        self,
        opportunity: 'ArbitrageOpportunity',
        portfolio_value: float,
    ) -> TradeSignal:
        """
        Generate a TradeSignal from an ArbitrageOpportunity.
        
        This is the main entry point for signal generation.
        """
        self._signal_counter += 1
        
        # ─── Step 1: Confidence scoring ─────────────────────────────────────
        confidence = self._calculate_confidence(opportunity)
        
        # ─── Step 2: Sizing ─────────────────────────────────────────────────
        min_size, max_size = self._calculate_size(
            opportunity, portfolio_value
        )
        
        recommended_size = min(
            opportunity.optimal_trade_size_usd,
            max_size
        )
        
        # ─── Step 3: Expected return ────────────────────────────────────────
        expected_pnl = self._estimate_pnl(opportunity, recommended_size)
        expected_return_pct = expected_pnl / recommended_size if recommended_size > 0 else 0
        risk_adj_return = expected_return_pct / self._estimate_risk(opportunity)
        
        # ─── Step 4: Urgency ─────────────────────────────────────────────────
        urgency = self._assess_urgency(opportunity)
        
        # ─── Step 5: Warnings ───────────────────────────────────────────────
        warnings = self._generate_warnings(opportunity, confidence)
        
        # ─── Step 6: Signal type ────────────────────────────────────────────
        signal_type = self._determine_signal_type(
            opportunity, confidence, expected_pnl, warnings
        )
        
        # ─── Build signal ────────────────────────────────────────────────────
        signal = TradeSignal(
            signal_id=f"SIG-{self._signal_counter:06d}",
            signal_type=signal_type,
            opportunity=opportunity,
            recommended_size_usd=recommended_size,
            min_viable_size_usd=max(min_size, self.min_profit_usd / (expected_return_pct / 100) if expected_return_pct > 0 else 0),
            max_size_usd=max_size,
            confidence=confidence,
            expected_return_pct=expected_return_pct * 100,
            expected_pnl_usd=expected_pnl,
            risk_adjusted_return=risk_adj_return,
            urgency=urgency,
            valid_until=opportunity.expires_at,
            warnings=warnings,
        )
        
        if signal.is_actionable():
            self._active_signals[signal.signal_id] = signal
        
        return signal
    
    def _calculate_confidence(self, opp: 'ArbitrageOpportunity') -> float:
        """
        Calculate confidence score 0-1.
        
        Based on:
        - Spread z-score (more extreme = more confident)
        - Historical win rate for similar spreads
        - Risk scores
        """
        base_conf = 0.5
        
        # Z-score contribution
        zscore = abs(opp.spread_zscore)
        if zscore >= 3.0:
            zscore_conf = 0.35
        elif zscore >= 2.5:
            zscore_conf = 0.30
        elif zscore >= 2.0:
            zscore_conf = 0.25
        elif zscore >= 1.5:
            zscore_conf = 0.15
        else:
            zscore_conf = 0.0
        
        # Percentile contribution
        percentile = opp.spread_percentile
        if percentile > 95:
            pct_conf = 0.20
        elif percentile > 90:
            pct_conf = 0.15
        elif percentile > 80:
            pct_conf = 0.10
        else:
            pct_conf = 0.0
        
        # Spread size contribution
        spread = abs(opp.spread_bps)
        if spread > 100:
            spread_conf = 0.15
        elif spread > 50:
            spread_conf = 0.10
        elif spread > 30:
            spread_conf = 0.05
        else:
            spread_conf = 0.0
        
        # Risk penalties
        risk_penalty = 0.0
        if opp.bridge_risk_score > 7:
            risk_penalty = 0.15
        elif opp.bridge_risk_score > 5:
            risk_penalty = 0.05
        
        if opp.mev_risk_score > 7:
            risk_penalty += 0.10
        
        # Final confidence
        confidence = base_conf + zscore_conf + pct_conf + spread_conf - risk_penalty
        
        # Gas spike penalty
        # (would check gas estimator here)
        
        return max(0.0, min(0.99, confidence))
    
    def _calculate_size(
        self,
        opp: 'ArbitrageOpportunity',
        portfolio_value: float,
    ) -> Tuple[float, float]:
        """
        Calculate position size limits.
        
        Returns: (min_size, max_size)
        """
        if self.risk_manager:
            return self.risk_manager.get_position_limits(opp)
        
        # Default sizing: 10% of portfolio max
        max_kelly = portfolio_value * 0.10
        max_hard = portfolio_value * 0.15
        max_size = min(max_kelly, max_hard, opp.max_trade_size_usd)
        
        min_size = max(5000, portfolio_value * 0.01)
        
        return min_size, max_size
    
    def _estimate_pnl(
        self,
        opp: 'ArbitrageOpportunity',
        size_usd: float
    ) -> float:
        """Estimate net PnL for a given size"""
        gross = size_usd * (abs(opp.spread_bps) / 10000)
        costs = (
            opp.buy_gas_usd +
            opp.sell_gas_usd +
            opp.bridge_fee_usd +
            opp.slippage_usd +
            gross * 0.001  # ~10bps fees
        )
        return gross - costs
    
    def _estimate_risk(self, opp: 'ArbitrageOpportunity') -> float:
        """
        Estimate risk (volatility of outcome) for risk-adjusted return.
        """
        # Risk is higher when:
        # - Spread is large (more volatile reversion)
        # - Bridge risk is high
        # - MEV risk is high
        # - Duration is long
        
        base_risk = 0.01  # 1% base risk
        
        spread_risk = abs(opp.spread_bps) / 10000 * 0.5
        bridge_risk = opp.bridge_risk_score / 10 * 0.02
        duration_risk = opp.estimated_duration_secs / 1800 * 0.01  # Normalized to 30min
        
        return base_risk + spread_risk + bridge_risk + duration_risk
    
    def _assess_urgency(self, opp: 'ArbitrageOpportunity') -> str:
        """Assess how quickly this signal must be acted on"""
        # High urgency for extreme z-scores
        if abs(opp.spread_zscore) >= 3.0:
            return "immediate"
        elif abs(opp.spread_zscore) >= 2.5:
            return "within_1min"
        elif opp.spread_percentile > 95:
            return "immediate"
        elif opp.spread_percentile > 90:
            return "within_1min"
        return "within_5min"
    
    def _generate_warnings(
        self,
        opp: 'ArbitrageOpportunity',
        confidence: float
    ) -> List[str]:
        """Generate warnings for this signal"""
        warnings = []
        
        if confidence < 0.6:
            warnings.append("Low confidence - consider smaller size")
        
        if opp.bridge_risk_score > 7:
            warnings.append("High bridge risk - consider alternative bridge")
        
        if opp.mev_risk_score > 6:
            warnings.append("MEV risk elevated - use private mempool")
        
        if opp.estimated_duration_secs > 600:
            warnings.append("Long execution window - spread may close before completion")
        
        if abs(opp.spread_zscore) > 4:
            warnings.append("Extremely large spread - possible structural break")
        
        return warnings
    
    def _determine_signal_type(
        self,
        opp: 'ArbitrageOpportunity',
        confidence: float,
        expected_pnl: float,
        warnings: List[str],
    ) -> SignalType:
        """Determine the type of signal to generate"""
        
        # Must be profitable
        if expected_pnl < self.min_profit_usd:
            return SignalType.SKIP
        
        # Must meet confidence threshold
        if confidence < self.min_confidence:
            return SignalType.SKIP
        
        # Must not have critical warnings
        critical_warnings = [w for w in warnings if "structural break" in w.lower()]
        if critical_warnings:
            return SignalType.SKIP
        
        # Direction based on spread
        if opp.direction == "A_TO_B":
            return SignalType.ENTRY_LONG
        else:
            return SignalType.ENTRY_SHORT
    
    def filter_signals(
        self,
        signals: List[TradeSignal],
        top_n: int = 3,
    ) -> List[TradeSignal]:
        """
        Filter and rank signals to find the best opportunities.
        
        Returns top N signals sorted by risk-adjusted expected return.
        """
        # Filter actionable
        actionable = [s for s in signals if s.is_actionable()]
        
        # Sort by risk-adjusted return (descending)
        actionable.sort(key=lambda s: s.risk_adjusted_return, reverse=True)
        
        return actionable[:top_n]
    
    def get_active_signals(self) -> List[TradeSignal]:
        """Get all active (non-expired) signals"""
        now = datetime.now()
        return [
            s for s in self._active_signals.values()
            if s.valid_until > now
        ]
    
    def clear_expired_signals(self) -> None:
        """Remove expired signals"""
        now = datetime.now()
        expired = [
            k for k, s in self._active_signals.items()
            if s.valid_until <= now
        ]
        for k in expired:
            del self._active_signals[k]
