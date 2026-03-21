#!/usr/bin/env python3
"""
Production Verification Script for Funding Arbitrage
Verifies connectivity to multiple exchanges via CCXT.
"""

import asyncio
import logging
import os
import argparse
import ccxt
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def verify_exchange(exchange_id, require_keys=True):
    """Verify connectivity and credentials for an exchange"""
    logger.info(f"Verifying {exchange_id}...")
    
    try:
        # Get exchange class
        exchange_class = getattr(ccxt, exchange_id)
        
        # Load keys from environment
        prefix = f"{exchange_id.upper()}_"
        api_key = os.getenv(f"{prefix}API_KEY")
        api_secret = os.getenv(f"{prefix}API_SECRET")
        passphrase = os.getenv(f"{prefix}PASSPHRASE")
        
        config = {'enableRateLimit': True}
        
        if api_key and api_secret:
            config['apiKey'] = api_key
            config['secret'] = api_secret
            if passphrase:
                config['password'] = passphrase
            logger.info(f"  ✓ Found API keys for {exchange_id}")
        elif require_keys:
            logger.error(f"  ✗ Missing API keys for {exchange_id}")
            return False
            
        exchange = exchange_class(config)
        
        # Test 1: Public Connectivity (Fetch Ticker)
        logger.info(f"  Testing public connectivity for {exchange_id}...")
        ticker = exchange.fetch_ticker('BTC/USDT' if exchange_id != 'okx' else 'BTC-USDT-SWAP')
        logger.info(f"  ✓ Public API OK (BTC Last: {ticker['last']})")
        
        # Test 2: Private Connectivity (if keys present)
        if api_key:
            logger.info(f"  Testing authenticated connectivity for {exchange_id}...")
            balance = exchange.fetch_balance()
            logger.info(f"  ✓ Private API OK (USDT Free: {balance.get('USDT', {}).get('free', 0)})")
            
        return True
        
    except Exception as e:
        logger.error(f"  ✗ {exchange_id} verification failed: {e}")
        return False

async def main():
    parser = argparse.ArgumentParser(description='Production Verifier')
    parser.add_argument('--exchanges', nargs='+', default=['binance', 'bybit'], 
                        help='Exchanges to verify')
    args = parser.parse_args()
    
    load_dotenv()
    
    logger.info("=== Funding Arb Production Verification ===")
    
    tasks = [verify_exchange(ex) for ex in args.exchanges]
    results = await asyncio.gather(*tasks)
    
    print("\n" + "="*50)
    if all(results):
        print("✅ PRODUCTION READY: All exchanges verified!")
        return 0
    else:
        print("❌ NOT READY: Some verification checks failed.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
