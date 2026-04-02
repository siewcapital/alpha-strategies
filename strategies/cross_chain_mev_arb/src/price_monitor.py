"""
Cross-Chain Price Monitor
Monitors DEX prices for the same asset across multiple chains in real-time.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import logging
import time
from datetime import datetime, timedelta
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


class Chain(Enum):
    ETHEREUM = "ethereum"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    POLYGON = "polygon"


class DEX(Enum):
    UNISWAP_V3 = "uniswap_v3"
    SUSHISWAP = "sushiswap"
    CURVE = "curve"
    Balancer = "balancer"


@dataclass
class DEXQuote:
    """Best quote from a specific DEX on a specific chain"""
    chain: Chain
    dex: DEX
    base_asset: str
    quote_asset: str
    
    bid_price: float      # Best bid (sell base) price
    ask_price: float      # Best ask (buy base) price
    bid_liquidity: float   # Liquidity at bid (in base units)
    ask_liquidity: float   # Liquidity at ask (in base units)
    gas_cost_quote_usd: float  # Gas cost to execute (USD)
    timestamp: datetime
    
    # Quality metrics
    price_impact_bps: float = 0.0
    slippage_bps: float = 0.0
    
    def mid_price(self) -> float:
        return (self.bid_price + self.ask_price) / 2.0
    
    def spread_bps(self) -> float:
        if self.ask_price == 0:
            return 0.0
        return (self.ask_price - self.bid_price) / self.ask_price * 10000


@dataclass 
class CrossChainSpread:
    """Represents the price spread between two chains for the same asset"""
    pair: str              # e.g., "WETH/USDC"
    chain_a: Chain
    chain_b: Chain
    
    price_a: float         # Price on chain A (mid price)
    price_b: float         # Price on chain B (mid price)
    
    spread_bps: float      # (price_b - price_a) / price_a * 10000
    spread_direction: str  # "A_TO_B" or "B_TO_A"
    
    # Execution estimates
    estimated_buy_gas_usd: float = 0.0
    estimated_sell_gas_usd: float = 0.0
    estimated_bridge_fee_usd: float = 0.0
    estimated_slippage_usd: float = 0.0
    total_cost_usd: float = 0.0
    
    # Net economics
    gross_profit_usd: float = 0.0
    net_profit_usd: float = 0.0
    profitable: bool = False
    
    timestamp: datetime = field(default_factory=datetime.now)
    
    def calculate_economics(self, trade_size_usd: float) -> None:
        """Calculate full economics for a given trade size"""
        self.gross_profit_usd = trade_size_usd * (abs(self.spread_bps) / 10000)
        self.total_cost_usd = (
            self.estimated_buy_gas_usd +
            self.estimated_sell_gas_usd +
            self.estimated_bridge_fee_usd +
            self.estimated_slippage_usd
        )
        self.net_profit_usd = self.gross_profit_usd - self.total_cost_usd
        self.profitable = self.net_profit_usd > 0


class PriceMonitor:
    """
    Real-time price monitor for cross-chain DEX prices.
    
    In production: connects to chain nodes, queries DEX contracts directly.
    In backtest/simulation: uses price feeds or synthetic data.
    """
    
    def __init__(
        self,
        chain_configs: Dict[Chain, Dict],
        dex_configs: Dict[str, List[Dict]],
        gas_estimator: Optional['GasEstimator'] = None,
    ):
        self.chain_configs = chain_configs
        self.dex_configs = dex_configs
        self.gas_estimator = gas_estimator
        
        # Price cache: chain -> dex -> pair -> quote
        self._quotes: Dict[Chain, Dict[str, DEXQuote]] = {}
        self._spread_history: deque = deque(maxlen=1000)
        
        # Historical spread data for z-score
        self._spread_series: Dict[str, deque] = {}  # pair -> spread history
        
        self._running = False
        self._lock = asyncio.Lock()
        
    async def start(self) -> None:
        """Start the price monitoring loop"""
        self._running = True
        logger.info("Price monitor started")
        
    async def stop(self) -> None:
        """Stop the price monitor"""
        self._running = False
        logger.info("Price monitor stopped")
        
    async def get_quote(
        self,
        chain: Chain,
        dex: DEX,
        pair: str,
        side: str,  # "buy" or "sell"
        size_base: float
    ) -> Optional[DEXQuote]:
        """
        Get a quote for a trade on a specific chain/DEX.
        
        In production this calls the DEX router contract.
        In simulation, returns synthetic quote.
        """
        base_asset, quote_asset = pair.split("/")
        
        # Simulated price (in production: query DEX contracts)
        mid_price = self._get_simulated_price(chain, base_asset, quote_asset)
        
        # Apply DEX-specific spread
        dex_spread = self._get_dex_spread(dex)
        bid_price = mid_price * (1 - dex_spread / 2)
        ask_price = mid_price * (1 + dex_spread / 2)
        
        # Estimate liquidity (in production: query pool reserves)
        liquidity = self._estimate_liquidity(chain, dex, pair)
        
        # Gas cost estimate
        gas_usd = 0.0
        if self.gas_estimator:
            gas_usd = self.gas_estimator.estimate_swap_gas(chain, dex, size_base)
        
        return DEXQuote(
            chain=chain,
            dex=dex,
            base_asset=base_asset,
            quote_asset=quote_asset,
            bid_price=bid_price,
            ask_price=ask_price,
            bid_liquidity=liquidity,
            ask_liquidity=liquidity,
            gas_cost_quote_usd=gas_usd,
            timestamp=datetime.now(),
        )
    
    def _get_simulated_price(self, chain: Chain, base: str, quote: str) -> float:
        """Get simulated price for backtesting. Replace with real data in production."""
        import hashlib
        # Deterministic pseudo-random price based on chain + asset
        h = hashlib.sha256(f"{chain.value}_{base}_{quote}_{time.time()//10}".encode()).digest()
        base_price = 1800 if base == "WETH" else (62000 if base == "WBTC" else 1.0)
        noise = (int.from_bytes(h[:4], 'big') % 1000 - 500) / 100000
        return base_price * (1 + noise)
    
    def _get_dex_spread(self, dex: DEX) -> float:
        """Get typical spread for a DEX in bps"""
        spreads = {
            DEX.UNISWAP_V3: 3,    # 0.03% for major tokens
            DEX.SUSHISWAP: 5,     # 0.05%
            DEX.CURVE: 2,         # 0.02% for stablecoins
            DEX.Balancer: 4,
        }
        return spreads.get(dex, 5)
    
    def _estimate_liquidity(self, chain: Chain, dex: DEX, pair: str) -> float:
        """Estimate available liquidity in base units"""
        # Rough TVL estimates per chain
        tvl_multipliers = {
            Chain.ETHEREUM: 10.0,
            Chain.ARBITRUM: 3.0,
            Chain.OPTIMISM: 2.0,
            Chain.BASE: 4.0,
        }
        mult = tvl_multipliers.get(chain, 1.0)
        base = 1000 if "ETH" in pair else (10 if "BTC" in pair else 1000000)
        return base * mult * (0.5 + (time.time() % 100) / 100)
    
    async def get_cross_chain_spread(
        self,
        pair: str,
        chain_a: Chain,
        chain_b: Chain,
        trade_size_usd: float,
    ) -> Optional[CrossChainSpread]:
        """
        Calculate the current cross-chain spread for a trading pair.
        This is the core function that identifies arbitrage opportunities.
        """
        async with self._lock:
            # Get quotes from both chains
            best_dex_a = await self._get_best_dex_quote(chain_a, pair, trade_size_usd)
            best_dex_b = await self._get_best_dex_quote(chain_b, pair, trade_size_usd)
            
            if not best_dex_a or not best_dex_b:
                return None
            
            # Determine direction
            price_a = best_dex_a.mid_price()
            price_b = best_dex_b.mid_price()
            spread_bps = (price_b - price_a) / price_a * 10000
            
            spread = CrossChainSpread(
                pair=pair,
                chain_a=chain_a,
                chain_b=chain_b,
                price_a=price_a,
                price_b=price_b,
                spread_bps=spread_bps,
                spread_direction="A_TO_B" if spread_bps > 0 else "B_TO_A",
                estimated_buy_gas_usd=best_dex_a.gas_cost_quote_usd if spread_bps > 0 else best_dex_b.gas_cost_quote_usd,
                estimated_sell_gas_usd=best_dex_b.gas_cost_quote_usd if spread_bps > 0 else best_dex_a.gas_cost_quote_usd,
            )
            
            spread.calculate_economics(trade_size_usd)
            
            # Record history for z-score
            if pair not in self._spread_series:
                self._spread_series[pair] = deque(maxlen=500)
            self._spread_series[pair].append(spread_bps)
            
            return spread
    
    async def _get_best_dex_quote(
        self,
        chain: Chain,
        pair: str,
        size_usd: float
    ) -> Optional[DEXQuote]:
        """Get the best quote across all DEXs on a chain"""
        base_asset = pair.split("/")[0]
        size_base = size_usd / self._get_simulated_price(chain, base_asset, pair.split("/")[1])
        
        best_quote = None
        best_slippage = float('inf')
        
        for dex_name, dexes in self.dex_configs.items():
            if chain.value in dexes:
                for dex_info in dexes[chain.value]:
                    dex = DEX(dex_info['name'])
                    quote = await self.get_quote(chain, dex, pair, "buy", size_base)
                    if quote and quote.slippage_bps < best_slippage:
                        best_slippage = quote.slippage_bps
                        best_quote = quote
        
        return best_quote
    
    def get_zscore(self, pair: str) -> Optional[float]:
        """Calculate z-score of current spread vs historical"""
        if pair not in self._spread_series:
            return None
        series = list(self._spread_series[pair])
        if len(series) < 30:
            return None
        
        mean = np.mean(series)
        std = np.std(series)
        current = series[-1] if series else 0
        
        if std == 0:
            return 0.0
        return (current - mean) / std
    
    def get_spread_stats(self, pair: str) -> Dict:
        """Get historical spread statistics for a pair"""
        if pair not in self._spread_series:
            return {}
        series = list(self._spread_series[pair])
        if len(series) < 2:
            return {}
        return {
            'mean': np.mean(series),
            'std': np.std(series),
            'min': np.min(series),
            'max': np.max(series),
            'median': np.median(series),
            'current': series[-1] if series else 0,
            'zscore': self.get_zscore(pair),
            'n': len(series),
        }
    
    def get_monitored_chains(self) -> List[Chain]:
        return list(self.chain_configs.keys())
    
    def is_running(self) -> bool:
        return self._running
