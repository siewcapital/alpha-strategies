import os
import sys
import ccxt
import pandas as pd
from datetime import datetime

# Set up paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)

class SimpleBasisMonitor:
    def __init__(self):
        self.exchanges = ['binance', 'bybit', 'okx']
        # Use perpetual futures symbols (swap markets)
        self.symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']
        
    def get_funding_sync(self):
        """Get funding rates synchronously."""
        opportunities = []
        
        for exchange_id in self.exchanges:
            try:
                exchange_class = getattr(ccxt, exchange_id)
                exchange = exchange_class({'enableRateLimit': True})
                
                for symbol in self.symbols:
                    try:
                        # Fetch funding rate
                        funding = exchange.fetch_funding_rate(symbol)
                        
                        funding_rate = funding.get('fundingRate', 0) or 0
                        # Annualize: 8h funding * 3 per day * 365 days
                        annualized = funding_rate * 3 * 365 * 100
                        
                        opportunities.append({
                            'exchange': exchange_id,
                            'symbol': symbol.replace('/USDT:USDT', ''),
                            'funding_rate': funding_rate,
                            'annualized_yield': annualized,
                            'mark_price': funding.get('markPrice', 0),
                            'next_funding': funding.get('fundingTimestamp'),
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })
                    except Exception as e:
                        print(f"  {symbol}: {e}")
                        
            except Exception as e:
                print(f"Error with {exchange_id}: {e}")
                
        return pd.DataFrame(opportunities)

if __name__ == "__main__":
    monitor = SimpleBasisMonitor()
    print("Fetching basis trade opportunities...\n")
    df = monitor.get_funding_sync()
    
    if not df.empty:
        df = df.sort_values(by='annualized_yield', ascending=False)
        
        print("\n" + "="*70)
        print("CURRENT BASIS TRADE OPPORTUNITIES (Funding Rate Arbitrage)")
        print("="*70)
        print(f"{'Exchange':<12} {'Symbol':<8} {'Funding Rate':<15} {'Annualized %':<15} {'Mark Price':<15}")
        print("-"*70)
        for _, row in df.iterrows():
            print(f"{row['exchange']:<12} {row['symbol']:<8} {row['funding_rate']:<15.6f} {row['annualized_yield']:<15.2f} ${row['mark_price']:<14,.2f}")
        
        # Save results
        results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
        os.makedirs(results_dir, exist_ok=True)
        output_path = os.path.join(results_dir, f'opportunities_{datetime.now().strftime("%Y%m%d_%H%M")}.csv')
        df.to_csv(output_path, index=False)
        print("="*70)
        print(f"\n✓ Results saved to: {output_path}")
        
        # Summary stats
        best = df.iloc[0]
        worst = df.iloc[-1]
        avg_yield = df['annualized_yield'].mean()
        
        print(f"\n--- SUMMARY ---")
        print(f"Best:  {best['symbol']} on {best['exchange'].upper()} @ {best['annualized_yield']:+.2f}% annualized")
        print(f"Worst: {worst['symbol']} on {worst['exchange'].upper()} @ {worst['annualized_yield']:+.2f}% annualized")
        print(f"Average yield: {avg_yield:+.2f}%")
        
        # Highlight opportunities > 10%
        good_ops = df[df['annualized_yield'] > 10]
        if not good_ops.empty:
            print(f"\n🔥 HIGH-YIELD OPPORTUNITIES (>10%):")
            for _, row in good_ops.iterrows():
                print(f"   {row['symbol']} on {row['exchange'].upper()}: {row['annualized_yield']:+.2f}%")
    else:
        print("No opportunities found.")
