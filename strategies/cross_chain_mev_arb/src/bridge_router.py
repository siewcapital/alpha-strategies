"""
Cross-Chain MEV Arbitrage - Bridge Router
Selects optimal bridge route for cross-chain transfers.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BridgeType(Enum):
    STARGATE = "stargate"
    ACROSS = "across"
    SYNAPSE = "synapse"
    WORMHOLE = "wormhole"
    CANONICAL = "canonical"


class BridgeStatus(Enum):
    AVAILABLE = "available"
    CONGESTED = "congested"
    PAUSED = "paused"
    RISKY = "risky"


@dataclass
class BridgeQuote:
    """Quote for bridging assets across chains"""
    bridge: BridgeType
    source_chain: str
    dest_chain: str
    asset: str
    amount: float           # Amount to bridge (in asset units)
    amount_out_min: float   # Minimum received (after slippage)
    fee_amount: float       # Bridge fee (in asset units)
    fee_usd: float          # Bridge fee (USD)
    estimated_time_secs: int
    gas_cost_dest_usd: float  # Gas cost on destination chain
    total_cost_usd: float
    received_usd: float    # Net received in USD
    reliability_score: float  # 0-10 (TVL, age, audits)
    risk_score: float       # 0-10 (lower is safer)
    
    def net_savings(self, other_quote: 'BridgeQuote') -> float:
        """Compare net received vs another bridge"""
        return self.received_usd - other_quote.received_usd
    
    @property
    def effective_slippage_bps(self) -> float:
        """Effective slippage in bps"""
        if self.amount == 0:
            return 0
        return abs(self.amount_out_min - self.amount) / self.amount * 10000


@dataclass
class BridgeRoute:
    """A complete bridge route from source to destination"""
    source_chain: str
    dest_chain: str
    asset: str
    amount: float
    
    primary_bridge: BridgeQuote
    fallback_bridge: Optional[BridgeQuote] = None
    
    total_cost_usd: float = 0.0
    total_time_secs: int = 0
    risk_adjusted: bool = False
    
    def best_quote(self) -> BridgeQuote:
        return self.primary_bridge


class BridgeRouter:
    """
    Routes cross-chain transfers across multiple bridges.
    
    Selects optimal bridge based on:
    - Net received (fee + gas + slippage)
    - Reliability (TVL, track record, audit status)
    - Speed (time to finality)
    - Risk score
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.bridge_configs = config.get('bridges', {})
        
        # Bridge metadata (in production: fetch from APIs/subgraphs)
        self._bridge_metadata: Dict[BridgeType, Dict] = {
            BridgeType.STARGATE: {
                'name': 'Stargate',
                'avg_time_secs': 30,
                'reliability_score': 9.2,
                'audit_score': 9.5,
                'tvl_score': 9.0,
                'liquidity_threshold_usd': 100_000,
            },
            BridgeType.ACROSS: {
                'name': 'Across',
                'avg_time_secs': 60,
                'reliability_score': 8.8,
                'audit_score': 9.0,
                'tvl_score': 8.5,
                'liquidity_threshold_usd': 50_000,
            },
            BridgeType.SYNAPSE: {
                'name': 'Synapse',
                'avg_time_secs': 180,
                'reliability_score': 8.0,
                'audit_score': 8.5,
                'tvl_score': 7.5,
                'liquidity_threshold_usd': 75_000,
            },
            BridgeType.WORMHOLE: {
                'name': 'Wormhole',
                'avg_time_secs': 900,
                'reliability_score': 7.5,
                'audit_score': 8.0,
                'tvl_score': 8.0,
                'liquidity_threshold_usd': 200_000,
            },
        }
        
        # Dynamic state
        self._bridge_status: Dict[BridgeType, BridgeStatus] = {
            b: BridgeStatus.AVAILABLE for b in BridgeType
        }
        self._tvl_cache: Dict[Tuple[str, str, str], Tuple[float, datetime]] = {}
        
    async def get_quote(
        self,
        source_chain: str,
        dest_chain: str,
        asset: str,
        amount: float,
        asset_price_usd: float,
    ) -> List[BridgeQuote]:
        """
        Get quotes from all enabled bridges for a transfer.
        
        Returns list sorted by net received (best first).
        """
        quotes = []
        
        for bridge_name, bridge_config in self.bridge_configs.items():
            if not bridge_config.get('enabled', False):
                continue
                
            try:
                quote = await self._quote_bridge(
                    bridge_name, source_chain, dest_chain,
                    asset, amount, asset_price_usd
                )
                if quote:
                    quotes.append(quote)
            except Exception as e:
                logger.warning(f"Bridge {bridge_name} quote failed: {e}")
                continue
        
        # Sort by net received (descending)
        quotes.sort(key=lambda q: q.received_usd, reverse=True)
        return quotes
    
    async def get_best_route(
        self,
        source_chain: str,
        dest_chain: str,
        asset: str,
        amount: float,
        asset_price_usd: float,
        prefer_speed: bool = False,
    ) -> Optional[BridgeRoute]:
        """
        Get the best bridge route, with optional fallback.
        """
        quotes = await self.get_quote(source_chain, dest_chain, asset, amount, asset_price_usd)
        
        if not quotes:
            return None
        
        primary = quotes[0]
        fallback = quotes[1] if len(quotes) > 1 else None
        
        route = BridgeRoute(
            source_chain=source_chain,
            dest_chain=dest_chain,
            asset=asset,
            amount=amount,
            primary_bridge=primary,
            fallback_bridge=fallback,
            total_cost_usd=primary.total_cost_usd,
            total_time_secs=primary.estimated_time_secs,
        )
        
        return route
    
    async def _quote_bridge(
        self,
        bridge_name: str,
        source_chain: str,
        dest_chain: str,
        asset: str,
        amount: float,
        asset_price_usd: float,
    ) -> Optional[BridgeQuote]:
        """Generate a quote for a specific bridge"""
        
        bridge_type = BridgeType(bridge_name)
        metadata = self._bridge_metadata.get(bridge_type, {})
        
        # Check if bridge is operational
        if self._bridge_status.get(bridge_type) != BridgeStatus.AVAILABLE:
            return None
        
        # Get TVL for this route (cached)
        tvl_key = (source_chain, dest_chain, asset)
        tvl, tvl_time = self._tvl_cache.get(tvl_key, (0, datetime.min))
        
        # Refresh TVL if stale (> 5 min)
        if (datetime.now() - tvl_time).total_seconds() > 300:
            tvl = self._fetch_tvl_estimate(source_chain, dest_chain, asset)
            self._tvl_cache[tvl_key] = (tvl, datetime.now())
        
        # Check liquidity
        min_liquidity = metadata.get('liquidity_threshold_usd', 100_000)
        if tvl > 0 and tvl < min_liquidity:
            return None
        
        # Calculate fees
        bridge_config = self.bridge_configs.get(bridge_name, {})
        fee_bps = bridge_config.get('fee_bps', 8)
        dest_gas = bridge_config.get('dest_gas', 300000)
        
        fee_amount = amount * (fee_bps / 10000)
        fee_usd = fee_amount * asset_price_usd
        
        # Estimated destination gas cost (simplified)
        gas_price_dest = self._estimate_dest_gas_price(dest_chain)
        gas_cost_dest_usd = dest_gas * gas_price_dest
        
        # Slippage
        max_slippage_bps = bridge_config.get('max_slippage_bps', 50)
        slippage_amount = amount * (max_slippage_bps / 10000)
        amount_out_min = amount - fee_amount - slippage_amount
        
        total_cost_usd = fee_usd + gas_cost_dest_usd
        received_usd = (amount_out_min) * asset_price_usd - gas_cost_dest_usd
        
        # Risk score (lower is safer)
        risk_score = self._calculate_risk_score(bridge_type, tvl)
        reliability_score = metadata.get('reliability_score', 7.0)
        
        return BridgeQuote(
            bridge=bridge_type,
            source_chain=source_chain,
            dest_chain=dest_chain,
            asset=asset,
            amount=amount,
            amount_out_min=amount_out_min,
            fee_amount=fee_amount,
            fee_usd=fee_usd,
            estimated_time_secs=metadata.get('avg_time_secs', 120),
            gas_cost_dest_usd=gas_cost_dest_usd,
            total_cost_usd=total_cost_usd,
            received_usd=received_usd,
            reliability_score=reliability_score,
            risk_score=risk_score,
        )
    
    def _fetch_tvl_estimate(self, source: str, dest: str, asset: str) -> float:
        """
        Fetch TVL estimate for bridge route.
        In production: query bridge subgraphs or APIs.
        For simulation: use deterministic estimate based on asset.
        """
        import hashlib
        h = asset + source + dest
        base_tvl = 50_000_000 if "USDC" in asset else 10_000_000
        noise = (int(hashlib.md5(h.encode()).hexdigest()[:8], 16) % 100 - 50) / 1000
        return base_tvl * (1 + noise)
    
    def _estimate_dest_gas_price(self, chain: str) -> float:
        """Estimate gas price on destination chain in USD"""
        gas_prices = {
            'ethereum': 0.00003,    # ~30 gwei * ETH $1800 / 1e9
            'arbitrum': 0.000001,   # ~1 gwei * ETH $1800 / 1e9
            'optimism': 0.0000005,  # ~0.5 gwei * ETH $1800 / 1e9
            'base': 0.000001,       # ~1 gwei
            'polygon': 0.0000001,   # ~100 gwei * MATIC $0.8 / 1e9
        }
        return gas_prices.get(chain, 0.000001)
    
    def _calculate_risk_score(self, bridge_type: BridgeType, tvl: float) -> float:
        """Calculate bridge risk score 0-10 (lower = safer)"""
        metadata = self._bridge_metadata.get(bridge_type, {})
        
        base_risk = 10.0
        
        # Reduce risk for high TVL
        if tvl > 100_000_000:
            base_risk -= 3.0
        elif tvl > 10_000_000:
            base_risk -= 2.0
        elif tvl > 1_000_000:
            base_risk -= 1.0
        
        # Reduce risk for good audit score
        audit_score = metadata.get('audit_score', 7.0)
        base_risk -= (audit_score - 5) / 2
        
        # Wormhole gets +1 risk (guardian model concerns)
        if bridge_type == BridgeType.WORMHOLE:
            base_risk += 1.0
        
        return max(0.0, min(10.0, base_risk))
    
    def set_bridge_status(self, bridge: BridgeType, status: BridgeStatus) -> None:
        """Update bridge operational status"""
        self._bridge_status[bridge] = status
        logger.info(f"Bridge {bridge.value} status: {status.value}")
    
    def get_bridge_status(self, bridge: BridgeType) -> BridgeStatus:
        return self._bridge_status.get(bridge, BridgeStatus.UNKNOWN)
    
    def is_bridge_available(self, bridge: BridgeType) -> bool:
        return self._bridge_status.get(bridge) == BridgeStatus.AVAILABLE
    
    def get_supported_chains(self, bridge: BridgeType) -> List[str]:
        """Get chains supported by a bridge"""
        # Simplified - in production, fetch from bridge config
        all_chains = ['ethereum', 'arbitrum', 'optimism', 'base', 'polygon']
        if bridge == BridgeType.CANONICAL:
            return ['ethereum', 'arbitrum', 'optimism', 'base']  # Native bridges
        return all_chains
