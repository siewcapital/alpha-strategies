"""
Cross-Chain MEV Arbitrage - Arbitrage Opportunity Detector
Detects and evaluates cross-chain arbitrage opportunities.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import numpy as np
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


class OpportunityType(Enum):
    DIRECT_ARB = "direct_arb"           # Buy chain A, sell chain B
    TRIANGULAR_ARB = "triangular_arb"   # Buy A/B, bridge, sell B/C
    FLASH_ARB = "flash_arb"             # Uses flash loan
    CYCLE_ARB = "cycle_arb"             # A -> B -> C -> A


@dataclass
class ArbitrageOpportunity:
    """
    Represents a detected cross-chain arbitrage opportunity.
    """
    opportunity_id: str
    opportunity_type: OpportunityType
    
    # Direction
    buy_chain: str
    sell_chain: str
    buy_dex: str
    sell_dex: str
    pair: str
    direction: str  # "A_TO_B" or "B_TO_A"
    
    # Prices
    buy_price: float
    sell_price: float
    spread_bps: float
    
    # Sizing
    max_trade_size_usd: float
    optimal_trade_size_usd: float
    min_trade_size_usd: float
    
    # Costs
    buy_gas_usd: float
    sell_gas_usd: float
    bridge_fee_usd: float
    slippage_usd: float
    total_cost_usd: float
    
    # Profitability
    gross_profit_usd: float
    net_profit_usd: float
    net_profit_bps: float
    is_profitable: bool
    confidence_score: float  # 0-1
    
    # Timing
    detected_at: datetime
    expires_at: datetime
    estimated_duration_secs: int
    
    # Risk
    bridge_risk_score: float
    mev_risk_score: float
    finality_risk: float
    
    # Z-score metrics
    spread_zscore: float = 0.0
    spread_percentile: float = 0.0
    
    def roi_estimate(self, capital_usd: float) -> float:
        """Estimated ROI if deploying capital_usd"""
        return self.net_profit_usd / capital_usd * 100 if capital_usd > 0 else 0
    
    def profit_per_spread_bps(self) -> float:
        """Net profit per basis point of spread"""
        if self.spread_bps == 0:
            return 0
        return self.net_profit_usd / (abs(self.spread_bps) / 100)
    
    def annualized_roi(
        self,
        capital_usd: float,
        trades_per_day: float = 4.0
    ) -> float:
        """Rough annualized ROI estimate"""
        daily_roi = self.roi_estimate(capital_usd) * trades_per_day
        return daily_roi * 252


@dataclass
class SpreadHistory:
    """Historical spread data for a chain pair"""
    pair: str
    chain_a: str
    chain_b: str
    spreads_bps: deque = field(default_factory=lambda: deque(maxlen=1000))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def add(self, spread_bps: float, timestamp: datetime) -> None:
        self.spreads_bps.append(spread_bps)
        self.timestamps.append(timestamp)
    
    def mean(self) -> float:
        if not self.spreads_bps:
            return 0.0
        return sum(self.spreads_bps) / len(self.spreads_bps)
    
    def std(self) -> float:
        if len(self.spreads_bps) < 2:
            return 1.0
        return np.std(list(self.spreads_bps))
    
    def zscore(self, value: float) -> float:
        s = self.std()
        if s == 0:
            return 0.0
        return (value - self.mean()) / s
    
    def percentile(self, value: float) -> float:
        if not self.spreads_bps:
            return 50.0
        sorted_vals = sorted(self.spreads_bps)
        n = len(sorted_vals)
        idx = sum(1 for v in sorted_vals if v <= value)
        return idx / n * 100
    
    def recent_volatility(self, window: int = 20) -> float:
        """Rolling volatility of spreads"""
        if len(self.spreads_bps) < window:
            return self.std()
        recent = list(self.spreads_bps)[-window:]
        return np.std(recent)


class ArbitrageDetector:
    """
    Detects cross-chain arbitrage opportunities using:
    - Real-time price spread monitoring
    - Statistical spread analysis (z-score)
    - Cost-profitability modeling
    - Risk scoring
    """
    
    def __init__(
        self,
        config: Dict,
        price_monitor: Optional['PriceMonitor'] = None,
        bridge_router: Optional['BridgeRouter'] = None,
        gas_estimator: Optional['GasEstimator'] = None,
    ):
        self.config = config
        self.trading_config = config.get('trading', {})
        self.risk_config = config.get('risk', {})
        
        self.price_monitor = price_monitor
        self.bridge_router = bridge_router
        self.gas_estimator = gas_estimator
        
        # Spread history by pair
        self._spread_histories: Dict[str, SpreadHistory] = {}
        
        # Active opportunities tracking
        self._active_opportunities: Dict[str, ArbitrageOpportunity] = {}
        self._opportunity_counter = 0
        
        # Cooldowns
        self._cooldowns: Dict[str, datetime] = {}  # pair -> last trade time
        
        # Detection parameters
        self.min_spread_bps = self.trading_config.get('arbitrage', {}).get('min_spread_bps', 15)
        self.zscore_entry = self.trading_config.get('arbitrage', {}).get('zscore_entry_threshold', 2.0)
        self.lookback = self.trading_config.get('arbitrage', {}).get('lookback_periods', 500)
        
    async def detect_opportunities(
        self,
        pair: str,
        chain_a: str,
        chain_b: str,
        trade_size_usd: float,
    ) -> List[ArbitrageOpportunity]:
        """
        Main detection function. Scans for arbitrage opportunities.
        
        Returns list of opportunities sorted by expected net profit.
        """
        if not self.price_monitor:
            logger.warning("No price monitor configured")
            return []
        
        # Check cooldowns
        cooldown_key = f"{pair}_{chain_a}_{chain_b}"
        if self._is_in_cooldown(cooldown_key):
            return []
        
        # Get cross-chain spread
        from src.price_monitor import Chain, CrossChainSpread
        
        chain_a_enum = Chain(chain_a)
        chain_b_enum = Chain(chain_b)
        
        spread = await self.price_monitor.get_cross_chain_spread(
            pair, chain_a_enum, chain_b_enum, trade_size_usd
        )
        
        if not spread:
            return []
        
        # Record in history
        history_key = f"{pair}_{chain_a}_{chain_b}"
        if history_key not in self._spread_histories:
            self._spread_histories[history_key] = SpreadHistory(pair, chain_a, chain_b)
        self._spread_histories[history_key].add(spread.spread_bps, datetime.now())
        
        # Build opportunity
        opp = self._build_opportunity(spread, chain_a, chain_b, trade_size_usd)
        
        if opp and opp.is_profitable and opp.confidence_score > 0.6:
            self._active_opportunities[opp.opportunity_id] = opp
            return [opp]
        
        return []
    
    def _build_opportunity(
        self,
        spread: 'CrossChainSpread',
        chain_a: str,
        chain_b: str,
        trade_size_usd: float,
    ) -> Optional[ArbitrageOpportunity]:
        """Build an ArbitrageOpportunity from a CrossChainSpread"""
        
        history_key = f"{spread.pair}_{chain_a}_{chain_b}"
        history = self._spread_histories.get(history_key)
        
        # Calculate z-score and percentile
        zscore = 0.0
        percentile = 50.0
        if history and len(history.spreads_bps) >= 20:
            zscore = history.zscore(spread.spread_bps)
            percentile = history.percentile(spread.spread_bps)
        
        # Determine direction
        if spread.spread_direction == "A_TO_B":
            buy_chain, sell_chain = chain_a, chain_b
            buy_price, sell_price = spread.price_a, spread.price_b
        else:
            buy_chain, sell_chain = chain_b, chain_a
            buy_price, sell_price = spread.price_b, spread.price_a
        
        # Size constraints
        pair_config = self._get_pair_config(spread.pair)
        min_size = pair_config.get('min_trade_usd', 5000)
        max_size = pair_config.get('max_trade_usd', 500000)
        
        # Optimal size based on Kelly or max viable
        optimal_size = min(
            self._calculate_kelly_size(trade_size_usd, spread.spread_bps),
            max_size
        )
        
        # Cost breakdown
        buy_gas = self._estimate_gas(chain_a, "swap", optimal_size)
        sell_gas = self._estimate_gas(chain_b, "swap", optimal_size)
        
        bridge_fee = optimal_size * 0.0008  # ~8 bps average
        slippage = optimal_size * 0.0005     # ~5 bps slippage
        
        total_cost = buy_gas + sell_gas + bridge_fee + slippage
        
        # Gross profit
        gross_profit = optimal_size * (abs(spread.spread_bps) / 10000)
        net_profit = gross_profit - total_cost
        
        # Confidence score based on z-score
        confidence = self._calculate_confidence(zscore, spread.spread_bps)
        
        # Time estimates
        bridge_time = 30 if chain_a == "arbitrum" or chain_b == "arbitrum" else 120
        swap_time = 15
        total_duration = bridge_time + swap_time * 2
        
        self._opportunity_counter += 1
        
        return ArbitrageOpportunity(
            opportunity_id=f"ARB-{self._opportunity_counter:06d}",
            opportunity_type=OpportunityType.DIRECT_ARB,
            buy_chain=buy_chain,
            sell_chain=sell_chain,
            buy_dex="uniswap_v3",
            sell_dex="uniswap_v3",
            pair=spread.pair,
            direction=spread.spread_direction,
            buy_price=buy_price,
            sell_price=sell_price,
            spread_bps=spread.spread_bps,
            max_trade_size_usd=max_size,
            optimal_trade_size_usd=optimal_size,
            min_trade_size_usd=min_size,
            buy_gas_usd=buy_gas,
            sell_gas_usd=sell_gas,
            bridge_fee_usd=bridge_fee,
            slippage_usd=slippage,
            total_cost_usd=total_cost,
            gross_profit_usd=gross_profit,
            net_profit_usd=net_profit,
            net_profit_bps=net_profit / optimal_size * 10000 if optimal_size > 0 else 0,
            is_profitable=net_profit > 0,
            confidence_score=confidence,
            detected_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=total_duration),
            estimated_duration_secs=total_duration,
            bridge_risk_score=5.0,   # Default
            mev_risk_score=5.0,      # Default
            finality_risk=2.0,       # Low for fast bridges
            spread_zscore=zscore,
            spread_percentile=percentile,
        )
    
    def _get_pair_config(self, pair: str) -> Dict:
        """Get configuration for a trading pair"""
        pairs = self.trading_config.get('pairs', [])
        for p in pairs:
            if f"{p.get('base')}/{p.get('quote')}" == pair:
                return p
        return {'min_trade_usd': 5000, 'max_trade_usd': 500000}
    
    def _calculate_kelly_size(
        self,
        max_capital_usd: float,
        spread_bps: float,
        kelly_fraction: float = 0.25
    ) -> float:
        """
        Calculate Kelly-optimal position size.
        
        Kelly % = W - (1-W)/R
        where W = win rate, R = win/loss ratio
        
        Simplified: we use spread magnitude as edge proxy.
        """
        # Win rate proxy from historical spread reversion
        win_rate = 0.55  # Estimated
        
        # If z-score > 2, we expect 80% reversion probability
        # Use fractional Kelly (25% = conservative)
        
        # Edge in bps
        edge = abs(spread_bps)
        cost_bps = 30  # 30 bps all-in cost estimate
        
        if edge <= cost_bps:
            return 0
        
        kelly_pct = kelly_fraction * (edge - cost_bps) / 100  # Simplified
        
        return min(max_capital_usd * kelly_pct, max_capital_usd * 0.15)
    
    def _estimate_gas(
        self,
        chain: str,
        operation: str,
        trade_size_usd: float
    ) -> float:
        """Estimate gas cost in USD"""
        if self.gas_estimator:
            return self.gas_estimator.estimate_swap_gas(chain, operation, trade_size_usd)
        
        # Fallback estimates
        gas_usd = {
            'ethereum': 50.0,
            'arbitrum': 1.0,
            'optimism': 0.5,
            'base': 0.5,
            'polygon': 0.1,
        }
        return gas_usd.get(chain, 5.0)
    
    def _calculate_confidence(self, zscore: float, spread_bps: float) -> float:
        """
        Calculate confidence score (0-1) for an opportunity.
        
        Higher z-score = more extreme spread = higher confidence of reversion
        But very high z-score might indicate structural break
        """
        # Base confidence from z-score
        if zscore < 0:
            zscore = -zscore
        
        if zscore >= 3.0:
            conf = 0.95  # Very extreme
        elif zscore >= 2.5:
            conf = 0.85
        elif zscore >= 2.0:
            conf = 0.75
        elif zscore >= 1.5:
            conf = 0.60
        else:
            conf = 0.40
        
        # Boost for large spread
        if spread_bps > 50:
            conf *= 1.1
        elif spread_bps > 100:
            conf *= 1.2
        
        return min(conf, 0.99)
    
    def _is_in_cooldown(self, key: str) -> bool:
        """Check if pair is in cooldown period"""
        cooldown_seconds = self.trading_config.get('arbitrage', {}).get('cooldown_seconds', 60)
        
        if key in self._cooldowns:
            elapsed = (datetime.now() - self._cooldowns[key]).total_seconds()
            if elapsed < cooldown_seconds:
                return True
        
        self._cooldowns[key] = datetime.now()
        return False
    
    def get_spread_stats(self, pair: str, chain_a: str, chain_b: str) -> Dict:
        """Get spread statistics for a pair"""
        history_key = f"{pair}_{chain_a}_{chain_b}"
        history = self._spread_histories.get(history_key)
        
        if not history:
            return {}
        
        return {
            'mean_bps': history.mean(),
            'std_bps': history.std(),
            'recent_vol': history.recent_volatility(),
            'n_samples': len(history.spreads_bps),
            'current_zscore': history.zscore(history.spreads_bps[-1]) if history.spreads_bps else 0,
            'current_percentile': history.percentile(history.spreads_bps[-1]) if history.spreads_bps else 50,
        }
    
    def get_active_opportunities(self) -> List[ArbitrageOpportunity]:
        """Get all active (non-expired) opportunities"""
        now = datetime.now()
        return [
            opp for opp in self._active_opportunities.values()
            if opp.expires_at > now
        ]
    
    def clear_expired(self) -> None:
        """Remove expired opportunities"""
        now = datetime.now()
        expired = [
            k for k, v in self._active_opportunities.items()
            if v.expires_at <= now
        ]
        for k in expired:
            del self._active_opportunities[k]
