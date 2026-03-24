"""
CCXT Binance Testnet Connector Test

Tests the CCXT connector with Binance testnet:
1. Fetches market data (ticker, OHLCV, funding rates)
2. Places a test limit order (small amount)
3. Checks account balance
4. Verifies connectivity

Usage:
    python3 test_ccxt_binance.py [--verbose]
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
import logging

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from trading_connectors.ccxt_connector import CCXTExchangeConnector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_market_data(connector: CCXTExchangeConnector, symbol: str = "BTCUSDT"):
    """Test fetching market data."""
    print("\n" + "=" * 70)
    print("TEST 1: Market Data Fetching")
    print("=" * 70)
    
    # Test 1a: Get ticker
    print(f"\n1a. Fetching ticker for {symbol}...")
    ticker = await connector.get_ticker(symbol)
    if ticker:
        print(f"  ✓ Ticker fetched successfully")
        print(f"    Symbol: {ticker.symbol}")
        print(f"    Bid: ${ticker.bid:,.2f}" if ticker.bid else "    Bid: N/A")
        print(f"    Ask: ${ticker.ask:,.2f}" if ticker.ask else "    Ask: N/A")
        print(f"    Last: ${ticker.last:,.2f}" if ticker.last else "    Last: N/A")
        print(f"    Mark Price: ${ticker.mark_price:,.2f}" if ticker.mark_price else "    Mark Price: N/A")
        print(f"    Volume 24h: {ticker.volume_24h:,.2f} USDT" if ticker.volume_24h else "    Volume 24h: N/A")
    else:
        print(f"  ✗ Failed to fetch ticker")
        return False
    
    # Test 1b: Get OHLCV
    print(f"\n1b. Fetching OHLCV data (1h, last 5 candles)...")
    ohlcv = await connector.get_ohlcv(symbol, timeframe='1h', limit=5)
    if not ohlcv.empty:
        print(f"  ✓ OHLCV fetched successfully ({len(ohlcv)} candles)")
        print(f"    Latest candle:")
        print(f"      Open:  ${ohlcv['open'].iloc[-1]:,.2f}")
        print(f"      High:  ${ohlcv['high'].iloc[-1]:,.2f}")
        print(f"      Low:   ${ohlcv['low'].iloc[-1]:,.2f}")
        print(f"      Close: ${ohlcv['close'].iloc[-1]:,.2f}")
        print(f"      Volume: {ohlcv['volume'].iloc[-1]:,.2f}")
    else:
        print(f"  ✗ Failed to fetch OHLCV")
        return False
    
    # Test 1c: Get funding rate
    print(f"\n1c. Fetching funding rate...")
    funding = await connector.get_funding_rate(symbol)
    if funding:
        print(f"  ✓ Funding rate fetched successfully")
        print(f"    Funding Rate: {funding.funding_rate:.6%}")
        print(f"    Mark Price: ${funding.mark_price:,.2f}" if funding.mark_price else "    Mark Price: N/A")
        print(f"    Index Price: ${funding.index_price:,.2f}" if funding.index_price else "    Index Price: N/A")
        print(f"    Next Funding: {funding.next_funding_time}")
    else:
        print(f"  ✗ Failed to fetch funding rate")
        return False
    
    return True


async def test_order_placement(connector: CCXTExchangeConnector, symbol: str = "BTCUSDT"):
    """Test placing orders on testnet."""
    print("\n" + "=" * 70)
    print("TEST 2: Order Placement (Testnet)")
    print("=" * 70)
    
    # Get current price
    ticker = await connector.get_ticker(symbol)
    if not ticker:
        print("  ✗ Cannot place order - failed to get ticker")
        return False
    
    current_price = ticker.last
    print(f"\nCurrent {symbol} price: ${current_price:,.2f}")
    
    # Calculate order price (slightly below market for limit buy)
    limit_price = round(current_price * 0.95, 2)  # 5% below market
    amount = 0.001  # Minimum order size for BTC
    
    print(f"\n2a. Placing LIMIT BUY order...")
    print(f"    Symbol: {symbol}")
    print(f"    Side: BUY")
    print(f"    Amount: {amount} BTC")
    print(f"    Price: ${limit_price:,.2f}")
    print(f"    Total: ${limit_price * amount:,.2f}")
    
    try:
        order = await connector.create_limit_order(
            symbol=symbol,
            side='buy',
            amount=amount,
            price=limit_price
        )
        
        if order:
            print(f"  ✓ Order placed successfully!")
            print(f"    Order ID: {order.get('id')}")
            print(f"    Status: {order.get('status')}")
            print(f"    Filled: {order.get('filled', 0)} / {order.get('amount', amount)}")
        else:
            print(f"  ✗ Order placement returned None")
            print(f"    Note: This may be expected if no API credentials are configured")
            return False
    except Exception as e:
        print(f"  ✗ Order placement failed: {e}")
        print(f"    Note: Testnet orders require API credentials")
        return False
    
    return True


async def test_account_balance(connector: CCXTExchangeConnector):
    """Test fetching account balance."""
    print("\n" + "=" * 70)
    print("TEST 3: Account Balance")
    print("=" * 70)
    
    print("\n3a. Fetching account balance...")
    try:
        balance = await connector.get_balance()
        
        if balance and 'total' in balance:
            print(f"  ✓ Balance fetched successfully")
            
            # Show non-zero balances
            non_zero = {k: v for k, v in balance['total'].items() if v > 0}
            
            if non_zero:
                print(f"\n    Non-zero balances:")
                for asset, amount in list(non_zero.items())[:5]:  # Show top 5
                    print(f"      {asset}: {amount}")
            else:
                print(f"    All balances are zero (expected for fresh testnet account)")
            
            print(f"\n    Free balances (top 5):")
            free = balance.get('free', {})
            for asset, amount in list(free.items())[:5]:
                if amount > 0:
                    print(f"      {asset}: {amount}")
        else:
            print(f"  ✗ Failed to fetch balance or empty balance")
            print(f"    Note: This requires API credentials")
            return False
    except Exception as e:
        print(f"  ✗ Balance fetch failed: {e}")
        print(f"    Note: This requires API credentials")
        return False
    
    return True


async def test_funding_rates_all(connector: CCXTExchangeConnector):
    """Test fetching all funding rates."""
    print("\n" + "=" * 70)
    print("TEST 4: All Funding Rates")
    print("=" * 70)
    
    print("\n4a. Fetching all funding rates...")
    rates = await connector.get_all_funding_rates()
    
    if rates:
        print(f"  ✓ Fetched {len(rates)} funding rates")
        
        # Show top 5 highest and lowest
        sorted_rates = sorted(rates, key=lambda x: x.funding_rate, reverse=True)
        
        print(f"\n    Top 5 highest funding rates:")
        for rate in sorted_rates[:5]:
            symbol_clean = rate.symbol.replace('/USDT:USDT', '')
            print(f"      {symbol_clean}: {rate.funding_rate:.6%}")
        
        print(f"\n    Top 5 lowest funding rates:")
        for rate in sorted_rates[-5:]:
            symbol_clean = rate.symbol.replace('/USDT:USDT', '')
            print(f"      {symbol_clean}: {rate.funding_rate:.6%}")
    else:
        print(f"  ✗ Failed to fetch funding rates")
        return False
    
    return True


async def run_all_tests():
    """Run all connectivity tests."""
    print("=" * 70)
    print("CCXT BINANCE TESTNET CONNECTOR TEST")
    print("=" * 70)
    print(f"\nTest Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Exchange: Binance Testnet")
    print()
    
    # Initialize connector (testnet mode, no credentials needed for public data)
    print("Initializing CCXT connector...")
    try:
        connector = CCXTExchangeConnector(
            exchange_id='binance',
            testnet=True
        )
        print("✓ Connector initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize connector: {e}")
        return
    
    results = {
        'market_data': False,
        'order_placement': False,
        'account_balance': False,
        'funding_rates': False
    }
    
    try:
        # Run tests
        results['market_data'] = await test_market_data(connector)
        results['order_placement'] = await test_order_placement(connector)
        results['account_balance'] = await test_account_balance(connector)
        results['funding_rates'] = await test_funding_rates_all(connector)
        
    except Exception as e:
        print(f"\n✗ Unexpected error during tests: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Close connector
        await connector.close()
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {test_name.replace('_', ' ').title():.<40} {status}")
    
    passed_count = sum(results.values())
    total_count = len(results)
    
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed! CCXT connector is working correctly.")
    elif passed_count >= 2:
        print("\n⚠️  Partial success. Public data APIs work. Order placement requires API keys.")
    else:
        print("\n❌ Multiple failures. Check connectivity and configuration.")
    
    # Save results
    results_file = Path(__file__).parent / 'ccxt_test_results.json'
    import json
    with open(results_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'exchange': 'binance',
            'testnet': True,
            'results': results,
            'summary': {
                'passed': passed_count,
                'total': total_count,
                'success_rate': passed_count / total_count if total_count > 0 else 0
            }
        }, f, indent=2)
    print(f"\nResults saved to: {results_file}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Test CCXT Binance Testnet Connector'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Run async tests
    asyncio.run(run_all_tests())


if __name__ == "__main__":
    main()
