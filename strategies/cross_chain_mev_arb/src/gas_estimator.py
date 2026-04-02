"""
Gas Estimator - Gas cost estimation across multiple chains.
"""

from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class GasQuote:
    """Gas cost quote for a transaction"""
    chain: str
    gas_price_gwei: float
    estimated_gas_units: int
    total_gas_wei: float
    cost_eth: float
    cost_usd: float
    fee_type: str  # "base_fee" | "priority_fee" | "l2_gas"
    timestamp: datetime
    block_number: int = 0
    
    @property
    def total_gas_gwei(self) -> float:
        return self.total_gas_wei / 1e9


class GasEstimator:
    """
    Estimates gas costs for cross-chain arbitrage transactions.
    
    Handles:
    - EIP-1559 gas pricing (base fee + priority fee)
    - L2 gas pricing (sequential + blob)
    - Historical gas tracking for spike detection
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.chain_configs = config.get('chains', {})
        
        # Historical gas tracking
        self._gas_history: Dict[str, deque] = {
            chain: deque(maxlen=100) for chain in self.chain_configs
        }
        
        # Current gas state
        self._current_gas: Dict[str, float] = {}  # chain -> gwei
        self._base_fee_history: Dict[str, deque] = {
            chain: deque(maxlen=50) for chain in self.chain_configs
        }
        
        # ETH price (in production: fetch from oracle)
        self._eth_price_usd = 1800.0
        
    def set_eth_price(self, price_usd: float) -> None:
        """Update ETH/USD price"""
        self._eth_price_usd = price_usd
    
    async def get_gas_quote(
        self,
        chain: str,
        operation: str = "swap",
    ) -> GasQuote:
        """
        Get current gas quote for a chain.
        
        Args:
            chain: Chain identifier
            operation: Type of operation (swap, bridge, flash_loan)
        """
        chain_config = self.chain_configs.get(chain, {})
        gas_type = chain_config.get('gas_price_type', 'base_fee')
        priority_fee = chain_config.get('priority_fee_gwei', 1.0)
        
        # Get estimated gas units for operation
        gas_units = self._get_operation_gas_units(chain, operation)
        
        # Get gas price
        if gas_type == 'l2_gas':
            # L2 chains use different pricing model
            gas_price_gwei = self._get_l2_gas_price(chain)
            total_gas_wei = gas_units * int(gas_price_gwei * 1e9)
        else:
            # EIP-1559: base fee + priority fee
            base_fee = self._get_base_fee(chain)
            gas_price_gwei = base_fee + priority_fee
            total_gas_wei = gas_units * int(gas_price_gwei * 1e9)
        
        cost_eth = total_gas_wei / 1e18
        cost_usd = cost_eth * self._eth_price_usd
        
        # Record history
        self._record_gas_sample(chain, gas_price_gwei, cost_usd)
        
        return GasQuote(
            chain=chain,
            gas_price_gwei=gas_price_gwei,
            estimated_gas_units=gas_units,
            total_gas_wei=total_gas_wei,
            cost_eth=cost_eth,
            cost_usd=cost_usd,
            fee_type=gas_type,
            timestamp=datetime.now(),
        )
    
    def _get_operation_gas_units(self, chain: str, operation: str) -> int:
        """
        Get estimated gas units for an operation on a chain.
        
        These are empirical estimates from mainnet observations.
        """
        # Base gas per operation type (Ethereum mainnet units)
        gas_units = {
            'swap': {
                'ethereum': 150000,     # Uniswap V3 swap
                'arbitrum': 200000,      # L2 overhead
                'optimism': 200000,
                'base': 200000,
                'polygon': 250000,        # High compute costs
            },
            'bridge_out': {
                'ethereum': 200000,
                'arbitrum': 100000,       # withdrawals are cheap
                'optimism': 100000,
                'base': 100000,
                'polygon': 300000,
            },
            'bridge_in': {
                'ethereum': 300000,      # messages from L1
                'arbitrum': 2000000,       # L1->L2 messages expensive
                'optimism': 2000000,
                'base': 2000000,
                'polygon': 500000,
            },
            'flash_loan': {
                'ethereum': 350000,
                'arbitrum': 400000,
                'optimism': 400000,
                'base': 400000,
            },
            'multi_swap': {  # 3-leg arb
                'ethereum': 350000,
                'arbitrum': 450000,
                'optimism': 450000,
                'base': 450000,
            },
        }
        
        return gas_units.get(operation, {}).get(chain, 150000)
    
    def _get_base_fee(self, chain: str) -> float:
        """
        Get current base fee for a chain.
        
        In production: query the chain node.
        In simulation: generate realistic base fee.
        """
        import time
        if chain == 'ethereum':
            # Simulated ETH base fee: 10-50 gwei typical
            base_fee = 20.0 + (int.from_bytes(str(int(time.time()//60)).encode(), 'big') % 10)
            return base_fee
        elif chain in ['arbitrum', 'optimism', 'base']:
            # L2s have very low base fees
            return 0.1
        elif chain == 'polygon':
            return 100.0  # gwei (MATIC gas)
        return 10.0
    
    def _get_l2_gas_price(self, chain: str) -> float:
        """Get L2 gas price in gwei equivalent"""
        # L2 gas is much cheaper
        l2_gas = {
            'arbitrum': 0.1,
            'optimism': 0.01,
            'base': 0.05,
            'polygon': 50.0,  # MATIC denominated
        }
        return l2_gas.get(chain, 1.0)
    
    def _record_gas_sample(self, chain: str, gas_price_gwei: float, cost_usd: float) -> None:
        """Record gas sample for historical tracking"""
        if chain in self._gas_history:
            self._gas_history[chain].append(gas_price_gwei)
        if chain in self._base_fee_history:
            self._base_fee_history[chain].append(gas_price_gwei)
        self._current_gas[chain] = gas_price_gwei
    
    def estimate_swap_gas(self, chain: str, dex: str, size_base: float) -> float:
        """Quick estimate of swap gas cost in USD"""
        quote = self._get_sync_gas_quote(chain, "swap")
        return quote.cost_usd if quote else 10.0
    
    def _get_sync_gas_quote(self, chain: str, operation: str) -> Optional[GasQuote]:
        """Synchronous gas quote (for backtesting)"""
        try:
            return self._sync_gas_quote_cache.get((chain, operation))
        except:
            return None
    
    def is_gas_spike(self, chain: str, threshold_multiplier: float = 3.0) -> bool:
        """
        Check if current gas is spiking (> threshold * 24hr avg).
        
        Used for circuit breaker.
        """
        if chain not in self._gas_history or len(self._gas_history[chain]) < 10:
            return False
        
        history = list(self._gas_history[chain])
        current = self._current_gas.get(chain, 0)
        avg_24h = sum(history) / len(history)
        
        return current > avg_24h * threshold_multiplier
    
    def get_gas_advisory(self, chain: str) -> str:
        """
        Get human-readable gas advisory for a chain.
        
        Returns: "LOW" | "NORMAL" | "HIGH" | "SPIKE"
        """
        if chain not in self._gas_history or len(self._gas_history[chain]) < 10:
            return "NORMAL"
        
        history = list(self._gas_history[chain])
        current = self._current_gas.get(chain, history[-1])
        avg = sum(history) / len(history)
        std = (sum((x - avg) ** 2 for x in history) / len(history)) ** 0.5
        
        if current > avg + 3 * std:
            return "SPIKE"
        elif current > avg + 2 * std:
            return "HIGH"
        elif current < avg * 0.5:
            return "LOW"
        return "NORMAL"
    
    def estimate_3leg_arb_gas(
        self,
        chain_a: str,
        chain_b: str,
        bridge_type: str
    ) -> Tuple[float, float]:
        """
        Estimate total gas for a 3-leg cross-chain arbitrage.
        
        Returns: (gas_a_usd, gas_b_usd)
        """
        # Gas on chain A: swap
        gas_a = self.estimate_swap_gas(chain_a, "uniswap_v3", 0)
        
        # Gas for bridging out
        bridge_out_gas = self._estimate_bridge_out_gas(chain_a, bridge_type)
        
        # Gas on chain B: swap
        gas_b = self.estimate_swap_gas(chain_b, "uniswap_v3", 0)
        
        return gas_a, gas_b
    
    def _estimate_bridge_out_gas(self, chain: str, bridge_type: str) -> float:
        """Estimate bridge-out gas cost in USD"""
        operation = "bridge_out"
        quote = self._get_sync_gas_quote(chain, operation)
        if quote:
            return quote.cost_usd
        
        gas_units = self._get_operation_gas_units(chain, operation)
        gas_price = self._get_base_fee(chain) + 0.5
        cost_eth = (gas_units * gas_price * 1e9) / 1e18
        return cost_eth * self._eth_price_usd
    
    def get_average_gas_24h(self, chain: str) -> float:
        """Get 24h average gas price in gwei"""
        if chain not in self._gas_history:
            return 20.0
        history = list(self._gas_history[chain])
        if not history:
            return 20.0
        return sum(history) / len(history)
    
    # Cache for synchronous use
    _sync_gas_quote_cache: Dict[Tuple[str, str], GasQuote] = {}
