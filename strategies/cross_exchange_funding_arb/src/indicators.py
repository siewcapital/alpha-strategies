"""
Cross-Exchange Funding Rate Arbitrage - Indicators Module
Calculates funding rate differentials, opportunity scores, and predictive signals.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, NamedTuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class OpportunityType(Enum):
    """Types of funding arbitrage opportunities."""
    CROSS_EXCHANGE = "cross_exchange"
    CONVERGENCE = "convergence"
    DIVERGENCE = "divergence"


@dataclass
class FundingRate:
    """Represents funding rate data for an exchange."""
    exchange: str
    symbol: str
    funding_rate: float
    next_funding_time: pd.Timestamp
    predicted_rate: Optional[float] = None
    premium_index: Optional[float] = None
    interest_rate: float = 0.0001  # 0.01% default
    
    @property
    def annualized_rate(self) -> float:
        """Convert 8-hour rate to annualized APR."""
        return self.funding_rate * 3 * 365
    
    @property
    def is_positive(self) -> bool:
        return self.funding_rate > 0


@dataclass  
class FundingDifferential:
    """Represents a funding rate differential between two exchanges."""
    symbol: str
    long_exchange: str
    short_exchange: str
    long_funding: float
    short_funding: float
    differential: float
    annualized_diff: float
    opportunity_score: float
    confidence: float
    
    def __post_init__(self):
        self.differential = self.short_funding - self.long_funding
        self.annualized_diff = self.differential * 3 * 365


class FundingRateCalculator:
    """
    Calculates funding rates, differentials, and opportunity metrics.
    """
    
    def __init__(
        self,
        min_differential: float = 0.0001,  # 0.01% minimum
        lookback_periods: int = 30,
        prediction_window: int = 3
    ):
        self.min_differential = min_differential
        self.lookback_periods = lookback_periods
        self.prediction_window = prediction_window
        self._funding_history: Dict[str, pd.DataFrame] = {}
        
    def add_funding_data(
        self,
        exchange: str,
        symbol: str,
        timestamp: pd.Timestamp,
        funding_rate: float,
        premium_index: Optional[float] = None
    ) -> None:
        """Add funding rate observation to history."""
        key = f"{exchange}:{symbol}"
        
        if key not in self._funding_history:
            self._funding_history[key] = pd.DataFrame(
                columns=['timestamp', 'funding_rate', 'premium_index']
            )
        
        new_row = pd.DataFrame([{
            'timestamp': timestamp,
            'funding_rate': funding_rate,
            'premium_index': premium_index
        }])
        
        self._funding_history[key] = pd.concat(
            [self._funding_history[key], new_row],
            ignore_index=True
        )
        
        # Keep only recent history
        if len(self._funding_history[key]) > self.lookback_periods * 2:
            self._funding_history[key] = self._funding_history[key].iloc[-self.lookback_periods:]
    
    def calculate_differentials(
        self,
        symbol: str,
        exchanges: List[str],
        current_rates: Dict[str, FundingRate]
    ) -> List[FundingDifferential]:
        """
        Calculate all pairwise funding differentials for a symbol.
        
        Returns opportunities sorted by annualized differential.
        """
        opportunities = []
        
        for i, ex_a in enumerate(exchanges):
            for ex_b in exchanges[i+1:]:
                if ex_a not in current_rates or ex_b not in current_rates:
                    continue
                
                rate_a = current_rates[ex_a]
                rate_b = current_rates[ex_b]
                
                diff = rate_a.funding_rate - rate_b.funding_rate
                
                if abs(diff) < self.min_differential:
                    continue
                
                # Determine long/short based on funding differential
                if diff > 0:  # A pays more → Short A, Long B
                    opp = FundingDifferential(
                        symbol=symbol,
                        long_exchange=ex_b,
                        short_exchange=ex_a,
                        long_funding=rate_b.funding_rate,
                        short_funding=rate_a.funding_rate,
                        differential=0.0,  # Calculated in post_init
                        annualized_diff=0.0,
                        opportunity_score=0.0,
                        confidence=0.0
                    )
                else:  # B pays more → Short B, Long A
                    opp = FundingDifferential(
                        symbol=symbol,
                        long_exchange=ex_a,
                        short_exchange=ex_b,
                        long_funding=rate_a.funding_rate,
                        short_funding=rate_b.funding_rate,
                        differential=0.0,
                        annualized_diff=0.0,
                        opportunity_score=0.0,
                        confidence=0.0
                    )
                
                # Calculate opportunity metrics
                opp.opportunity_score = self._calculate_opportunity_score(opp)
                opp.confidence = self._calculate_confidence(opp, current_rates)
                
                opportunities.append(opp)
        
        # Sort by opportunity score (descending)
        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)
        return opportunities
    
    def _calculate_opportunity_score(self, opp: FundingDifferential) -> float:
        """
        Calculate composite opportunity score.
        
        Factors:
        - Differential magnitude (annualized)
        - Historical persistence of differential
        - Volatility-adjusted return
        """
        base_score = abs(opp.annualized_diff)
        
        # Adjust for historical persistence
        persistence_factor = self._calculate_persistence_factor(
            opp.symbol, opp.long_exchange, opp.short_exchange
        )
        
        # Volatility adjustment
        vol_adjustment = self._calculate_volatility_adjustment(
            opp.symbol, opp.long_exchange, opp.short_exchange
        )
        
        score = base_score * persistence_factor * vol_adjustment
        return score
    
    def _calculate_persistence_factor(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str
    ) -> float:
        """Calculate how persistent the funding differential has been."""
        key_long = f"{long_exchange}:{symbol}"
        key_short = f"{short_exchange}:{symbol}"
        
        if key_long not in self._funding_history or key_short not in self._funding_history:
            return 0.5  # Neutral if no history
        
        hist_long = self._funding_history[key_long]
        hist_short = self._funding_history[key_short]
        
        if len(hist_long) < 3 or len(hist_short) < 3:
            return 0.5
        
        # Calculate historical differentials
        recent_diffs = []
        for i in range(min(len(hist_long), len(hist_short))):
            diff = hist_short.iloc[i]['funding_rate'] - hist_long.iloc[i]['funding_rate']
            recent_diffs.append(diff)
        
        if not recent_diffs:
            return 0.5
        
        # Check sign consistency (persistence)
        current_sign = np.sign(recent_diffs[-1])
        consistent_periods = sum(1 for d in recent_diffs if np.sign(d) == current_sign)
        persistence = consistent_periods / len(recent_diffs)
        
        return 0.5 + 0.5 * persistence  # Scale to 0.5-1.0
    
    def _calculate_volatility_adjustment(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str
    ) -> float:
        """Adjust score based on funding rate volatility."""
        key_long = f"{long_exchange}:{symbol}"
        key_short = f"{short_exchange}:{symbol}"
        
        volatilities = []
        for key in [key_long, key_short]:
            if key in self._funding_history and len(self._funding_history[key]) >= 3:
                hist = self._funding_history[key]['funding_rate']
                vol = hist.std()
                volatilities.append(vol)
        
        if not volatilities:
            return 1.0
        
        avg_vol = np.mean(volatilities)
        # Higher volatility = lower score (less predictable)
        adjustment = 1.0 / (1.0 + avg_vol * 100)
        
        return max(0.3, adjustment)  # Floor at 0.3
    
    def _calculate_confidence(
        self,
        opp: FundingDifferential,
        current_rates: Dict[str, FundingRate]
    ) -> float:
        """Calculate confidence level for the opportunity."""
        confidence_factors = []
        
        # Factor 1: Differential magnitude (larger = more confident)
        mag_score = min(abs(opp.differential) / 0.001, 1.0)
        confidence_factors.append(mag_score)
        
        # Factor 2: Data freshness (assumed current)
        confidence_factors.append(1.0)
        
        # Factor 3: Historical prediction accuracy
        pred_accuracy = self._calculate_prediction_accuracy(
            opp.symbol, opp.long_exchange, opp.short_exchange
        )
        confidence_factors.append(pred_accuracy)
        
        return np.mean(confidence_factors)
    
    def _calculate_prediction_accuracy(
        self,
        symbol: str,
        long_exchange: str,
        short_exchange: str
    ) -> float:
        """Calculate historical prediction accuracy for funding rates."""
        # Simplified - would use actual predictions vs outcomes
        return 0.7  # Default moderate confidence
    
    def predict_next_funding(
        self,
        exchange: str,
        symbol: str,
        current_premium: float,
        current_interest: float = 0.0001
    ) -> Optional[float]:
        """
        Predict next funding rate based on premium index trend.
        
        Most exchanges use: Funding = Premium + Interest
        """
        key = f"{exchange}:{symbol}"
        
        if key not in self._funding_history:
            return None
        
        hist = self._funding_history[key]
        if len(hist) < 3:
            return current_premium + current_interest
        
        # Simple trend extrapolation
        recent_premiums = hist['premium_index'].dropna()
        if len(recent_premiums) >= 3:
            trend = (recent_premiums.iloc[-1] - recent_premiums.iloc[0]) / len(recent_premiums)
            predicted_premium = current_premium + trend * self.prediction_window
        else:
            predicted_premium = current_premium
        
        return predicted_premium + current_interest
    
    def get_funding_statistics(
        self,
        exchange: str,
        symbol: str
    ) -> Dict[str, float]:
        """Get funding rate statistics for analysis."""
        key = f"{exchange}:{symbol}"
        
        if key not in self._funding_history or len(self._funding_history[key]) < 2:
            return {
                'mean': 0.0,
                'std': 0.0,
                'min': 0.0,
                'max': 0.0,
                'annualized_mean': 0.0
            }
        
        hist = self._funding_history[key]['funding_rate']
        
        return {
            'mean': float(hist.mean()),
            'std': float(hist.std()),
            'min': float(hist.min()),
            'max': float(hist.max()),
            'annualized_mean': float(hist.mean() * 3 * 365)
        }


class OpportunityFilter:
    """
    Filters and ranks funding arbitrage opportunities.
    """
    
    def __init__(
        self,
        min_annualized_return: float = 0.05,  # 5%
        min_confidence: float = 0.6,
        max_funding_volatility: float = 0.001,  # 0.1%
        max_position_heat: float = 0.8
    ):
        self.min_annualized_return = min_annualized_return
        self.min_confidence = min_confidence
        self.max_funding_volatility = max_funding_volatility
        self.max_position_heat = max_position_heat
    
    def filter_opportunities(
        self,
        opportunities: List[FundingDifferential],
        portfolio_heat: float = 0.0
    ) -> List[FundingDifferential]:
        """Filter opportunities based on criteria."""
        filtered = []
        
        for opp in opportunities:
            # Check minimum return
            if abs(opp.annualized_diff) < self.min_annualized_return:
                continue
            
            # Check confidence
            if opp.confidence < self.min_confidence:
                continue
            
            # Check portfolio heat
            if portfolio_heat > self.max_position_heat:
                continue
            
            filtered.append(opp)
        
        return filtered
    
    def rank_opportunities(
        self,
        opportunities: List[FundingDifferential]
    ) -> List[Tuple[int, FundingDifferential, float]]:
        """
        Rank opportunities with composite score.
        
        Returns: List of (rank, opportunity, final_score)
        """
        scored = []
        
        for opp in opportunities:
            # Risk-adjusted score
            risk_adjusted = opp.opportunity_score * opp.confidence
            scored.append((opp, risk_adjusted))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        
        # Add rankings
        ranked = [
            (i+1, opp, score)
            for i, (opp, score) in enumerate(scored)
        ]
        
        return ranked
