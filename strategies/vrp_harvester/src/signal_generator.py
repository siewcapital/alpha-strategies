"""
Signal Generator Module for VRP Harvester Strategy

Generates entry and exit signals based on:
- IV Rank and IV Percentile thresholds
- VRP calculations
- Volatility regime detection
- Technical confirmation filters

Author: ATLAS Alpha Hunter
Date: 2026-03-18
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from .indicators import VolatilityCalculator, VolatilityRegimeDetector, GreeksCalculator

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """Structured signal result"""
    signal_type: str  # 'ENTER', 'EXIT', 'HEDGE', 'NONE'
    confidence: float  # 0.0 to 1.0
    metadata: Dict
    timestamp: datetime
    asset: str


class SignalGenerator:
    """
    Generates trading signals for VRP Harvester strategy
    
    Combines multiple factors for robust signal generation:
    1. Volatility metrics (IV Rank, VRP)
    2. Market regime detection
    3. Trend/momentum filters
    4. Risk management constraints
    """
    
    def __init__(self, config: Dict):
        """
        Initialize signal generator
        
        Args:
            config: Configuration dictionary with signal parameters
        """
        self.config = config
        
        # Entry parameters
        self.iv_rank_min = config.get('iv_rank_min', 70)
        self.iv_percentile_min = config.get('iv_percentile_min', 70)
        self.vrp_min = config.get('vrp_min', 0.05)
        self.vrp_optimal = config.get('vrp_optimal', 0.15)
        
        # Exit parameters
        self.profit_target = config.get('profit_target', 0.50)
        self.stop_loss = config.get('stop_loss', 2.00)
        self.time_stop_dte = config.get('time_stop_dte', 5)
        
        # Hedge parameters
        self.delta_threshold = config.get('delta_threshold', 0.15)
        self.target_delta = config.get('target_delta', 0.05)
        
        # Filters
        self.dvol_max = config.get('dvol_max', 80)
        self.trend_filter = config.get('trend_filter', True)
        self.min_adx = config.get('min_adx', 20)
        
        # Initialize calculators
        self.vol_calc = VolatilityCalculator()
        self.regime_detector = VolatilityRegimeDetector()
        self.greeks_calc = GreeksCalculator()
    
    def generate_entry_signal(self,
                             asset: str,
                             current_price: float,
                             current_iv: float,
                             iv_history: pd.Series,
                             rv_history: pd.Series,
                             price_history: pd.DataFrame,
                             available_margin: float,
                             open_positions: int) -> SignalResult:
        """
        Generate entry signal for new straddle position
        
        Args:
            asset: Asset symbol
            current_price: Current spot price
            current_iv: Current implied volatility
            iv_history: Historical IV series
            rv_history: Historical RV series
            price_history: OHLCV price data
            available_margin: Available trading margin
            open_positions: Current number of open positions
            
        Returns:
            SignalResult with signal details
        """
        timestamp = datetime.now()
        metadata = {
            'asset': asset,
            'current_price': current_price,
            'current_iv': current_iv,
            'checks': []
        }
        
        # Check 1: Position limit
        max_positions = self.config.get('max_positions', 3)
        if open_positions >= max_positions:
            metadata['checks'].append({'name': 'position_limit', 'passed': False, 
                                      'value': f"{open_positions}/{max_positions}"})
            return SignalResult('NONE', 0.0, metadata, timestamp, asset)
        
        # Check 2: Margin availability
        min_margin = self.config.get('min_margin', 1000)
        if available_margin < min_margin:
            metadata['checks'].append({'name': 'margin', 'passed': False, 
                                      'value': f"${available_margin:,.0f} < ${min_margin:,.0f}"})
            return SignalResult('NONE', 0.0, metadata, timestamp, asset)
        
        # Calculate IV metrics
        iv_rank = self.vol_calc.calculate_iv_rank(current_iv, iv_history)
        iv_percentile = self.vol_calc.calculate_iv_percentile(current_iv, iv_history)
        current_rv = rv_history.iloc[-1] if len(rv_history) > 0 else current_iv * 0.7
        vrp = self.vol_calc.calculate_vrp(current_iv, current_rv)
        
        metadata['iv_rank'] = iv_rank
        metadata['iv_percentile'] = iv_percentile
        metadata['current_rv'] = current_rv
        metadata['vrp'] = vrp
        
        # Check 3: IV Rank threshold
        if iv_rank < self.iv_rank_min:
            metadata['checks'].append({'name': 'iv_rank', 'passed': False, 
                                      'value': f"{iv_rank:.1f} < {self.iv_rank_min}"})
            return SignalResult('NONE', 0.0, metadata, timestamp, asset)
        metadata['checks'].append({'name': 'iv_rank', 'passed': True, 'value': f"{iv_rank:.1f}"})
        
        # Check 4: IV Percentile threshold
        if iv_percentile < self.iv_percentile_min:
            metadata['checks'].append({'name': 'iv_percentile', 'passed': False, 
                                      'value': f"{iv_percentile:.1f} < {self.iv_percentile_min}"})
            return SignalResult('NONE', 0.0, metadata, timestamp, asset)
        metadata['checks'].append({'name': 'iv_percentile', 'passed': True, 'value': f"{iv_percentile:.1f}"})
        
        # Check 5: VRP threshold
        if vrp < self.vrp_min:
            metadata['checks'].append({'name': 'vrp', 'passed': False, 
                                      'value': f"{vrp:.2%} < {self.vrp_min:.2%}"})
            return SignalResult('NONE', 0.0, metadata, timestamp, asset)
        metadata['checks'].append({'name': 'vrp', 'passed': True, 'value': f"{vrp:.2%}"})
        
        # Check 6: DVOL/Volatility regime
        dvol_proxy = self._calculate_dvol_proxy(price_history)
        metadata['dvol_proxy'] = dvol_proxy
        if dvol_proxy > self.dvol_max:
            metadata['checks'].append({'name': 'dvol', 'passed': False, 
                                      'value': f"{dvol_proxy:.1f} > {self.dvol_max}"})
            return SignalResult('NONE', 0.0, metadata, timestamp, asset)
        metadata['checks'].append({'name': 'dvol', 'passed': True, 'value': f"{dvol_proxy:.1f}"})
        
        # Check 7: Trend filter (optional)
        if self.trend_filter:
            trend_score = self._calculate_trend_score(price_history)
            metadata['trend_score'] = trend_score
            if abs(trend_score) > 0.7:  # Too directional
                metadata['checks'].append({'name': 'trend', 'passed': False, 
                                          'value': f"{trend_score:.2f} (too directional)"})
                return SignalResult('NONE', 0.0, metadata, timestamp, asset)
            metadata['checks'].append({'name': 'trend', 'passed': True, 'value': f"{trend_score:.2f}"})
        
        # Calculate confidence score
        confidence = self._calculate_entry_confidence(iv_rank, iv_percentile, vrp, dvol_proxy)
        metadata['confidence'] = confidence
        
        logger.info(f"ENTRY SIGNAL: {asset} - IV Rank={iv_rank:.1f}, VRP={vrp:.2%}, Confidence={confidence:.2f}")
        
        return SignalResult('ENTER', confidence, metadata, timestamp, asset)
    
    def generate_exit_signal(self,
                            asset: str,
                            position_data: Dict,
                            current_price: float,
                            current_iv: float,
                            iv_history: pd.Series) -> SignalResult:
        """
        Generate exit signal for existing position
        
        Args:
            asset: Asset symbol
            position_data: Dictionary with position details
            current_price: Current spot price
            current_iv: Current implied volatility
            iv_history: Historical IV series
            
        Returns:
            SignalResult with exit signal
        """
        timestamp = datetime.now()
        metadata = {
            'asset': asset,
            'current_price': current_price,
            'current_iv': current_iv,
            'checks': []
        }
        
        entry_premium = position_data.get('entry_premium', 0)
        current_premium = position_data.get('current_premium', entry_premium)
        entry_date = position_data.get('entry_date', timestamp)
        expiration = position_data.get('expiration', timestamp + timedelta(days=30))
        entry_iv = position_data.get('entry_iv', current_iv)
        
        # Calculate metrics
        pnl_pct = (entry_premium - current_premium) / entry_premium if entry_premium > 0 else 0
        dte = max(0, (expiration - timestamp).days)
        days_held = (timestamp - entry_date).days
        
        metadata['pnl_pct'] = pnl_pct
        metadata['dte'] = dte
        metadata['days_held'] = days_held
        
        # Exit 1: Profit target
        if pnl_pct >= self.profit_target:
            metadata['checks'].append({'name': 'profit_target', 'triggered': True, 
                                      'value': f"{pnl_pct:.1%} >= {self.profit_target:.1%}"})
            logger.info(f"EXIT SIGNAL: {asset} - Profit target reached: {pnl_pct:.1%}")
            return SignalResult('EXIT', 1.0, metadata, timestamp, asset)
        
        # Exit 2: Stop loss
        if pnl_pct <= -self.stop_loss:
            metadata['checks'].append({'name': 'stop_loss', 'triggered': True, 
                                      'value': f"{pnl_pct:.1%} <= -{self.stop_loss:.1%}"})
            logger.info(f"EXIT SIGNAL: {asset} - Stop loss triggered: {pnl_pct:.1%}")
            return SignalResult('EXIT', 1.0, metadata, timestamp, asset)
        
        # Exit 3: Time stop
        if dte <= self.time_stop_dte:
            metadata['checks'].append({'name': 'time_stop', 'triggered': True, 
                                      'value': f"DTE {dte} <= {self.time_stop_dte}"})
            logger.info(f"EXIT SIGNAL: {asset} - Time stop: {dte} DTE")
            return SignalResult('EXIT', 1.0, metadata, timestamp, asset)
        
        # Exit 4: IV collapse (opportunistic)
        iv_collapse_threshold = 0.70  # IV fell 30%
        if current_iv < entry_iv * iv_collapse_threshold and pnl_pct > 0.25:
            metadata['checks'].append({'name': 'iv_collapse', 'triggered': True, 
                                      'value': f"IV {current_iv:.2%} < {entry_iv * iv_collapse_threshold:.2%}"})
            logger.info(f"EXIT SIGNAL: {asset} - IV collapse exit")
            return SignalResult('EXIT', 0.8, metadata, timestamp, asset)
        
        # No exit signal
        metadata['checks'].append({'name': 'hold', 'triggered': False, 
                                  'value': f"PnL={pnl_pct:.1%}, DTE={dte}"})
        return SignalResult('NONE', 0.0, metadata, timestamp, asset)
    
    def generate_hedge_signal(self,
                             asset: str,
                             position_delta: float,
                             current_hedge_size: float,
                             current_price: float) -> SignalResult:
        """
        Generate hedge rebalancing signal
        
        Args:
            asset: Asset symbol
            position_delta: Current position delta
            current_hedge_size: Current hedge position size
            current_price: Current spot price
            
        Returns:
            SignalResult with hedge signal
        """
        timestamp = datetime.now()
        metadata = {
            'asset': asset,
            'position_delta': position_delta,
            'current_hedge': current_hedge_size,
            'current_price': current_price
        }
        
        # Calculate net delta
        net_delta = position_delta + current_hedge_size
        metadata['net_delta'] = net_delta
        
        # Check if rebalance needed
        if abs(net_delta) > self.delta_threshold:
            target_hedge = -position_delta
            adjustment = target_hedge - current_hedge_size
            
            metadata['target_hedge'] = target_hedge
            metadata['adjustment'] = adjustment
            metadata['reason'] = f"Net delta {net_delta:.3f} exceeds threshold {self.delta_threshold}"
            
            logger.info(f"HEDGE SIGNAL: {asset} - Rebalance: adjustment={adjustment:.3f}")
            return SignalResult('HEDGE', 1.0, metadata, timestamp, asset)
        
        return SignalResult('NONE', 0.0, metadata, timestamp, asset)
    
    def _calculate_entry_confidence(self, iv_rank: float, iv_percentile: float, 
                                   vrp: float, dvol: float) -> float:
        """
        Calculate confidence score for entry signal
        
        Higher confidence when:
        - IV Rank is very high (>80)
        - VRP is large (>10%)
        - DVOL is moderate (not in crisis)
        """
        # IV Rank component (0.0 to 0.4)
        iv_score = min(0.4, (iv_rank / 100) * 0.5)
        
        # VRP component (0.0 to 0.4)
        vrp_normalized = min(1.0, vrp / self.vrp_optimal)
        vrp_score = vrp_normalized * 0.4
        
        # DVOL component (0.0 to 0.2)
        # Best when DVOL is elevated but not extreme
        dvol_optimal = self.dvol_max * 0.6
        if dvol <= dvol_optimal:
            dvol_score = (dvol / dvol_optimal) * 0.2
        else:
            dvol_score = max(0, 0.2 - (dvol - dvol_optimal) / self.dvol_max * 0.2)
        
        return min(1.0, iv_score + vrp_score + dvol_score)
    
    def _calculate_trend_score(self, price_history: pd.DataFrame) -> float:
        """
        Calculate trend score (-1 to 1)
        Used to avoid entering when market is strongly trending
        """
        if len(price_history) < 50:
            return 0.0
        
        close = price_history['close']
        
        # Calculate ADX-like trend strength
        # Simplified version using slope of regression
        x = np.arange(len(close.tail(20)))
        y = close.tail(20).values
        slope = np.polyfit(x, y, 1)[0]
        
        # Normalize by average price
        normalized_slope = slope / close.mean()
        
        # Scale to -1 to 1
        trend_score = np.tanh(normalized_slope * 100)
        
        return trend_score
    
    def _calculate_dvol_proxy(self, price_history: pd.DataFrame) -> float:
        """
        Calculate a DVOL-like volatility index proxy
        """
        if len(price_history) < 30:
            return 50.0  # Default moderate vol
        
        # Use close-to-close returns (annualized and converted to percentage)
        returns = np.log(price_history['close'] / price_history['close'].shift(1))
        vol = returns.rolling(30).std().iloc[-1] * np.sqrt(365) * 100
        
        return vol if not np.isnan(vol) else 50.0
    
    def scan_for_opportunities(self,
                              assets: List[str],
                              market_data: Dict[str, Dict]) -> List[SignalResult]:
        """
        Scan multiple assets for VRP opportunities
        
        Args:
            assets: List of asset symbols to scan
            market_data: Dictionary of market data for each asset
            
        Returns:
            List of SignalResult objects sorted by confidence
        """
        signals = []
        
        for asset in assets:
            if asset not in market_data:
                continue
            
            data = market_data[asset]
            signal = self.generate_entry_signal(
                asset=asset,
                current_price=data.get('price', 0),
                current_iv=data.get('current_iv', 0),
                iv_history=data.get('iv_history', pd.Series()),
                rv_history=data.get('rv_history', pd.Series()),
                price_history=data.get('price_history', pd.DataFrame()),
                available_margin=data.get('available_margin', 0),
                open_positions=data.get('open_positions', 0)
            )
            
            if signal.signal_type == 'ENTER':
                signals.append(signal)
        
        # Sort by confidence descending
        signals.sort(key=lambda x: x.confidence, reverse=True)
        
        return signals
