"""
Additional Backtests - Multi-Asset Validation

Tests strategy on multiple assets and timeframes for robustness.
"""

import sys
sys.path.insert(0, '/Users/siewbrayden/.openclaw/agents/atlas/workspace/alpha-hunter/strategies/hoffman-irb')

from backtest import run_comprehensive_backtest, print_results, generate_visualizations
import pandas as pd
from datetime import datetime

def run_multi_asset_test():
    """Run backtests on multiple assets."""
    
    assets = [
        {"symbol": "ETH-USD", "name": "Ethereum", "period": "2y", "interval": "1h"},
        {"symbol": "SOL-USD", "name": "Solana", "period": "2y", "interval": "1h"},
    ]
    
    results_summary = []
    
    for asset in assets:
        print(f"\n{'='*60}")
        print(f"Testing {asset['name']} ({asset['symbol']})")
        print('='*60)
        
        try:
            results = run_comprehensive_backtest(
                symbol=asset['symbol'],
                period=asset['period'],
                interval=asset['interval'],
                initial_capital=10000.0,
                transaction_cost=0.001,
                strategy_params={
                    'ema_period': 20,
                    'irb_threshold': 0.45,
                    'risk_per_trade': 0.02,
                    'risk_reward_ratio': 1.5,
                    'max_irb_bars': 20,
                    'use_atr_filter': True,
                    'atr_multiplier': 2.0,
                    'atr_period': 14
                }
            )
            
            print_results(results)
            
            # Save summary
            stats = results['trade_stats']
            results_summary.append({
                'Asset': asset['name'],
                'Symbol': asset['symbol'],
                'Total Return': f"{results['total_return']*100:.2f}%",
                'Sharpe': f"{results['sharpe_ratio']:.3f}",
                'Max DD': f"{results['max_drawdown']*100:.2f}%",
                'Win Rate': f"{stats['win_rate']*100:.1f}%" if stats else "N/A",
                'Trades': stats['total_trades'] if stats else 0,
                'Profit Factor': f"{stats['profit_factor']:.2f}" if stats else "N/A"
            })
            
            # Save visualization
            output_dir = f"/Users/siewbrayden/.openclaw/agents/atlas/workspace/alpha-hunter/strategies/hoffman-irb/data"
            generate_visualizations(results, output_dir)
            
        except Exception as e:
            print(f"Error testing {asset['symbol']}: {e}")
            results_summary.append({
                'Asset': asset['name'],
                'Symbol': asset['symbol'],
                'Total Return': 'ERROR',
                'Sharpe': 'ERROR',
                'Max DD': 'ERROR',
                'Win Rate': 'ERROR',
                'Trades': 0,
                'Profit Factor': 'ERROR'
            })
    
    # Print summary table
    print("\n" + "="*80)
    print("MULTI-ASSET SUMMARY")
    print("="*80)
    
    summary_df = pd.DataFrame(results_summary)
    print(summary_df.to_string(index=False))
    
    # Save summary
    summary_df.to_csv(f"/Users/siewbrayden/.openclaw/agents/atlas/workspace/alpha-hunter/strategies/hoffman-irb/data/multi_asset_summary.csv", index=False)
    print(f"\nSaved: multi_asset_summary.csv")


def run_optimization_test():
    """Test different parameter combinations."""
    
    print("\n" + "="*80)
    print("PARAMETER OPTIMIZATION TEST")
    print("="*80)
    
    param_sets = [
        {"name": "Conservative", "risk_reward_ratio": 2.0, "ema_period": 30},
        {"name": "Aggressive", "risk_reward_ratio": 1.2, "ema_period": 10},
        {"name": "Balanced", "risk_reward_ratio": 1.5, "ema_period": 20},  # Original
    ]
    
    opt_results = []
    
    for params in param_sets:
        print(f"\n--- Testing: {params['name']} ---")
        
        strategy_params = {
            'ema_period': params['ema_period'],
            'irb_threshold': 0.45,
            'risk_per_trade': 0.02,
            'risk_reward_ratio': params['risk_reward_ratio'],
            'max_irb_bars': 20,
            'use_atr_filter': True,
            'atr_multiplier': 2.0,
            'atr_period': 14
        }
        
        try:
            results = run_comprehensive_backtest(
                symbol="BTC-USD",
                period="2y",
                interval="1h",
                initial_capital=10000.0,
                transaction_cost=0.001,
                strategy_params=strategy_params
            )
            
            stats = results['trade_stats']
            opt_results.append({
                'Configuration': params['name'],
                'R:R': params['risk_reward_ratio'],
                'EMA': params['ema_period'],
                'Return': f"{results['total_return']*100:.2f}%",
                'Sharpe': f"{results['sharpe_ratio']:.3f}",
                'Max DD': f"{results['max_drawdown']*100:.2f}%",
                'Win Rate': f"{stats['win_rate']*100:.1f}%" if stats else "N/A",
                'Profit Factor': f"{stats['profit_factor']:.2f}" if stats else "N/A"
            })
            
        except Exception as e:
            print(f"Error: {e}")
    
    # Print optimization results
    print("\n" + "="*80)
    print("OPTIMIZATION RESULTS")
    print("="*80)
    
    opt_df = pd.DataFrame(opt_results)
    print(opt_df.to_string(index=False))
    
    opt_df.to_csv(f"/Users/siewbrayden/.openclaw/agents/atlas/workspace/alpha-hunter/strategies/hoffman-irb/data/optimization_results.csv", index=False)
    print(f"\nSaved: optimization_results.csv")


if __name__ == "__main__":
    print("ATLAS ALPHA HUNTER - Multi-Asset Validation")
    print("="*80)
    
    # Run multi-asset tests
    run_multi_asset_test()
    
    # Run optimization tests
    run_optimization_test()
    
    print("\n" + "="*80)
    print("✅ All additional tests complete!")
    print("="*80)
