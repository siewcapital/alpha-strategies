#!/usr/bin/env python3
"""
Liquidation Cascade Sniping (LCS) Monitor
Detects and capitalizes on liquidation-driven price dislocations.

Author: ATLAS
Date: March 21, 2026
"""

import asyncio
import json
import sys
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp


class LiquidationCascadeMonitor:
    """
    Monitor for liquidation cascade events and subsequent mean-reversion opportunities.
    
    Strategy Logic:
    1. Detect abnormal liquidation volume
    2. Identify price over-extension from liquidation pressure
    3. Execute mean-reversion trades post-exhaustion
    4. Profit as price normalizes
    
    Market Context:
    - In "Extreme Fear" environments (Fear & Greed Index < 20), liquidation cascades are frequent
    - Leverage flushes create temporary price dislocations
    - Mean-reversion typically occurs within 15-60 minutes post-cascade
    """
    
    def __init__(
        self,
        symbols: List[str] = None,
        lookback_minutes: int = 60,
        liquidation_threshold: float = 3.0,  # Multiplier above average
        price_move_threshold: float = 2.0,   # % move in short window
        cooldown_minutes: int = 30,          # Min time between signals
        exchanges: List[str] = None
    ):
        self.symbols = symbols or ['BTC', 'ETH', 'SOL']
        self.lookback_minutes = lookback_minutes
        self.liquidation_threshold = liquidation_threshold
        self.price_move_threshold = price_move_threshold
        self.cooldown_minutes = cooldown_minutes
        self.exchanges = exchanges or ['binance', 'bybit', 'okx']
        
        # Data storage
        self.liquidation_history: Dict[str, deque] = {s: deque(maxlen=lookback_minutes) for s in self.symbols}
        self.price_history: Dict[str, deque] = {s: deque(maxlen=lookback_minutes) for s in self.symbols}
        self.last_signal_time: Dict[str, Optional[datetime]] = {s: None for s in self.symbols}
        
        # Cascade detection parameters
        self.cascade_params = {
            'min_liquidation_usd': 1000000,      # $1M minimum for significant cascade
            'price_impact_threshold': 2.0,        # 2% move in 5 minutes
            'volume_spike_multiplier': 3.0,       # 3x average volume
            'recovery_window': 45                 # Target recovery in 45 minutes
        }
        
    async def fetch_liquidation_data(self, session: aiohttp.ClientSession, symbol: str) -> Dict:
        """
        Fetch liquidation data from aggregated sources.
        
        Uses multiple data sources for redundancy:
        1. CoinGlass API (if available)
        2. Exchange liquidation feeds
        3. On-chain liquidations (for DeFi)
        """
        liquidations = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'total_usd': 0,
            'long_liquidations': 0,
            'short_liquidations': 0,
            'exchange_breakdown': {},
            'source': 'aggregated'
        }
        
        # Try CoinGlass API (free tier)
        try:
            # Note: CoinGlass requires API key for production use
            # This is a placeholder for the API structure
            coinglass_data = await self._fetch_coinglass_liquidations(session, symbol)
            if coinglass_data:
                liquidations.update(coinglass_data)
        except Exception as e:
            pass  # Fallback to exchange data
            
        # Fetch from individual exchanges
        for exchange in self.exchanges:
            try:
                exchange_liqs = await self._fetch_exchange_liquidations(session, exchange, symbol)
                if exchange_liqs:
                    liquidations['total_usd'] += exchange_liqs.get('total_usd', 0)
                    liquidations['long_liquidations'] += exchange_liqs.get('long_liquidations', 0)
                    liquidations['short_liquidations'] += exchange_liqs.get('short_liquidations', 0)
                    liquidations['exchange_breakdown'][exchange] = exchange_liqs
            except Exception as e:
                continue
                
        return liquidations
        
    async def _fetch_coinglass_liquidations(self, session: aiohttp.ClientSession, symbol: str) -> Optional[Dict]:
        """Fetch liquidation data from CoinGlass."""
        # Placeholder for CoinGlass API integration
        # In production, this would use their API with proper authentication
        return None
        
    async def _fetch_exchange_liquidations(self, session: aiohttp.ClientSession, 
                                           exchange: str, symbol: str) -> Optional[Dict]:
        """Fetch liquidation data directly from exchanges."""
        try:
            if exchange == 'binance':
                url = f"https://fapi.binance.com/fapi/v1/forceOrders?symbol={symbol}USDT"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, list):
                            total_usd = sum(float(order['executedQty']) * float(order['avgPrice']) 
                                          for order in data[:50])
                            long_liqs = sum(1 for order in data[:50] if order.get('side') == 'SELL')
                            short_liqs = len(data[:50]) - long_liqs
                            return {
                                'total_usd': total_usd,
                                'long_liquidations': long_liqs,
                                'short_liquidations': short_liqs
                            }
                            
            elif exchange == 'bybit':
                url = f"https://api.bybit.com/v5/market/recent-trade?category=linear&symbol={symbol}USDT"
                # Bybit doesn't have a direct liquidation endpoint in public API
                # Would need authenticated API or websocket
                return None
                
        except Exception as e:
            return None
            
        return None
        
    async def fetch_price_data(self, session: aiohttp.ClientSession, symbol: str) -> Dict:
        """Fetch current and recent price data."""
        price_data = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'current_price': 0,
            'price_change_5m': 0,
            'price_change_1h': 0,
            'volume_24h': 0,
            'high_24h': 0,
            'low_24h': 0
        }
        
        try:
            # Fetch from Binance
            url = f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}USDT"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    price_data['current_price'] = float(data.get('lastPrice', 0))
                    price_data['price_change_24h'] = float(data.get('priceChangePercent', 0))
                    price_data['volume_24h'] = float(data.get('volume', 0))
                    price_data['high_24h'] = float(data.get('highPrice', 0))
                    price_data['low_24h'] = float(data.get('lowPrice', 0))
                    
            # Fetch 5-minute change
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}USDT&interval=5m&limit=2"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if len(data) >= 2:
                        prev_close = float(data[0][4])
                        curr_close = float(data[1][4])
                        price_data['price_change_5m'] = ((curr_close / prev_close) - 1) * 100
                        
        except Exception as e:
            print(f"⚠️  Error fetching price data for {symbol}: {e}")
            
        return price_data
        
    def detect_cascade_event(self, symbol: str, liquidation_data: Dict, price_data: Dict) -> Optional[Dict]:
        """
        Detect if current conditions indicate a liquidation cascade.
        
        Cascade Indicators:
        1. Abnormal liquidation volume (&gt;3x average)
        2. Rapid price movement (&gt;2% in 5 min)
        3. High correlation between liquidations and price direction
        """
        # Calculate average liquidation volume
        history = self.liquidation_history[symbol]
        if len(history) < 10:
            return None  # Not enough history
            
        avg_liq = sum(h.get('total_usd', 0) for h in history) / len(history)
        current_liq = liquidation_data.get('total_usd', 0)
        
        # Check thresholds
        liq_spike = current_liq > (avg_liq * self.liquidation_threshold)
        price_spike = abs(price_data.get('price_change_5m', 0)) > self.price_move_threshold
        significant_size = current_liq > self.cascade_params['min_liquidation_usd']
        
        cascade_detected = liq_spike and price_spike and significant_size
        
        if cascade_detected:
            direction = 'UP' if price_data.get('price_change_5m', 0) > 0 else 'DOWN'
            
            # Determine if this is likely exhaustion
            long_liqs = liquidation_data.get('long_liquidations', 0)
            short_liqs = liquidation_data.get('short_liquidations', 0)
            total_liqs = long_liqs + short_liqs
            
            if total_liqs > 0:
                long_ratio = long_liqs / total_liqs
                
                # Exhaustion signals
                exhaustion_indicators = []
                if direction == 'DOWN' and long_ratio > 0.8:
                    exhaustion_indicators.append('Heavy long liquidation (capitulation)')
                if direction == 'UP' and long_ratio < 0.2:
                    exhaustion_indicators.append('Heavy short liquidation (short squeeze)')
                if abs(price_data.get('price_change_5m', 0)) > 4:
                    exhaustion_indicators.append('Extreme price velocity')
                    
            return {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'detected': True,
                'direction': direction,
                'liquidation_usd': current_liq,
                'avg_liquidation_usd': avg_liq,
                'liquidation_spike_ratio': current_liq / avg_liq if avg_liq > 0 else 0,
                'price_change_5m': price_data.get('price_change_5m', 0),
                'price_change_24h': price_data.get('price_change_24h', 0),
                'long_ratio': long_ratio if total_liqs > 0 else 0.5,
                'exhaustion_indicators': exhaustion_indicators,
                'current_price': price_data.get('current_price', 0),
                'confidence': self._calculate_cascade_confidence(
                    current_liq, avg_liq, price_data.get('price_change_5m', 0), exhaustion_indicators
                )
            }
            
        return None
        
    def _calculate_cascade_confidence(self, current_liq: float, avg_liq: float, 
                                      price_change: float, exhaustion: List[str]) -> float:
        """Calculate confidence score for cascade opportunity."""
        score = 0.0
        
        # Liquidation magnitude (0-40 points)
        if avg_liq > 0:
            liq_ratio = current_liq / avg_liq
            score += min(40, (liq_ratio - 1) * 10)
            
        # Price velocity (0-30 points)
        score += min(30, abs(price_change) * 5)
        
        # Exhaustion signals (0-30 points)
        score += len(exhaustion) * 10
        
        return min(1.0, score / 100)
        
    def generate_signal(self, cascade_data: Dict) -> Dict:
        """Generate trading signal from cascade detection."""
        direction = cascade_data['direction']
        confidence = cascade_data['confidence']
        
        if direction == 'DOWN':
            # Price crashed due to liquidations - look for long entry
            action = 'LONG_MEAN_REVERSION'
            entry_zone = f"{cascade_data['current_price'] * 0.98:.2f} - {cascade_data['current_price']:.2f}"
            target = f"{cascade_data['current_price'] * 1.02:.2f} (2% mean reversion)"
            stop = f"{cascade_data['current_price'] * 0.95:.2f} (5% stop)"
        else:
            # Price spiked due to short squeeze - look for short entry
            action = 'SHORT_MEAN_REVERSION'
            entry_zone = f"{cascade_data['current_price']:.2f} - {cascade_data['current_price'] * 1.02:.2f}"
            target = f"{cascade_data['current_price'] * 0.98:.2f} (2% mean reversion)"
            stop = f"{cascade_data['current_price'] * 1.05:.2f} (5% stop)"
            
        # Position sizing based on confidence
        if confidence >= 0.8:
            size = 'FULL_SIZE (2% risk)'
        elif confidence >= 0.6:
            size = 'HALF_SIZE (1% risk)'
        else:
            size = 'QUARTER_SIZE (0.5% risk)'
            
        return {
            'action': action,
            'confidence': confidence,
            'entry_zone': entry_zone,
            'target': target,
            'stop_loss': stop,
            'position_size': size,
            'timeframe': f"{self.cascade_params['recovery_window']} minutes target",
            'rationale': f"Liquidation cascade exhaustion detected. {len(cascade_data['exhaustion_indicators'])} exhaustion signals."
        }
        
    def check_cooldown(self, symbol: str) -> bool:
        """Check if symbol is in cooldown period."""
        last_signal = self.last_signal_time[symbol]
        if last_signal is None:
            return True
            
        cooldown_end = last_signal + timedelta(minutes=self.cooldown_minutes)
        return datetime.now() > cooldown_end
        
    async def analyze_all_symbols(self, session: aiohttp.ClientSession) -> List[Dict]:
        """Analyze all configured symbols for cascade events."""
        print(f"\n{'='*80}")
        print(f"LIQUIDATION CASCADE ANALYSIS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        
        signals = []
        
        for symbol in self.symbols:
            print(f"🔍 Analyzing {symbol}...")
            
            # Fetch data
            liq_data = await self.fetch_liquidation_data(session, symbol)
            price_data = await self.fetch_price_data(session, symbol)
            
            # Store in history
            self.liquidation_history[symbol].append(liq_data)
            self.price_history[symbol].append(price_data)
            
            # Detect cascade
            cascade = self.detect_cascade_event(symbol, liq_data, price_data)
            
            if cascade and cascade['detected']:
                # Check cooldown
                if not self.check_cooldown(symbol):
                    print(f"   ⏸️  Cascade detected but in cooldown period")
                    continue
                    
                # Generate signal
                signal = self.generate_signal(cascade)
                
                # Update last signal time
                self.last_signal_time[symbol] = datetime.now()
                
                result = {
                    'symbol': symbol,
                    'cascade_data': cascade,
                    'signal': signal,
                    'timestamp': datetime.now().isoformat()
                }
                signals.append(result)
                
                # Display signal
                print(f"\n{'🚨'*20}")
                print(f"LIQUIDATION CASCADE DETECTED: {symbol}")
                print(f"{'🚨'*20}\n")
                print(f"Direction:        {cascade['direction']}")
                print(f"Liquidation Vol:  ${cascade['liquidation_usd']:,.0f}")
                print(f"Spike Ratio:      {cascade['liquidation_spike_ratio']:.1f}x average")
                print(f"5m Price Change:  {cascade['price_change_5m']:+.2f}%")
                print(f"Confidence:       {cascade['confidence']*100:.0f}%")
                print(f"\n📊 TRADING SIGNAL:")
                print(f"Action:           {signal['action']}")
                print(f"Entry Zone:       {signal['entry_zone']}")
                print(f"Target:           {signal['target']}")
                print(f"Stop Loss:        {signal['stop_loss']}")
                print(f"Position Size:    {signal['position_size']}")
                print(f"Timeframe:        {signal['timeframe']}")
                print(f"\nRationale:        {signal['rationale']}")
                
                if cascade['exhaustion_indicators']:
                    print(f"\nExhaustion Signals:")
                    for indicator in cascade['exhaustion_indicators']:
                        print(f"  • {indicator}")
                        
                print(f"\n{'-'*80}\n")
            else:
                print(f"   ✓ No cascade detected")
                print(f"     Current Liq: ${liq_data.get('total_usd', 0):,.0f}")
                print(f"     5m Change:   {price_data.get('price_change_5m', 0):+.2f}%")
                print()
                
        return signals
        
    async def run(self, cycles: Optional[int] = None, interval: int = 60):
        """Main monitoring loop."""
        print("\n" + "="*80)
        print("LIQUIDATION CASCADE SNIPING MONITOR")
        print("Detecting liquidation-driven price dislocations")
        print("="*80 + "\n")
        
        print(f"Configuration:")
        print(f"  Symbols: {', '.join(self.symbols)}")
        print(f"  Liquidation Threshold: {self.liquidation_threshold}x average")
        print(f"  Price Move Threshold: ±{self.price_move_threshold}%")
        print(f"  Cooldown Period: {self.cooldown_minutes} minutes")
        print(f"  Update Interval: {interval} seconds\n")
        
        cycle = 0
        async with aiohttp.ClientSession() as session:
            try:
                while cycles is None or cycle < cycles:
                    cycle += 1
                    signals = await self.analyze_all_symbols(session)
                    
                    if signals:
                        # Save signals
                        output_dir = Path(__file__).parent.parent.parent / 'research' / 'lcs_data'
                        output_dir.mkdir(parents=True, exist_ok=True)
                        
                        output_file = output_dir / f'lcs_signals_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                        with open(output_file, 'w') as f:
                            json.dump(signals, f, indent=2)
                            
                        print(f"💾 Signals saved to: {output_file}")
                        
                    if cycles is None or cycle < cycles:
                        print(f"\n⏱️  Next scan in {interval} seconds...\n")
                        await asyncio.sleep(interval)
                        
            except KeyboardInterrupt:
                print("\n\n👋 Monitor stopped by user")
                
    def save_state(self):
        """Save monitor state to file."""
        state = {
            'liquidation_history': {k: list(v) for k, v in self.liquidation_history.items()},
            'price_history': {k: list(v) for k, v in self.price_history.items()},
            'last_signal_time': {k: v.isoformat() if v else None 
                                for k, v in self.last_signal_time.items()}
        }
        
        output_dir = Path(__file__).parent.parent.parent / 'research' / 'lcs_data'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        state_file = output_dir / 'monitor_state.json'
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
            
        print(f"💾 State saved to: {state_file}")


async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Liquidation Cascade Sniping Monitor')
    parser.add_argument('--symbols', nargs='+', default=['BTC', 'ETH', 'SOL'],
                       help='Symbols to monitor (default: BTC ETH SOL)')
    parser.add_argument('--threshold', type=float, default=3.0,
                       help='Liquidation spike threshold multiplier (default: 3)')
    parser.add_argument('--price-threshold', type=float, default=2.0,
                       help='Price move threshold %% (default: 2)')
    parser.add_argument('--cooldown', type=int, default=30,
                       help='Cooldown between signals (minutes, default: 30)')
    parser.add_argument('--interval', type=int, default=60,
                       help='Update interval in seconds (default: 60)')
    parser.add_argument('--cycles', type=int, default=None,
                       help='Number of cycles to run (default: infinite)')
    
    args = parser.parse_args()
    
    monitor = LiquidationCascadeMonitor(
        symbols=args.symbols,
        liquidation_threshold=args.threshold,
        price_move_threshold=args.price_threshold,
        cooldown_minutes=args.cooldown
    )
    
    try:
        await monitor.run(cycles=args.cycles, interval=args.interval)
    finally:
        monitor.save_state()


if __name__ == '__main__':
    asyncio.run(main())
