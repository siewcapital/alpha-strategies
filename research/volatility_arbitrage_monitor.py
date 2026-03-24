#!/usr/bin/env python3
"""
Volatility Arbitrage Monitor (ETH-BTC IV Spread)
Tracks implied volatility spreads between BTC and ETH for mean-reversion opportunities.

Author: ATLAS
Date: March 21, 2026
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import ccxt.async_support as ccxt


class VolatilityArbitrageMonitor:
    """
    Monitor ETH-BTC implied volatility spread for arbitrage opportunities.
    
    Strategy:
    - When ETH IV trades at significant premium/discount to BTC IV
    - Trade the mean-reversion of the spread
    - Delta-hedged for pure vol exposure
    """
    
    def __init__(
        self,
        exchanges: list = None,
        min_spread_threshold: float = 5.0,  # Minimum IV spread % to alert
        lookback_days: int = 30,
        update_interval: int = 300  # 5 minutes
    ):
        self.exchanges = exchanges or ['deribit', 'binance']
        self.min_spread_threshold = min_spread_threshold
        self.lookback_days = lookback_days
        self.update_interval = update_interval
        
        self.exchange_instances: Dict[str, ccxt.Exchange] = {}
        self.iv_history: list = []
        self.spread_history: list = []
        
        # Volatility regime thresholds
        self.spread_thresholds = {
            'extreme_high': 20.0,  # ETH IV 20%+ above BTC (short ETH vol)
            'high': 10.0,          # ETH IV 10%+ above BTC (monitor for short)
            'normal_high': 5.0,    # ETH IV 5%+ above BTC (normal range)
            'normal_low': -5.0,    # ETH IV 5% below BTC (normal range)
            'low': -10.0,          # ETH IV 10% below BTC (monitor for long)
            'extreme_low': -20.0   # ETH IV 20% below BTC (long ETH vol)
        }
        
    async def initialize_exchanges(self):
        """Initialize exchange connections."""
        for ex_name in self.exchanges:
            try:
                exchange_class = getattr(ccxt, ex_name)
                exchange = exchange_class({
                    'enableRateLimit': True,
                    'options': {'defaultType': 'option'} if ex_name == 'deribit' else {}
                })
                await exchange.load_markets()
                self.exchange_instances[ex_name] = exchange
                print(f"✅ Connected to {ex_name.upper()}")
            except Exception as e:
                print(f"⚠️  Failed to connect to {ex_name}: {e}")
                
    async def fetch_option_iv(self, exchange: ccxt.Exchange, symbol: str) -> Optional[Dict]:
        """
        Fetch implied volatility data for options.
        
        For Deribit: Use DVOL index or ATM options
        For Binance: Use options mark price IV
        """
        try:
            if exchange.id == 'deribit':
                # Try to fetch DVOL index first
                try:
                    # DVOL is the volatility index on Deribit
                    ticker = await exchange.fetch_ticker(f"{symbol}_DVOL")
                    return {
                        'symbol': symbol,
                        'iv': ticker.get('last', 0),
                        'source': 'DVOL',
                        'timestamp': datetime.now().isoformat()
                    }
                except:
                    # Fallback to ATM options
                    return await self._fetch_atm_iv_deribit(exchange, symbol)
                    
            elif exchange.id == 'binance':
                # Fetch Binance options IV
                return await self._fetch_binance_options_iv(exchange, symbol)
                
        except Exception as e:
            print(f"⚠️  Error fetching IV for {symbol} on {exchange.id}: {e}")
            return None
            
    async def _fetch_atm_iv_deribit(self, exchange: ccxt.Exchange, symbol: str) -> Optional[Dict]:
        """Fetch ATM option IV from Deribit."""
        try:
            # Get current spot price
            spot_ticker = await exchange.fetch_ticker(f"{symbol}_PERP")
            spot_price = spot_ticker['last']
            
            # Find ATM strike (closest to spot)
            strikes = await exchange.public_get_get_instruments({
                'currency': symbol,
                'kind': 'option',
                'expired': 'false'
            })
            
            if not strikes or 'result' not in strikes:
                return None
                
            # Find closest expiration (30 days out)
            target_date = datetime.now() + timedelta(days=30)
            closest_expiry = None
            min_diff = float('inf')
            
            for instrument in strikes['result']:
                expiry = datetime.fromtimestamp(instrument['expiration_timestamp'] / 1000)
                diff = abs((expiry - target_date).days)
                if diff < min_diff:
                    min_diff = diff
                    closest_expiry = instrument['expiration_timestamp']
                    
            if not closest_expiry:
                return None
                
            # Find ATM strike
            atm_strike = None
            min_strike_diff = float('inf')
            
            for instrument in strikes['result']:
                if instrument['expiration_timestamp'] == closest_expiry:
                    strike_diff = abs(instrument['strike'] - spot_price)
                    if strike_diff < min_strike_diff:
                        min_strike_diff = strike_diff
                        atm_strike = instrument['strike']
                        
            if not atm_strike:
                return None
                
            # Fetch ATM option mark price
            call_symbol = f"{symbol}-{closest_expiry // 1000 // 86400 * 86400}-{int(atm_strike)}-C"
            option_ticker = await exchange.fetch_ticker(call_symbol)
            
            # Extract IV from greeks
            iv = option_ticker.get('info', {}).get('mark_iv', 0)
            
            return {
                'symbol': symbol,
                'iv': float(iv) if iv else 0,
                'strike': atm_strike,
                'expiry': closest_expiry,
                'source': 'ATM_OPTION',
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"⚠️  Deribit ATM fetch error: {e}")
            return None
            
    async def _fetch_binance_options_iv(self, exchange: ccxt.Exchange, symbol: str) -> Optional[Dict]:
        """Fetch options IV from Binance."""
        try:
            # Binance uses different symbol format for options
            binance_symbol = f"{symbol}-USDT"
            
            # Fetch mark price for options
            response = await exchange.eapiPublicGetMark({
                'underlying': binance_symbol
            })
            
            if not response or 'data' not in response:
                return None
                
            # Find ATM option (30 days expiry)
            target_date = datetime.now() + timedelta(days=30)
            atm_option = None
            min_diff = float('inf')
            
            for option in response['data']:
                expiry = datetime.fromtimestamp(option['expiryDate'] / 1000)
                diff = abs((expiry - target_date).days)
                if diff < min_diff:
                    min_diff = diff
                    atm_option = option
                    
            if not atm_option:
                return None
                
            return {
                'symbol': symbol,
                'iv': float(atm_option.get('markIv', 0)) * 100,  # Convert to percentage
                'strike': float(atm_option.get('strikePrice', 0)),
                'expiry': atm_option.get('expiryDate'),
                'source': 'BINANCE_OPTION',
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"⚠️  Binance options fetch error: {e}")
            return None
            
    def calculate_spread_regime(self, spread_pct: float) -> str:
        """Determine the volatility regime based on spread."""
        if spread_pct >= self.spread_thresholds['extreme_high']:
            return 'EXTREME_HIGH'  # Short ETH vol strongly
        elif spread_pct >= self.spread_thresholds['high']:
            return 'HIGH'  # Consider shorting ETH vol
        elif spread_pct >= self.spread_thresholds['normal_high']:
            return 'NORMAL_HIGH'  # Monitor
        elif spread_pct >= self.spread_thresholds['normal_low']:
            return 'NORMAL'  # No trade
        elif spread_pct >= self.spread_thresholds['low']:
            return 'NORMAL_LOW'  # Monitor
        elif spread_pct >= self.spread_thresholds['extreme_low']:
            return 'LOW'  # Consider longing ETH vol
        else:
            return 'EXTREME_LOW'  # Long ETH vol strongly
            
    def generate_signal(self, spread_pct: float, regime: str) -> Dict:
        """Generate trading signal based on spread regime."""
        signals = {
            'EXTREME_HIGH': {
                'action': 'SELL_ETH_VOL',
                'confidence': 0.9,
                'description': 'ETH IV extremely rich vs BTC - short ETH vol',
                'suggested_structure': 'Sell ETH straddle, buy BTC straddle (delta-hedged)'
            },
            'HIGH': {
                'action': 'CONSIDER_SELL_ETH_VOL',
                'confidence': 0.7,
                'description': 'ETH IV elevated vs BTC - monitor for short entry',
                'suggested_structure': 'Wait for confirmation or scale in'
            },
            'NORMAL_HIGH': {
                'action': 'MONITOR',
                'confidence': 0.5,
                'description': 'ETH IV slightly elevated - no immediate action',
                'suggested_structure': 'Watch for spread expansion'
            },
            'NORMAL': {
                'action': 'NO_TRADE',
                'confidence': 0.0,
                'description': 'Spread within normal range',
                'suggested_structure': 'Maintain delta-neutral positions'
            },
            'NORMAL_LOW': {
                'action': 'MONITOR',
                'confidence': 0.5,
                'description': 'ETH IV slightly depressed - no immediate action',
                'suggested_structure': 'Watch for spread compression'
            },
            'LOW': {
                'action': 'CONSIDER_BUY_ETH_VOL',
                'confidence': 0.7,
                'description': 'ETH IV cheap vs BTC - monitor for long entry',
                'suggested_structure': 'Wait for confirmation or scale in'
            },
            'EXTREME_LOW': {
                'action': 'BUY_ETH_VOL',
                'confidence': 0.9,
                'description': 'ETH IV extremely cheap vs BTC - long ETH vol',
                'suggested_structure': 'Buy ETH straddle, sell BTC straddle (delta-hedged)'
            }
        }
        
        return signals.get(regime, signals['NORMAL'])
        
    async def analyze_spread(self) -> Optional[Dict]:
        """Analyze the current ETH-BTC IV spread."""
        print(f"\n{'='*80}")
        print(f"VOLATILITY ARBITRAGE ANALYSIS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        
        iv_data = {}
        
        # Fetch IV data from all exchanges
        for ex_name, exchange in self.exchange_instances.items():
            print(f"📊 Fetching data from {ex_name.upper()}...")
            
            btc_iv = await self.fetch_option_iv(exchange, 'BTC')
            eth_iv = await self.fetch_option_iv(exchange, 'ETH')
            
            if btc_iv and eth_iv:
                iv_data[ex_name] = {
                    'btc': btc_iv,
                    'eth': eth_iv
                }
                
        if not iv_data:
            print("⚠️  No IV data available from any exchange")
            return None
            
        # Calculate spreads
        results = []
        for ex_name, data in iv_data.items():
            btc_iv_val = data['btc'].get('iv', 0)
            eth_iv_val = data['eth'].get('iv', 0)
            
            if btc_iv_val > 0 and eth_iv_val > 0:
                spread_pct = eth_iv_val - btc_iv_val
                spread_ratio = (eth_iv_val / btc_iv_val - 1) * 100
                
                regime = self.calculate_spread_regime(spread_pct)
                signal = self.generate_signal(spread_pct, regime)
                
                result = {
                    'exchange': ex_name,
                    'timestamp': datetime.now().isoformat(),
                    'btc_iv': btc_iv_val,
                    'eth_iv': eth_iv_val,
                    'spread_pct': spread_pct,
                    'spread_ratio': spread_ratio,
                    'regime': regime,
                    'signal': signal
                }
                results.append(result)
                
                # Add to history
                self.spread_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'exchange': ex_name,
                    'spread_pct': spread_pct
                })
                
        # Display results
        print(f"\n{'='*80}")
        print("IV SPREAD ANALYSIS")
        print(f"{'='*80}\n")
        
        for r in results:
            print(f"Exchange:     {r['exchange'].upper()}")
            print(f"BTC IV:       {r['btc_iv']:.2f}%")
            print(f"ETH IV:       {r['eth_iv']:.2f}%")
            print(f"Spread:       {r['spread_pct']:+.2f}% ({r['spread_ratio']:+.2f}%)")
            print(f"Regime:       {r['regime']}")
            print(f"Signal:       {r['signal']['action']}")
            print(f"Confidence:   {r['signal']['confidence']*100:.0f}%")
            print(f"Description:  {r['signal']['description']}")
            print(f"Structure:    {r['signal']['suggested_structure']}")
            print(f"{'-'*80}\n")
            
        # Summary
        if results:
            avg_spread = sum(r['spread_pct'] for r in results) / len(results)
            print(f"\n📈 SUMMARY:")
            print(f"   Average ETH-BTC IV Spread: {avg_spread:+.2f}%")
            print(f"   Threshold for Action: ±{self.min_spread_threshold}%")
            
            if abs(avg_spread) >= self.min_spread_threshold:
                action = "TRADEABLE OPPORTUNITY DETECTED" if abs(avg_spread) >= 10 else "MONITOR FOR ENTRY"
                print(f"   Status: 🎯 {action}")
            else:
                print(f"   Status: ⏸️  No immediate opportunity")
                
        return {
            'timestamp': datetime.now().isoformat(),
            'results': results,
            'history_count': len(self.spread_history)
        }
        
    async def run(self, cycles: Optional[int] = None):
        """Main monitoring loop."""
        print("\n" + "="*80)
        print("VOLATILITY ARBITRAGE MONITOR")
        print("ETH-BTC Implied Volatility Spread Tracker")
        print("="*80 + "\n")
        
        await self.initialize_exchanges()
        
        if not self.exchange_instances:
            print("❌ No exchanges available. Exiting.")
            return
            
        cycle = 0
        try:
            while cycles is None or cycle < cycles:
                cycle += 1
                result = await self.analyze_spread()
                
                if result:
                    # Save to file
                    output_dir = Path(__file__).parent.parent.parent / 'research' / 'vol_arb_data'
                    output_dir.mkdir(parents=True, exist_ok=True)
                    
                    output_file = output_dir / f'vol_analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                    with open(output_file, 'w') as f:
                        json.dump(result, f, indent=2)
                        
                    print(f"💾 Saved to: {output_file}")
                    
                if cycles is None or cycle < cycles:
                    print(f"\n⏱️  Next update in {self.update_interval} seconds...\n")
                    await asyncio.sleep(self.update_interval)
                    
        except KeyboardInterrupt:
            print("\n\n👋 Monitor stopped by user")
        finally:
            # Close exchange connections
            for exchange in self.exchange_instances.values():
                await exchange.close()
                
    def save_history(self):
        """Save spread history to file."""
        if self.spread_history:
            output_dir = Path(__file__).parent.parent.parent / 'research' / 'vol_arb_data'
            output_dir.mkdir(parents=True, exist_ok=True)
            
            history_file = output_dir / 'spread_history.json'
            with open(history_file, 'w') as f:
                json.dump(self.spread_history, f, indent=2)
                
            print(f"💾 History saved to: {history_file}")


async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='ETH-BTC Volatility Arbitrage Monitor')
    parser.add_argument('--exchanges', nargs='+', default=['deribit'],
                       help='Exchanges to monitor (default: deribit)')
    parser.add_argument('--threshold', type=float, default=5.0,
                       help='Minimum spread threshold %% (default: 5)')
    parser.add_argument('--interval', type=int, default=300,
                       help='Update interval in seconds (default: 300)')
    parser.add_argument('--cycles', type=int, default=None,
                       help='Number of cycles to run (default: infinite)')
    
    args = parser.parse_args()
    
    monitor = VolatilityArbitrageMonitor(
        exchanges=args.exchanges,
        min_spread_threshold=args.threshold,
        update_interval=args.interval
    )
    
    try:
        await monitor.run(cycles=args.cycles)
    finally:
        monitor.save_history()


if __name__ == '__main__':
    asyncio.run(main())
