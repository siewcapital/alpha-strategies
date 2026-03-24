import os
import sys
import asyncio
import ccxt
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

# Set up paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)

@dataclass
class BasisOpportunity:
    """Represents a basis trade opportunity."""
    exchange: str
    symbol: str
    spot_price: float
    futures_price: float
    basis: float  # Annualized basis percentage
    expiry_days: int
    timestamp: datetime
    
    @property
    def is_contango(self) -> bool:
        """Returns True if futures > spot (normal contango)."""
        return self.basis > 0
    
    @property
    def annualized_yield(self) -> float:
        """Returns annualized yield percentage."""
        return self.basis


class BasisMonitor:
    """
    Monitors basis opportunities across multiple exchanges.
    
    Tracks the price difference between spot and futures markets
    to identify cash-and-carry arbitrage opportunities.
    """
    
    def __init__(self, exchanges: List[str] = None, min_annualized_yield: float = 5.0):
        """
        Initialize the basis monitor.
        
        Args:
            exchanges: List of exchange IDs to monitor
            min_annualized_yield: Minimum annualized yield to report (in %)
        """
        self.exchanges = exchanges or ['binance', 'bybit', 'okx']
        self.min_annualized_yield = min_annualized_yield
        self.symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
        self.exchange_instances = {}
        
    def _get_exchange(self, exchange_id: str):
        """Get or create exchange instance."""
        if exchange_id not in self.exchange_instances:
            try:
                exchange_class = getattr(ccxt, exchange_id)
                self.exchange_instances[exchange_id] = exchange_class({
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'spot',
                    }
                })
            except Exception as e:
                print(f"Error initializing {exchange_id}: {e}")
                return None
        return self.exchange_instances[exchange_id]
    
    def fetch_basis_opportunities(self) -> List[BasisOpportunity]:
        """
        Fetch current basis opportunities across all exchanges.
        
        Returns:
            List of BasisOpportunity objects sorted by yield (highest first)
        """
        opportunities = []
        
        for exchange_id in self.exchanges:
            exchange = self._get_exchange(exchange_id)
            if not exchange:
                continue
                
            try:
                exchange_opps = self._fetch_exchange_basis(exchange, exchange_id)
                opportunities.extend(exchange_opps)
            except Exception as e:
                print(f"Error fetching from {exchange_id}: {e}")
                
        # Sort by annualized yield (descending)
        opportunities.sort(key=lambda x: x.annualized_yield, reverse=True)
        return opportunities
    
    def _fetch_exchange_basis(self, exchange, exchange_id: str) -> List[BasisOpportunity]:
        """Fetch basis data for a specific exchange."""
        opportunities = []
        
        for symbol in self.symbols:
            try:
                # Get spot price
                spot_ticker = exchange.fetch_ticker(symbol)
                spot_price = spot_ticker.get('last', 0)
                
                # Get perpetual futures price
                perp_symbol = f"{symbol.replace('/USDT', '')}/USDT:USDT"
                try:
                    perp_ticker = exchange.fetch_ticker(perp_symbol)
                    futures_price = perp_ticker.get('last', 0)
                    
                    # Calculate basis
                    if spot_price > 0 and futures_price > 0:
                        price_diff = (futures_price - spot_price) / spot_price
                        # Annualize (perpetual funding rate is 8h, so * 3 * 365)
                        annualized = price_diff * 3 * 365 * 100
                        
                        opp = BasisOpportunity(
                            exchange=exchange_id,
                            symbol=symbol.replace('/USDT', ''),
                            spot_price=spot_price,
                            futures_price=futures_price,
                            basis=annualized,
                            expiry_days=0,  # Perpetual
                            timestamp=datetime.now()
                        )
                        
                        if abs(annualized) >= self.min_annualized_yield:
                            opportunities.append(opp)
                            
                except Exception as e:
                    # Perpetual market might not exist
                    pass
                    
            except Exception as e:
                print(f"  Error with {symbol}: {e}")
                
        return opportunities
    
    def get_funding_rates(self) -> List[Dict]:
        """Get current funding rates for perpetual futures."""
        funding_data = []
        
        for exchange_id in self.exchanges:
            exchange = self._get_exchange(exchange_id)
            if not exchange:
                continue
                
            try:
                # Switch to swap markets for funding rates
                if hasattr(exchange, 'options'):
                    exchange.options['defaultType'] = 'swap'
                    
                for symbol in self.symbols:
                    try:
                        perp_symbol = f"{symbol.replace('/USDT', '')}/USDT:USDT"
                        funding = exchange.fetch_funding_rate(perp_symbol)
                        
                        funding_rate = funding.get('fundingRate', 0) or 0
                        annualized = funding_rate * 3 * 365 * 100
                        
                        funding_data.append({
                            'exchange': exchange_id,
                            'symbol': symbol.replace('/USDT', ''),
                            'funding_rate': funding_rate,
                            'annualized_yield': annualized,
                            'mark_price': funding.get('markPrice', 0),
                            'index_price': funding.get('indexPrice', 0),
                            'next_funding': funding.get('fundingTimestamp'),
                            'timestamp': datetime.now().isoformat()
                        })
                    except Exception as e:
                        pass
                        
            except Exception as e:
                print(f"Error fetching funding from {exchange_id}: {e}")
                
        return funding_data
    
    def print_opportunities(self, opportunities: List[BasisOpportunity] = None):
        """Pretty print basis opportunities."""
        if opportunities is None:
            opportunities = self.fetch_basis_opportunities()
            
        if not opportunities:
            print("No basis opportunities found meeting criteria.")
            return
            
        print("\n" + "="*80)
        print("BASIS TRADE OPPORTUNITIES")
        print("="*80)
        print(f"{'Exchange':<12} {'Symbol':<8} {'Spot':<14} {'Perp':<14} {'Basis %':<12} {'Type':<10}")
        print("-"*80)
        
        for opp in opportunities:
            basis_type = "Contango" if opp.is_contango else "Backwardation"
            print(f"{opp.exchange:<12} {opp.symbol:<8} ${opp.spot_price:<13,.2f} "
                  f"${opp.futures_price:<13,.2f} {opp.basis:>+10.2f}% {basis_type:<10}")
                  
        print("="*80)
        
        # Summary
        best = opportunities[0]
        print(f"\nBest Opportunity: {best.symbol} on {best.exchange.upper()}")
        print(f"  Annualized Yield: {best.annualized_yield:+.2f}%")
        print(f"  Spot: ${best.spot_price:,.2f} | Perp: ${best.futures_price:,.2f}")


def main():
    """Main entry point for basis monitoring."""
    monitor = BasisMonitor(min_annualized_yield=3.0)
    
    print("Fetching basis trade opportunities...\n")
    opportunities = monitor.fetch_basis_opportunities()
    monitor.print_opportunities(opportunities)
    
    # Also fetch funding rates
    print("\n" + "="*80)
    print("FUNDING RATE DATA")
    print("="*80)
    
    funding_data = monitor.get_funding_rates()
    if funding_data:
        print(f"{'Exchange':<12} {'Symbol':<8} {'Funding Rate':<15} {'Annualized %':<15}")
        print("-"*80)
        for data in sorted(funding_data, key=lambda x: x['annualized_yield'], reverse=True):
            print(f"{data['exchange']:<12} {data['symbol']:<8} "
                  f"{data['funding_rate']:<15.6f} {data['annualized_yield']:>+14.2f}%")
    
    # Save results
    results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
    os.makedirs(results_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    
    # Save opportunities
    if opportunities:
        opps_file = os.path.join(results_dir, f'basis_opportunities_{timestamp}.json')
        with open(opps_file, 'w') as f:
            json.dump([{
                'exchange': o.exchange,
                'symbol': o.symbol,
                'spot_price': o.spot_price,
                'futures_price': o.futures_price,
                'basis': o.basis,
                'timestamp': o.timestamp.isoformat()
            } for o in opportunities], f, indent=2)
        print(f"\n✓ Opportunities saved to: {opps_file}")
    
    # Save funding data
    if funding_data:
        funding_file = os.path.join(results_dir, f'funding_rates_{timestamp}.json')
        with open(funding_file, 'w') as f:
            json.dump(funding_data, f, indent=2)
        print(f"✓ Funding rates saved to: {funding_file}")


if __name__ == "__main__":
    main()
