"""
Crypto Volatility Risk Premium (VRP) Harvesting Strategy

This module implements the core VRP harvesting strategy using short ATM straddles
with dynamic delta hedging. The strategy systematically captures the spread between
implied volatility (IV) and realized volatility (RV).

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Signal(Enum):
    """Trade signals"""
    NO_SIGNAL = 0
    ENTER_SHORT_STRADDLE = 1
    EXIT_PROFIT_TARGET = 2
    EXIT_STOP_LOSS = 3
    EXIT_TIME_STOP = 4
    EXIT_IV_COLLAPSE = 5
    REBALANCE_HEDGE = 6


@dataclass
class StraddlePosition:
    """Represents a short straddle position"""
    asset: str
    strike: float
    expiration: datetime
    call_premium: float
    put_premium: float
    entry_iv: float
    entry_underlying: float
    entry_date: datetime
    quantity: int = 1
    
    # Dynamic tracking
    current_delta: float = 0.0
    current_gamma: float = 0.0
    current_theta: float = 0.0
    current_vega: float = 0.0
    current_iv: float = 0.0
    current_underlying: float = 0.0
    
    # P&L tracking
    realized_pnl: float = 0.0
    hedge_pnl: float = 0.0
    
    # Exit tracking
    exit_reason: Optional[str] = None
    exit_date: Optional[datetime] = None
    
    @property
    def total_premium(self) -> float:
        """Total premium collected"""
        return (self.call_premium + self.put_premium) * self.quantity
    
    @property
    def dte(self) -> int:
        """Days to expiration"""
        return max(0, (self.expiration - datetime.now()).days)
    
    @property
    def days_held(self) -> int:
        """Days since entry"""
        return (datetime.now() - self.entry_date).days


@dataclass
class HedgePosition:
    """Represents a delta hedge position in perpetual futures"""
    asset: str
    position_size: float  # Positive = long, Negative = short
    entry_price: float
    entry_date: datetime
    current_price: float = 0.0
    
    @property
    def delta(self) -> float:
        """Position delta (1.0 for futures)"""
        return self.position_size
    
    @property
    def pnl(self) -> float:
        """Unrealized P&L"""
        if self.position_size > 0:
            return self.position_size * (self.current_price - self.entry_price)
        else:
            return abs(self.position_size) * (self.entry_price - self.current_price)


class VRPHarvesterStrategy:
    """
    Volatility Risk Premium Harvesting Strategy
    
    Core strategy logic for selling delta-hedged ATM straddles when
    implied volatility is elevated relative to realized volatility.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize VRP Harvester strategy
        
        Args:
            config: Strategy configuration dictionary
        """
        self.config = config
        self.positions: List[StraddlePosition] = []
        self.hedges: Dict[str, HedgePosition] = {}
        self.trade_history: List[Dict] = []
        
        # Extract parameters
        self.iv_rank_threshold = config.get('iv_rank_threshold', 70)
        self.vrp_min_threshold = config.get('vrp_min_threshold', 0.05)
        self.max_dte_entry = config.get('max_dte_entry', 21)
        self.min_dte_entry = config.get('min_dte_entry', 7)
        self.profit_target = config.get('profit_target', 0.50)
        self.stop_loss = config.get('stop_loss', 2.00)
        self.time_stop_dte = config.get('time_stop_dte', 5)
        self.delta_threshold = config.get('delta_threshold', 0.15)
        self.target_delta = config.get('target_delta', 0.05)
        self.max_positions = config.get('max_positions', 3)
        self.dvol_filter = config.get('dvol_filter', 80)
        
        logger.info("VRP Harvester Strategy initialized")
        logger.info(f"IV Rank Threshold: {self.iv_rank_threshold}")
        logger.info(f"VRP Min Threshold: {self.vrp_min_threshold}")
        logger.info(f"Delta Threshold: {self.delta_threshold}")
    
    def check_entry_conditions(self, 
                              asset: str,
                              current_iv: float,
                              iv_rank: float,
                              iv_percentile: float,
                              realized_vol: float,
                              dvol_index: float,
                              available_margin: float) -> Tuple[Signal, Dict]:
        """
        Check if entry conditions are met for a new straddle position
        
        Args:
            asset: Asset symbol (BTC, ETH)
            current_iv: Current implied volatility (annualized, decimal)
            iv_rank: IV rank (0-100) vs 52-week range
            iv_percentile: IV percentile (0-100) vs 52-week history
            realized_vol: Realized volatility (annualized, decimal)
            dvol_index: DVOL or VIX equivalent index value
            available_margin: Available margin for trading
            
        Returns:
            Tuple of (Signal, metadata dict)
        """
        metadata = {
            'asset': asset,
            'current_iv': current_iv,
            'realized_vol': realized_vol,
            'vrp': current_iv - realized_vol,
            'iv_rank': iv_rank,
            'dvol': dvol_index,
            'checks_passed': [],
            'checks_failed': []
        }
        
        # Check 1: IV Rank above threshold
        if iv_rank >= self.iv_rank_threshold:
            metadata['checks_passed'].append(f"IV Rank {iv_rank:.1f} >= {self.iv_rank_threshold}")
        else:
            metadata['checks_failed'].append(f"IV Rank {iv_rank:.1f} < {self.iv_rank_threshold}")
            return Signal.NO_SIGNAL, metadata
        
        # Check 2: VRP exists (IV > RV)
        vrp = current_iv - realized_vol
        if vrp >= self.vrp_min_threshold:
            metadata['checks_passed'].append(f"VRP {vrp:.2%} >= {self.vrp_min_threshold:.2%}")
        else:
            metadata['checks_failed'].append(f"VRP {vrp:.2%} < {self.vrp_min_threshold:.2%}")
            return Signal.NO_SIGNAL, metadata
        
        # Check 3: Not in crisis regime
        if dvol_index <= self.dvol_filter:
            metadata['checks_passed'].append(f"DVOL {dvol_index} <= {self.dvol_filter}")
        else:
            metadata['checks_failed'].append(f"DVOL {dvol_index} > {self.dvol_filter}")
            return Signal.NO_SIGNAL, metadata
        
        # Check 4: Position limit
        current_positions = len([p for p in self.positions if p.exit_date is None])
        if current_positions < self.max_positions:
            metadata['checks_passed'].append(f"Positions {current_positions} < {self.max_positions}")
        else:
            metadata['checks_failed'].append(f"Max positions reached: {current_positions}")
            return Signal.NO_SIGNAL, metadata
        
        # Check 5: Sufficient margin
        estimated_margin = self._estimate_margin_requirement(asset, current_iv)
        if available_margin >= estimated_margin:
            metadata['checks_passed'].append(f"Margin available: ${available_margin:,.0f}")
        else:
            metadata['checks_failed'].append(f"Insufficient margin: ${available_margin:,.0f} < ${estimated_margin:,.0f}")
            return Signal.NO_SIGNAL, metadata
        
        logger.info(f"ENTRY SIGNAL for {asset}: IV Rank={iv_rank:.1f}, VRP={vrp:.2%}")
        return Signal.ENTER_SHORT_STRADDLE, metadata
    
    def check_exit_conditions(self, position: StraddlePosition) -> Tuple[Signal, Dict]:
        """
        Check if exit conditions are met for an existing position
        
        Args:
            position: The straddle position to check
            
        Returns:
            Tuple of (Signal, metadata dict)
        """
        metadata = {
            'asset': position.asset,
            'strike': position.strike,
            'entry_premium': position.total_premium,
            'dte': position.dte,
            'days_held': position.days_held
        }
        
        # Calculate current position value (theoretical)
        current_value = self._calculate_position_value(position)
        pnl_pct = (position.total_premium - current_value) / position.total_premium
        metadata['current_value'] = current_value
        metadata['pnl_pct'] = pnl_pct
        
        # Exit 1: Profit target
        if pnl_pct >= self.profit_target:
            metadata['exit_reason'] = f"Profit target: {pnl_pct:.1%} >= {self.profit_target:.1%}"
            return Signal.EXIT_PROFIT_TARGET, metadata
        
        # Exit 2: Stop loss
        if pnl_pct <= -self.stop_loss:
            metadata['exit_reason'] = f"Stop loss: {pnl_pct:.1%} <= -{self.stop_loss:.1%}"
            return Signal.EXIT_STOP_LOSS, metadata
        
        # Exit 3: Time stop
        if position.dte <= self.time_stop_dte:
            metadata['exit_reason'] = f"Time stop: DTE {position.dte} <= {self.time_stop_dte}"
            return Signal.EXIT_TIME_STOP, metadata
        
        # Exit 4: IV collapse (opportunistic early exit)
        if position.current_iv < position.entry_iv * 0.7:  # IV fell 30%
            if pnl_pct > 0.25:  # Only exit if profitable
                metadata['exit_reason'] = f"IV collapse: {position.current_iv:.2%} vs entry {position.entry_iv:.2%}"
                return Signal.EXIT_IV_COLLAPSE, metadata
        
        return Signal.NO_SIGNAL, metadata
    
    def check_hedge_rebalance(self, position: StraddlePosition) -> Tuple[Signal, Dict]:
        """
        Check if delta hedge needs rebalancing
        
        Args:
            position: The straddle position to check
            
        Returns:
            Tuple of (Signal, metadata dict)
        """
        metadata = {
            'asset': position.asset,
            'current_delta': position.current_delta,
            'target_delta': self.target_delta,
            'threshold': self.delta_threshold
        }
        
        if abs(position.current_delta) > self.delta_threshold:
            metadata['rebalance_needed'] = True
            metadata['hedge_size'] = -position.current_delta  # Opposite sign to neutralize
            return Signal.REBALANCE_HEDGE, metadata
        
        return Signal.NO_SIGNAL, metadata
    
    def enter_position(self, 
                      asset: str,
                      strike: float,
                      expiration: datetime,
                      call_premium: float,
                      put_premium: float,
                      iv: float,
                      underlying_price: float,
                      delta: float,
                      gamma: float,
                      theta: float,
                      vega: float,
                      quantity: int = 1) -> StraddlePosition:
        """
        Enter a new short straddle position
        
        Args:
            asset: Asset symbol
            strike: Strike price
            expiration: Expiration datetime
            call_premium: Call option premium
            put_premium: Put option premium
            iv: Implied volatility at entry
            underlying_price: Underlying price at entry
            delta: Position delta
            gamma: Position gamma
            theta: Position theta
            vega: Position vega
            quantity: Number of contracts
            
        Returns:
            StraddlePosition object
        """
        position = StraddlePosition(
            asset=asset,
            strike=strike,
            expiration=expiration,
            call_premium=call_premium,
            put_premium=put_premium,
            entry_iv=iv,
            entry_underlying=underlying_price,
            entry_date=datetime.now(),
            quantity=quantity,
            current_delta=delta,
            current_gamma=gamma,
            current_theta=theta,
            current_vega=vega,
            current_iv=iv,
            current_underlying=underlying_price
        )
        
        self.positions.append(position)
        
        # Immediately establish delta hedge
        hedge_size = -delta * quantity
        hedge = HedgePosition(
            asset=asset,
            position_size=hedge_size,
            entry_price=underlying_price,
            entry_date=datetime.now(),
            current_price=underlying_price
        )
        self.hedges[asset] = hedge
        
        logger.info(f"ENTERED {asset} straddle: Strike={strike}, Premium={call_premium+put_premium:.4f}, "
                   f"IV={iv:.2%}, Delta={delta:.3f}")
        
        return position
    
    def exit_position(self, position: StraddlePosition, exit_reason: str, 
                     exit_premium: float) -> Dict:
        """
        Exit a straddle position
        
        Args:
            position: Position to exit
            exit_reason: Reason for exit
            exit_premium: Current premium to buy back
            
        Returns:
            Trade summary dict
        """
        position.exit_date = datetime.now()
        position.exit_reason = exit_reason
        
        # Calculate P&L
        premium_pnl = position.total_premium - (exit_premium * position.quantity)
        hedge_pnl = self.hedges.get(position.asset, HedgePosition(position.asset, 0, 0, datetime.now())).pnl
        total_pnl = premium_pnl + hedge_pnl
        
        position.realized_pnl = premium_pnl
        position.hedge_pnl = hedge_pnl
        
        # Close hedge position
        if position.asset in self.hedges:
            del self.hedges[position.asset]
        
        trade_summary = {
            'asset': position.asset,
            'strike': position.strike,
            'entry_date': position.entry_date,
            'exit_date': position.exit_date,
            'days_held': position.days_held,
            'entry_premium': position.total_premium,
            'exit_premium': exit_premium * position.quantity,
            'premium_pnl': premium_pnl,
            'hedge_pnl': hedge_pnl,
            'total_pnl': total_pnl,
            'pnl_pct': total_pnl / position.total_premium,
            'exit_reason': exit_reason,
            'entry_iv': position.entry_iv,
            'exit_iv': position.current_iv
        }
        
        self.trade_history.append(trade_summary)
        
        logger.info(f"EXITED {position.asset} straddle: PnL=${total_pnl:.2f} "
                   f"({trade_summary['pnl_pct']:.1%}), Reason={exit_reason}")
        
        return trade_summary
    
    def update_position(self, position: StraddlePosition, 
                       current_underlying: float,
                       current_iv: float,
                       delta: float,
                       gamma: float,
                       theta: float,
                       vega: float):
        """
        Update position Greeks and pricing
        
        Args:
            position: Position to update
            current_underlying: Current underlying price
            current_iv: Current implied volatility
            delta: Current delta
            gamma: Current gamma
            theta: Current theta
            vega: Current vega
        """
        position.current_underlying = current_underlying
        position.current_iv = current_iv
        position.current_delta = delta
        position.current_gamma = gamma
        position.current_theta = theta
        position.current_vega = vega
        
        # Update hedge pricing
        if position.asset in self.hedges:
            self.hedges[position.asset].current_price = current_underlying
    
    def rebalance_hedge(self, position: StraddlePosition) -> HedgePosition:
        """
        Rebalance delta hedge to maintain neutrality
        
        Args:
            position: Position to hedge
            
        Returns:
            Updated HedgePosition
        """
        target_hedge_size = -position.current_delta * position.quantity
        
        if position.asset in self.hedges:
            current_hedge = self.hedges[position.asset]
            adjustment = target_hedge_size - current_hedge.position_size
            
            # Update hedge position
            new_size = current_hedge.position_size + adjustment
            avg_price = ((current_hedge.position_size * current_hedge.entry_price) + 
                        (adjustment * position.current_underlying)) / new_size if new_size != 0 else 0
            
            current_hedge.position_size = new_size
            current_hedge.entry_price = avg_price
            current_hedge.current_price = position.current_underlying
            
            logger.info(f"REBALANCED {position.asset} hedge: Size={new_size:.3f}, Adjustment={adjustment:.3f}")
        else:
            # Create new hedge
            self.hedges[position.asset] = HedgePosition(
                asset=position.asset,
                position_size=target_hedge_size,
                entry_price=position.current_underlying,
                entry_date=datetime.now(),
                current_price=position.current_underlying
            )
            logger.info(f"NEW HEDGE {position.asset}: Size={target_hedge_size:.3f}")
        
        return self.hedges[position.asset]
    
    def _estimate_margin_requirement(self, asset: str, iv: float) -> float:
        """Estimate margin requirement for a new position"""
        # Simplified margin estimate: roughly 10% of notional for short options
        notional = 50000 if asset == "BTC" else 3000  # Approximate prices
        return notional * iv * 0.10  # Conservative estimate
    
    def _calculate_position_value(self, position: StraddlePosition) -> float:
        """
        Calculate current theoretical value of straddle position
        Uses Black-Scholes approximation for mark-to-market
        """
        # Simplified valuation - in production would use actual market prices
        # or proper Black-Scholes with current parameters
        time_decay_factor = max(0, position.dte / 30)  # Simplified
        iv_factor = position.current_iv / position.entry_iv if position.entry_iv > 0 else 1.0
        
        # Base value decays with time and IV changes
        base_value = (position.call_premium + position.put_premium) * position.quantity
        adjusted_value = base_value * np.sqrt(time_decay_factor) * iv_factor
        
        return max(0.01, adjusted_value)
    
    def get_portfolio_stats(self) -> Dict:
        """Get current portfolio statistics"""
        open_positions = [p for p in self.positions if p.exit_date is None]
        closed_positions = [p for p in self.positions if p.exit_date is not None]
        
        total_pnl = sum(t['total_pnl'] for t in self.trade_history)
        winning_trades = len([t for t in self.trade_history if t['pnl_pct'] > 0])
        
        return {
            'open_positions': len(open_positions),
            'closed_positions': len(closed_positions),
            'total_trades': len(self.trade_history),
            'winning_trades': winning_trades,
            'win_rate': winning_trades / len(self.trade_history) if self.trade_history else 0,
            'total_pnl': total_pnl,
            'total_premium_collected': sum(p.total_premium for p in open_positions),
            'net_delta': sum(p.current_delta for p in open_positions),
            'net_theta': sum(p.current_theta for p in open_positions),
            'net_vega': sum(p.current_vega for p in open_positions)
        }
