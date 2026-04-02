"""
Cross-Chain MEV Arbitrage - Risk Manager
Position sizing, circuit breakers, drawdown protection, and bridge risk management.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from datetime import datetime, timedelta, date
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


class RiskStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    CIRCUIT_BREAKER = "circuit_breaker"
    MAX_POSITION = "max_position"
    GAS_SPIKE = "gas_spike"
    DRAWADOWN_LIMIT = "drawdown_limit"


@dataclass
class RiskMetrics:
    """Current risk metrics snapshot"""
    daily_trades: int = 0
    concurrent_trades: int = 0
    bridge_exposure_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    total_pnl_usd: float = 0.0
    portfolio_value_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    current_gas_gwei: Dict[str, float] = field(default_factory=dict)
    avg_gas_24h: Dict[str, float] = field(default_factory=dict)
    
    @property
    def bridge_exposure_pct(self) -> float:
        if self.portfolio_value_usd == 0:
            return 0.0
        return self.bridge_exposure_usd / self.portfolio_value_usd


@dataclass
class RiskCheckResult:
    """Result of a risk check"""
    allowed: bool
    status: RiskStatus
    message: str
    reduction_factor: float = 1.0  # Scale position by this factor


class RiskManager:
    """
    Comprehensive risk management for cross-chain arbitrage.
    
    Handles:
    - Position sizing (Kelly + risk limits)
    - Daily/lifetime loss limits
    - Circuit breakers (gas spikes, drawdown)
    - Bridge risk scoring and limits
    - MEV risk assessment
    - Concurrent trade limits
    """
    
    def __init__(self, config: Dict, initial_capital: float = 100_000):
        self.config = config
        self.risk_config = config.get('risk', {})
        
        # Capital tracking
        self.initial_capital = initial_capital
        self.portfolio_value = initial_capital
        self.peak_portfolio_value = initial_capital
        
        # Daily tracking
        self._daily_pnl: Dict[date, float] = {}
        self._daily_trades: Dict[date, int] = {}
        self._today_date = date.today()
        
        # Concurrent positions
        self._active_positions: Dict[str, dict] = {}
        
        # Bridge exposure
        self._bridge_exposure_usd = 0.0
        
        # Loss tracking
        self._trade_history: deque = deque(maxlen=1000)
        
        # Circuit breakers
        self._circuit_breakers: Dict[str, datetime] = {}
        
        # Gas spike tracking
        self._gas_spike_chains: Dict[str, bool] = {}
        
        # Stop loss tracking
        self._stop_loss_triggered = False
        self._max_drawdown_triggered = False
        
        # Limits from config
        self.max_daily_trades = self.risk_config.get('max_daily_trades', 20)
        self.max_concurrent_trades = self.risk_config.get('max_concurrent_trades', 3)
        self.max_bridge_exposure_pct = self.risk_config.get('max_bridge_exposure_pct', 0.20)
        self.max_daily_loss_pct = self.risk_config.get('max_daily_loss_pct', 0.03)
        self.max_drawdown_pct = self.risk_config.get('max_drawdown_pct', 0.10)
        self.stop_loss_bps = self.risk_config.get('stop_loss_bps', 50)
        self.gas_spike_multiplier = self.risk_config.get('gas_spike_multiplier', 3.0)
        
        logger.info(f"RiskManager initialized: capital=${initial_capital:,.0f}")
    
    def check_trade(
        self,
        opportunity: 'ArbitrageOpportunity',
        gas_estimator: Optional['GasEstimator'] = None,
    ) -> RiskCheckResult:
        """
        Comprehensive risk check before executing a trade.
        
        Returns RiskCheckResult with allowed status and any position reduction.
        """
        # Reset daily counters if new day
        self._reset_daily()
        
        # 1. Daily trade limit
        if self._daily_trades.get(self._today_date, 0) >= self.max_daily_trades:
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.CIRCUIT_BREAKER,
                message=f"Daily trade limit ({self.max_daily_trades}) reached"
            )
        
        # 2. Concurrent position limit
        if len(self._active_positions) >= self.max_concurrent_trades:
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.MAX_POSITION,
                message=f"Max concurrent trades ({self.max_concurrent_trades}) active"
            )
        
        # 3. Circuit breaker check
        if self._is_circuit_breaker_active():
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.CIRCUIT_BREAKER,
                message="Circuit breaker is active"
            )
        
        # 4. Stop loss check
        if self._check_stop_loss():
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.DRAWADOWN_LIMIT,
                message="Stop loss triggered"
            )
        
        # 5. Drawdown limit
        if self._check_drawdown_limit():
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.DRAWADOWN_LIMIT,
                message="Max drawdown limit reached"
            )
        
        # 6. Gas spike check
        if gas_estimator:
            for chain in [opportunity.buy_chain, opportunity.sell_chain]:
                if gas_estimator.is_gas_spike(chain, self.gas_spike_multiplier):
                    self._gas_spike_chains[chain] = True
                    return RiskCheckResult(
                        allowed=False,
                        status=RiskStatus.GAS_SPIKE,
                        message=f"Gas spike detected on {chain}"
                    )
        
        # 7. Bridge exposure check
        required_bridge_exp = opportunity.optimal_trade_size_usd * 0.5  # ~50% in bridge
        if self._bridge_exposure_usd + required_bridge_exp > self.portfolio_value * self.max_bridge_exposure_pct:
            # Scale down position
            available = self.portfolio_value * self.max_bridge_exposure_pct - self._bridge_exposure_usd
            scale = min(1.0, available / (opportunity.optimal_trade_size_usd * 0.5))
            if scale < 0.2:
                return RiskCheckResult(
                    allowed=False,
                    status=RiskStatus.MAX_POSITION,
                    message="Bridge exposure limit reached"
                )
            
            logger.warning(f"Position scaled by {scale:.1%} due to bridge exposure limit")
            return RiskCheckResult(
                allowed=True,
                status=RiskStatus.WARNING,
                message=f"Position scaled to {scale:.1%}",
                reduction_factor=scale
            )
        
        # 8. Daily loss limit
        daily_loss = -self._daily_pnl.get(self._today_date, 0)
        if daily_loss > self.portfolio_value * self.max_daily_loss_pct:
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.DRAWADOWN_LIMIT,
                message=f"Daily loss limit ({self.max_daily_loss_pct:.1%}) reached"
            )
        
        # All checks passed
        return RiskCheckResult(
            allowed=True,
            status=RiskStatus.OK,
            message="All risk checks passed"
        )
    
    def check_position_exit(
        self,
        position_id: str,
        current_pnl_usd: float,
    ) -> Tuple[bool, str]:
        """
        Check if a position should be exited.
        
        Returns: (should_exit, reason)
        """
        if position_id not in self._active_positions:
            return False, "Position not found"
        
        pos = self._active_positions[position_id]
        
        # Stop loss check
        entry_value = pos['entry_value']
        pnl_pct = current_pnl_usd / entry_value
        if pnl_pct < -self.stop_loss_bps / 10000:
            return True, f"Stop loss triggered: {pnl_pct*100:.2f}%"
        
        # Time-based exit
        max_hold = self.risk_config.get('max_hold_seconds', 1800)
        elapsed = (datetime.now() - pos['entry_time']).total_seconds()
        if elapsed > max_hold:
            return True, f"Max hold time ({max_hold}s) exceeded"
        
        # Take profit (optional)
        if current_pnl_usd > entry_value * 0.01:  # 1% take profit
            return True, f"Take profit: {pnl_pct*100:.2f}%"
        
        return False, ""
    
    def record_trade(
        self,
        opportunity_id: str,
        opportunity: 'ArbitrageOpportunity',
        executed_size_usd: float,
        actual_pnl_usd: float,
        status: str,  # "success" | "failed" | "partial"
        failure_reason: str = "",
    ) -> None:
        """Record a completed trade for risk tracking"""
        self._daily_trades[self._today_date] = self._daily_trades.get(self._today_date, 0) + 1
        self._daily_pnl[self._today_date] = self._daily_pnl.get(self._today_date, 0) + actual_pnl_usd
        
        # Update portfolio value
        self.portfolio_value += actual_pnl_usd
        if self.portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = self.portfolio_value
        
        # Update bridge exposure
        if opportunity_id in self._active_positions:
            del self._active_positions[opportunity_id]
        
        # Record in history
        self._trade_history.append({
            'timestamp': datetime.now(),
            'opportunity_id': opportunity_id,
            'pair': opportunity.pair,
            'size_usd': executed_size_usd,
            'pnl_usd': actual_pnl_usd,
            'status': status,
            'failure_reason': failure_reason,
            'buy_chain': opportunity.buy_chain,
            'sell_chain': opportunity.sell_chain,
        })
        
        logger.info(
            f"Trade recorded: {opportunity_id} | "
            f"PnL: ${actual_pnl_usd:,.2f} | "
            f"Portfolio: ${self.portfolio_value:,.2f} | "
            f"Status: {status}"
        )
    
    def open_position(
        self,
        opportunity_id: str,
        opportunity: 'ArbitrageOpportunity',
        executed_size_usd: float,
    ) -> None:
        """Record position opening"""
        self._active_positions[opportunity_id] = {
            'opportunity': opportunity,
            'size_usd': executed_size_usd,
            'entry_value': executed_size_usd,
            'entry_time': datetime.now(),
            'bridge_exposure': executed_size_usd * 0.5,
        }
        self._bridge_exposure_usd += executed_size_usd * 0.5
    
    def get_metrics(self) -> RiskMetrics:
        """Get current risk metrics"""
        return RiskMetrics(
            daily_trades=self._daily_trades.get(self._today_date, 0),
            concurrent_trades=len(self._active_positions),
            bridge_exposure_usd=self._bridge_exposure_usd,
            daily_pnl_usd=self._daily_pnl.get(self._today_date, 0),
            total_pnl_usd=self.portfolio_value - self.initial_capital,
            portfolio_value_usd=self.portfolio_value,
            max_drawdown_pct=self._calculate_current_drawdown(),
        )
    
    def _reset_daily(self) -> None:
        """Reset daily counters if new day"""
        today = date.today()
        if today != self._today_date:
            self._today_date = today
            self._daily_trades[today] = 0
            self._daily_pnl[today] = 0.0
            logger.info("Daily risk counters reset")
    
    def _is_circuit_breaker_active(self) -> bool:
        """Check if any circuit breaker is active"""
        for cb_time in self._circuit_breakers.values():
            if (datetime.now() - cb_time).total_seconds() < 300:  # 5 min cooldown
                return True
        return False
    
    def trigger_circuit_breaker(self, reason: str) -> None:
        """Activate circuit breaker for 5 minutes"""
        self._circuit_breakers['global'] = datetime.now()
        logger.warning(f"CIRCUIT BREAKER TRIGGERED: {reason}")
    
    def _check_stop_loss(self) -> bool:
        """Check if stop loss has been triggered"""
        if self._trade_history:
            # Look at recent trades
            recent = list(self._trade_history)[-5:]
            losses = [t['pnl_usd'] for t in recent if t['pnl_usd'] < 0]
            if len(losses) >= 3:
                total_loss = sum(losses)
                if total_loss < -self.portfolio_value * 0.02:  # 2% in last 5 trades
                    return True
        return False
    
    def _check_drawdown_limit(self) -> bool:
        """Check if max drawdown is reached"""
        return self._calculate_current_drawdown() >= self.max_drawdown_pct
    
    def _calculate_current_drawdown(self) -> float:
        """Calculate current drawdown percentage"""
        if self.peak_portfolio_value == 0:
            return 0.0
        return max(0.0, (self.peak_portfolio_value - self.portfolio_value) / self.peak_portfolio_value)
    
    def get_position_limits(self, opportunity: 'ArbitrageOpportunity') -> Tuple[float, float]:
        """
        Get min/max position size for an opportunity based on risk.
        
        Returns: (min_size_usd, max_size_usd)
        """
        kelly_fraction = 0.25  # Conservative Kelly
        spread_bps = abs(opportunity.spread_bps)
        cost_bps = 30
        
        if spread_bps <= cost_bps:
            return 0, 0
        
        # Kelly fraction
        edge_bps = spread_bps - cost_bps
        kelly_pct = kelly_fraction * edge_bps / 100
        
        max_kelly = self.portfolio_value * kelly_pct
        
        # Hard caps
        max_hard = min(
            self.portfolio_value * 0.15,  # Max 15% per trade
            opportunity.max_trade_size_usd
        )
        
        # Bridge exposure limit
        available_bridge = self.portfolio_value * self.max_bridge_exposure_pct - self._bridge_exposure_usd
        max_bridge = available_bridge / 0.5  # 50% of trade in bridge
        
        max_size = min(max_kelly, max_hard, max_bridge)
        min_size = max(5000, self.portfolio_value * 0.01)  # At least 1% or $5K
        
        return max(min_size, 0), max(max_size, 0)
    
    def get_recent_performance(self, n_trades: int = 20) -> Dict:
        """Get recent trading performance metrics"""
        recent = list(self._trade_history)[-n_trades:]
        
        if not recent:
            return {
                'n_trades': 0,
                'win_rate': 0,
                'avg_pnl': 0,
                'profit_factor': 0,
            }
        
        pnls = [t['pnl_usd'] for t in recent]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        return {
            'n_trades': len(recent),
            'win_rate': len(wins) / len(pnls) if pnls else 0,
            'avg_pnl': sum(pnls) / len(pnls) if pnls else 0,
            'total_pnl': sum(pnls),
            'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) < 0 else float('inf'),
            'max_win': max(pnls) if pnls else 0,
            'max_loss': min(pnls) if pnls else 0,
        }
    
    def update_gas_state(self, chain: str, current_gwei: float, avg_24h: float) -> None:
        """Update gas state for a chain"""
        self._gas_spike_chains[chain] = current_gwei > avg_24h * self.gas_spike_multiplier
