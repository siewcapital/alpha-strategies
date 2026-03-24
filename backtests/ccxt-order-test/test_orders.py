"""
CCXT Binance Testnet - Order Placement & Cancellation Test
Tests actual order execution capabilities on Binance testnet.
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
import json
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'trading_connectors'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

import ccxt


class CCXTOrderTest:
    """Test order placement and cancellation on Binance testnet."""
    
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'tests': {},
            'overall_status': 'pending',
            'orders': []
        }
        self.exchange = None
    
    async def setup_exchange(self):
        """Initialize Binance testnet connection."""
        logger.info("="*60)
        logger.info("Setting up Binance Testnet Connection")
        logger.info("="*60)
        
        try:
            # For testnet, we can use public data without credentials
            # But for order placement, we need testnet API keys
            config = {
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'
                }
            }
            
            # Try to load credentials from environment
            api_key = os.getenv('BINANCE_TESTNET_API_KEY', '')
            api_secret = os.getenv('BINANCE_TESTNET_API_SECRET', '')
            
            if api_key and api_secret:
                config['apiKey'] = api_key
                config['secret'] = api_secret
                logger.info("Using provided API credentials")
            else:
                logger.info("No API credentials - will test public endpoints only")
            
            # Initialize exchange
            self.exchange = ccxt.binance(config)
            
            # Configure testnet URLs
            self.exchange.set_sandbox_mode(True)
            
            # Load markets
            markets = self.exchange.load_markets()
            logger.info(f"✓ Loaded {len(markets)} markets")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to setup exchange: {e}")
            return False
    
    async def test_public_endpoints(self):
        """Test public data endpoints."""
        logger.info("\n" + "="*60)
        logger.info("TEST 1: Public Endpoints")
        logger.info("="*60)
        
        test_results = {'status': 'running', 'tests': {}}
        
        try:
            # Test 1a: Fetch ticker
            logger.info("\n[Test 1a] Fetching BTC/USDT ticker...")
            ticker = self.exchange.fetch_ticker('BTC/USDT:USDT')
            bid_str = f"${ticker['bid']:,.2f}" if ticker['bid'] else "N/A"
            ask_str = f"${ticker['ask']:,.2f}" if ticker['ask'] else "N/A"
            last_str = f"${ticker['last']:,.2f}" if ticker['last'] else "N/A"
            logger.info(f"  ✓ Bid: {bid_str}")
            logger.info(f"  ✓ Ask: {ask_str}")
            logger.info(f"  ✓ Last: {last_str}")
            test_results['tests']['ticker'] = {'status': 'passed', 'last': ticker['last']}
            
            # Test 1b: Fetch OHLCV
            logger.info("\n[Test 1b] Fetching OHLCV data...")
            ohlcv = self.exchange.fetch_ohlcv('BTC/USDT:USDT', '1h', limit=10)
            logger.info(f"  ✓ Fetched {len(ohlcv)} candles")
            test_results['tests']['ohlcv'] = {'status': 'passed', 'candles': len(ohlcv)}
            
            # Test 1c: Fetch funding rate
            logger.info("\n[Test 1c] Fetching funding rate...")
            funding = self.exchange.fetch_funding_rate('BTC/USDT:USDT')
            logger.info(f"  ✓ Funding Rate: {funding['fundingRate']:.6%}")
            test_results['tests']['funding_rate'] = {
                'status': 'passed', 
                'rate': funding['fundingRate']
            }
            
            test_results['status'] = 'passed'
            
        except Exception as e:
            logger.error(f"✗ Public endpoints test failed: {e}")
            test_results['status'] = 'failed'
            test_results['error'] = str(e)
        
        self.results['tests']['public_endpoints'] = test_results
        return test_results['status'] == 'passed'
    
    async def test_order_placement(self):
        """Test order placement and cancellation."""
        logger.info("\n" + "="*60)
        logger.info("TEST 2: Order Placement & Cancellation")
        logger.info("="*60)
        
        test_results = {
            'status': 'running', 
            'tests': {},
            'orders': []
        }
        
        # Check if we have credentials
        if not self.exchange.apiKey:
            logger.info("⚠ No API credentials - skipping order tests")
            test_results['status'] = 'skipped'
            test_results['reason'] = 'no_credentials'
            self.results['tests']['order_placement'] = test_results
            return True
        
        try:
            symbol = 'SOL/USDT:USDT'
            
            # Get current price
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            logger.info(f"\nCurrent {symbol} price: ${current_price:,.2f}")
            
            # Test 2a: Place a limit order (far from market to avoid fills)
            logger.info("\n[Test 2a] Placing LIMIT buy order...")
            limit_price = current_price * 0.8  # 20% below market (won't fill)
            amount = 0.1  # Small amount
            
            try:
                order = self.exchange.create_limit_buy_order(
                    symbol, amount, limit_price
                )
                logger.info(f"  ✓ Limit order placed: {order['id']}")
                logger.info(f"  ✓ Status: {order['status']}")
                logger.info(f"  ✓ Price: ${order['price']:,.2f}")
                logger.info(f"  ✓ Amount: {order['amount']}")
                
                test_results['tests']['limit_order'] = {
                    'status': 'passed',
                    'order_id': order['id'],
                    'price': order['price'],
                    'amount': order['amount']
                }
                test_results['orders'].append(order['id'])
                
                # Test 2b: Check order status
                logger.info("\n[Test 2b] Checking order status...")
                order_status = self.exchange.fetch_order(order['id'], symbol)
                logger.info(f"  ✓ Order status: {order_status['status']}")
                test_results['tests']['order_status'] = {
                    'status': 'passed',
                    'order_status': order_status['status']
                }
                
                # Test 2c: Cancel the order
                logger.info("\n[Test 2c] Cancelling order...")
                cancel_result = self.exchange.cancel_order(order['id'], symbol)
                logger.info(f"  ✓ Order cancelled successfully")
                test_results['tests']['cancel_order'] = {'status': 'passed'}
                
            except ccxt.AuthenticationError as e:
                logger.error(f"  ✗ Authentication failed: {e}")
                test_results['tests']['limit_order'] = {
                    'status': 'failed',
                    'error': 'authentication_failed'
                }
                test_results['status'] = 'failed'
                self.results['tests']['order_placement'] = test_results
                return False
            
            except ccxt.InsufficientFunds as e:
                logger.error(f"  ✗ Insufficient funds: {e}")
                test_results['tests']['limit_order'] = {
                    'status': 'failed',
                    'error': 'insufficient_funds'
                }
                test_results['status'] = 'failed'
                self.results['tests']['order_placement'] = test_results
                return False
            
            # Test 2d: Place and cancel another order to verify consistency
            logger.info("\n[Test 2d] Testing order placement consistency...")
            limit_price2 = current_price * 0.85
            order2 = self.exchange.create_limit_buy_order(
                symbol, amount, limit_price2
            )
            logger.info(f"  ✓ Second order placed: {order2['id']}")
            
            # Cancel immediately
            self.exchange.cancel_order(order2['id'], symbol)
            logger.info(f"  ✓ Second order cancelled")
            test_results['tests']['consistency'] = {'status': 'passed'}
            
            test_results['status'] = 'passed'
            
        except Exception as e:
            logger.error(f"✗ Order placement test failed: {e}")
            test_results['status'] = 'failed'
            test_results['error'] = str(e)
        
        self.results['tests']['order_placement'] = test_results
        return test_results['status'] in ['passed', 'skipped']
    
    async def test_order_book(self):
        """Test order book fetching."""
        logger.info("\n" + "="*60)
        logger.info("TEST 3: Order Book (L2 Data)")
        logger.info("="*60)
        
        test_results = {'status': 'running', 'tests': {}}
        
        try:
            symbol = 'SOL/USDT:USDT'
            
            # Fetch order book
            logger.info(f"\nFetching order book for {symbol}...")
            order_book = self.exchange.fetch_order_book(symbol, limit=20)
            
            bids = order_book['bids']
            asks = order_book['asks']
            
            logger.info(f"  ✓ Bids: {len(bids)} levels")
            logger.info(f"  ✓ Asks: {len(asks)} levels")
            
            if bids and asks:
                best_bid = bids[0][0]
                best_ask = asks[0][0]
                spread = best_ask - best_bid
                spread_pct = (spread / best_bid) * 100
                
                logger.info(f"  ✓ Best Bid: ${best_bid:,.2f}")
                logger.info(f"  ✓ Best Ask: ${best_ask:,.2f}")
                logger.info(f"  ✓ Spread: ${spread:.2f} ({spread_pct:.4f}%)")
                
                test_results['tests']['order_book'] = {
                    'status': 'passed',
                    'bid_levels': len(bids),
                    'ask_levels': len(asks),
                    'spread_pct': spread_pct
                }
            
            test_results['status'] = 'passed'
            
        except Exception as e:
            logger.error(f"✗ Order book test failed: {e}")
            test_results['status'] = 'failed'
            test_results['error'] = str(e)
        
        self.results['tests']['order_book'] = test_results
        return test_results['status'] == 'passed'
    
    async def run_all_tests(self):
        """Run all order tests."""
        logger.info("\n" + "="*60)
        logger.info("CCXT BINANCE TESTNET - ORDER TEST SUITE")
        logger.info("="*60)
        logger.info(f"Start Time: {datetime.now()}")
        logger.info("="*60)
        
        # Setup exchange
        if not await self.setup_exchange():
            self.results['overall_status'] = 'failed'
            return self.results
        
        all_passed = True
        
        # Run tests
        all_passed &= await self.test_public_endpoints()
        all_passed &= await self.test_order_placement()
        all_passed &= await self.test_order_book()
        
        # Determine overall status
        self.results['overall_status'] = 'passed' if all_passed else 'failed'
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("TEST SUMMARY")
        logger.info("="*60)
        
        for test_name, test_data in self.results['tests'].items():
            status = test_data.get('status', 'unknown')
            icon = "✓" if status == 'passed' else "⚠" if status == 'skipped' else "✗"
            logger.info(f"{icon} {test_name}: {status.upper()}")
        
        logger.info("="*60)
        logger.info(f"Overall Status: {self.results['overall_status'].upper()}")
        logger.info("="*60)
        
        # Save results
        output_dir = Path(__file__).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        results_file = output_dir / "ccxt_order_test_results.json"
        
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        
        logger.info(f"\nResults saved to: {results_file}")
        
        return self.results


async def main():
    """Main entry point."""
    tester = CCXTOrderTest()
    results = await tester.run_all_tests()
    
    # Return exit code
    return 0 if results['overall_status'] == 'passed' else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
