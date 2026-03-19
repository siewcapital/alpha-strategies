"""
CCXT Binance Testnet Validation Script
Tests the CCXT connector with Binance testnet for paper trading.
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from ccxt_connector import CCXTExchangeConnector, MultiExchangeConnector, ExchangeCredentials


class CCXTTestnetValidator:
    """
    Validates CCXT connector functionality with Binance testnet.
    Performs comprehensive tests for paper trading readiness.
    """
    
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'tests': {},
            'overall_status': 'pending'
        }
    
    async def test_public_data_fetching(self):
        """Test public market data fetching (no credentials needed)."""
        logger.info("="*60)
        logger.info("TEST 1: Public Data Fetching")
        logger.info("="*60)
        
        test_results = {
            'status': 'running',
            'tests': {}
        }
        
        try:
            # Initialize connector in testnet mode
            connector = CCXTExchangeConnector('binance', testnet=True)
            
            # Test 1a: Fetch funding rate for BTC
            logger.info("\n[Test 1a] Fetching BTC funding rate...")
            funding = await connector.get_funding_rate('BTCUSDT')
            if funding:
                logger.info(f"  ✓ BTC Funding Rate: {funding.funding_rate:.6%}")
                logger.info(f"  ✓ Next Funding: {funding.next_funding_time}")
                logger.info(f"  ✓ Mark Price: ${funding.mark_price:,.2f}")
                test_results['tests']['funding_rate'] = {
                    'status': 'passed',
                    'rate': funding.funding_rate,
                    'mark_price': funding.mark_price
                }
            else:
                test_results['tests']['funding_rate'] = {'status': 'failed'}
            
            # Test 1b: Fetch all funding rates
            logger.info("\n[Test 1b] Fetching all funding rates...")
            all_rates = await connector.get_all_funding_rates()
            logger.info(f"  ✓ Fetched {len(all_rates)} funding rates")
            symbols = [r.symbol for r in all_rates[:5]]
            logger.info(f"  ✓ Sample symbols: {symbols}")
            test_results['tests']['all_funding_rates'] = {
                'status': 'passed',
                'count': len(all_rates)
            }
            
            # Test 1c: Fetch ticker data
            logger.info("\n[Test 1c] Fetching BTC ticker...")
            ticker = await connector.get_ticker('BTCUSDT')
            if ticker:
                bid_str = f"${ticker.bid:,.2f}" if ticker.bid else "N/A"
                ask_str = f"${ticker.ask:,.2f}" if ticker.ask else "N/A"
                last_str = f"${ticker.last:,.2f}" if ticker.last else "N/A"
                logger.info(f"  ✓ Bid: {bid_str}")
                logger.info(f"  ✓ Ask: {ask_str}")
                logger.info(f"  ✓ Last: {last_str}")
                test_results['tests']['ticker'] = {
                    'status': 'passed',
                    'bid': ticker.bid,
                    'ask': ticker.ask
                }
            else:
                test_results['tests']['ticker'] = {'status': 'failed'}
            
            # Test 1d: Fetch OHLCV data
            logger.info("\n[Test 1d] Fetching OHLCV data (24h 1h candles)...")
            ohlcv = await connector.get_ohlcv('BTCUSDT', timeframe='1h', limit=24)
            if not ohlcv.empty:
                logger.info(f"  ✓ Fetched {len(ohlcv)} candles")
                logger.info(f"  ✓ Latest close: ${ohlcv['close'].iloc[-1]:,.2f}")
                logger.info(f"  ✓ 24h range: ${ohlcv['low'].min():,.2f} - ${ohlcv['high'].max():,.2f}")
                test_results['tests']['ohlcv'] = {
                    'status': 'passed',
                    'candles': len(ohlcv),
                    'latest_close': ohlcv['close'].iloc[-1]
                }
            else:
                test_results['tests']['ohlcv'] = {'status': 'failed'}
            
            await connector.close()
            test_results['status'] = 'passed'
            
        except Exception as e:
            logger.error(f"  ✗ Public data test failed: {e}")
            test_results['status'] = 'failed'
            test_results['error'] = str(e)
        
        self.results['tests']['public_data'] = test_results
        return test_results['status'] == 'passed'
    
    async def test_multi_exchange(self):
        """Test multi-exchange connector."""
        logger.info("\n" + "="*60)
        logger.info("TEST 2: Multi-Exchange Connector")
        logger.info("="*60)
        
        test_results = {
            'status': 'running',
            'tests': {}
        }
        
        try:
            multi = MultiExchangeConnector(testnet=True)
            
            # Add Binance
            logger.info("\n[Test 2a] Adding Binance...")
            multi.add_exchange('binance')
            logger.info("  ✓ Binance added")
            
            # Fetch funding rates from all exchanges
            logger.info("\n[Test 2b] Fetching funding rates from all exchanges...")
            all_rates = await multi.get_all_funding_rates()
            for exchange, rates in all_rates.items():
                logger.info(f"  ✓ {exchange}: {len(rates)} rates")
            
            test_results['tests']['multi_fetch'] = {
                'status': 'passed',
                'exchanges': list(all_rates.keys())
            }
            
            # Test funding differentials
            logger.info("\n[Test 2c] Calculating funding differentials...")
            diffs = await multi.get_funding_differentials(symbols=['BTC', 'ETH', 'SOL'])
            if not diffs.empty:
                logger.info(f"  ✓ Found {len(diffs)} arbitrage opportunities")
                top_diffs = diffs.nlargest(3, 'differential_bps')
                for _, row in top_diffs.iterrows():
                    logger.info(f"    {row['symbol']}: {row['differential_bps']:.2f} bps "
                              f"({row['long_exchange']} long / {row['short_exchange']} short)")
                test_results['tests']['differentials'] = {
                    'status': 'passed',
                    'opportunities': len(diffs)
                }
            else:
                test_results['tests']['differentials'] = {'status': 'no_data'}
            
            await multi.close_all()
            test_results['status'] = 'passed'
            
        except Exception as e:
            logger.error(f"  ✗ Multi-exchange test failed: {e}")
            test_results['status'] = 'failed'
            test_results['error'] = str(e)
        
        self.results['tests']['multi_exchange'] = test_results
        return test_results['status'] == 'passed'
    
    async def test_authenticated_endpoints(self):
        """Test authenticated endpoints (requires API keys)."""
        logger.info("\n" + "="*60)
        logger.info("TEST 3: Authenticated Endpoints (Optional)")
        logger.info("="*60)
        
        test_results = {
            'status': 'running',
            'tests': {}
        }
        
        # Check for credentials
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            logger.info("  ⚠ No API credentials found. Skipping authenticated tests.")
            logger.info("  Set BINANCE_API_KEY and BINANCE_API_SECRET to test.")
            test_results['status'] = 'skipped'
            test_results['reason'] = 'no_credentials'
            self.results['tests']['authenticated'] = test_results
            return True
        
        try:
            creds = ExchangeCredentials(
                api_key=api_key,
                api_secret=api_secret,
                testnet=True
            )
            
            connector = CCXTExchangeConnector('binance', credentials=creds, testnet=True)
            
            # Test balance fetch
            logger.info("\n[Test 3a] Fetching account balance...")
            balance = await connector.get_balance()
            if balance:
                total = balance.get('total', {})
                usdt_balance = total.get('USDT', 0)
                logger.info(f"  ✓ USDT Balance: ${usdt_balance:,.2f}")
                test_results['tests']['balance'] = {
                    'status': 'passed',
                    'usdt': usdt_balance
                }
            else:
                test_results['tests']['balance'] = {'status': 'failed'}
            
            # Test position fetch
            logger.info("\n[Test 3b] Fetching positions...")
            positions = await connector.get_positions()
            logger.info(f"  ✓ Open positions: {len(positions)}")
            test_results['tests']['positions'] = {
                'status': 'passed',
                'count': len(positions)
            }
            
            await connector.close()
            test_results['status'] = 'passed'
            
        except Exception as e:
            logger.error(f"  ✗ Authenticated test failed: {e}")
            test_results['status'] = 'failed'
            test_results['error'] = str(e)
        
        self.results['tests']['authenticated'] = test_results
        return test_results['status'] in ['passed', 'skipped']
    
    async def test_paper_trading_simulation(self):
        """Simulate paper trading scenarios."""
        logger.info("\n" + "="*60)
        logger.info("TEST 4: Paper Trading Simulation")
        logger.info("="*60)
        
        test_results = {
            'status': 'running',
            'tests': {}
        }
        
        try:
            connector = CCXTExchangeConnector('binance', testnet=True)
            
            # Simulate fetching data for strategy decisions
            logger.info("\n[Test 4a] Simulating strategy data requirements...")
            
            symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
            funding_data = {}
            
            for symbol in symbols:
                funding = await connector.get_funding_rate(symbol)
                ticker = await connector.get_ticker(symbol)
                ohlcv = await connector.get_ohlcv(symbol, timeframe='1h', limit=24)
                
                if funding and ticker and not ohlcv.empty:
                    funding_data[symbol] = {
                        'funding_rate': funding.funding_rate,
                        'mark_price': funding.mark_price,
                        'bid': ticker.bid,
                        'ask': ticker.ask,
                        'volatility': ohlcv['close'].pct_change().std() * 100
                    }
                    logger.info(f"  ✓ {symbol}: Funding={funding.funding_rate:.4%}, "
                              f"Price=${ticker.last:,.2f}")
            
            test_results['tests']['data_requirements'] = {
                'status': 'passed',
                'symbols_data': len(funding_data)
            }
            
            # Simulate arbitrage opportunity detection
            logger.info("\n[Test 4b] Simulating arbitrage detection...")
            if len(funding_data) >= 2:
                # Calculate synthetic differentials
                rates = {s: d['funding_rate'] for s, d in funding_data.items()}
                max_rate = max(rates.values())
                min_rate = min(rates.values())
                diff = max_rate - min_rate
                
                logger.info(f"  ✓ Funding rate range: {min_rate:.4%} to {max_rate:.4%}")
                logger.info(f"  ✓ Max differential: {diff:.4%} ({diff*10000:.2f} bps)")
                
                if diff > 0.0001:  # 1 bps threshold
                    logger.info(f"  ✓ Arbitrage opportunity detected!")
                
                test_results['tests']['arbitrage_detection'] = {
                    'status': 'passed',
                    'max_differential_bps': diff * 10000
                }
            
            await connector.close()
            test_results['status'] = 'passed'
            
        except Exception as e:
            logger.error(f"  ✗ Paper trading test failed: {e}")
            test_results['status'] = 'failed'
            test_results['error'] = str(e)
        
        self.results['tests']['paper_trading'] = test_results
        return test_results['status'] == 'passed'
    
    async def run_all_tests(self):
        """Run all validation tests."""
        logger.info("\n" + "="*60)
        logger.info("CCXT BINANCE TESTNET VALIDATION")
        logger.info("="*60)
        logger.info(f"Start Time: {datetime.now()}")
        logger.info("="*60)
        
        all_passed = True
        
        # Run tests
        all_passed &= await self.test_public_data_fetching()
        all_passed &= await self.test_multi_exchange()
        all_passed &= await self.test_authenticated_endpoints()
        all_passed &= await self.test_paper_trading_simulation()
        
        # Determine overall status
        self.results['overall_status'] = 'passed' if all_passed else 'failed'
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("VALIDATION SUMMARY")
        logger.info("="*60)
        
        for test_name, test_data in self.results['tests'].items():
            status = test_data.get('status', 'unknown')
            icon = "✓" if status == 'passed' else "⚠" if status == 'skipped' else "✗"
            logger.info(f"{icon} {test_name}: {status.upper()}")
        
        logger.info("="*60)
        logger.info(f"Overall Status: {self.results['overall_status'].upper()}")
        logger.info("="*60)
        
        # Save results
        results_file = Path(__file__).parent / "ccxt_testnet_validation.json"
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {results_file}")
        
        return self.results


async def main():
    """Main entry point."""
    validator = CCXTTestnetValidator()
    results = await validator.run_all_tests()
    
    # Return exit code based on status
    return 0 if results['overall_status'] == 'passed' else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
