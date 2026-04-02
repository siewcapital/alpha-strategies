"""
Token Unlock Arbitrage - Backtest Engine
========================================
Event-driven backtest using synthetic unlock data.

Research-based synthetic data assumptions:
- Unlock events follow known schedules (CoinGecko/TokenUnlocks data)
- 1% unlock → 0.6% total predictable price impact (0.3% before + 0.3% after)
- Market is semi-efficient: 60% of move happens in anticipation
- Remaining 40% on days 3-4 post-unlock (selling pressure)
- Noise: Daily vol 3%, mean-reverting around unlock events
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple
import yaml
import json
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dataclasses import asdict

from strategy import TokenUnlockStrategy, UnlockEvent, Trade


class SyntheticDataGenerator:
    """Generate synthetic price data with realistic unlock impacts."""
    
    def __init__(self, seed: int = 42):
        np.random.seed(seed)
        
    def generate_unlock_schedule(
        self,
        tokens: List[str],
        start_date: datetime,
        end_date: datetime,
        avg_unlocks_per_month: int = 5
    ) -> List[Dict]:
        """Generate synthetic unlock schedule."""
        unlocks = []
        current_date = start_date
        
        # Generate unlock events
        while current_date < end_date:
            n_unlocks = np.random.poisson(avg_unlocks_per_month / 30)
            
            for _ in range(n_unlocks):
                token = np.random.choice(tokens)
                
                # Unlock size varies: most are small, some are large
                # Power law distribution
                unlock_pct = np.random.exponential(0.8) + 0.2
                unlock_pct = min(unlock_pct, 15.0)  # Cap at 15%
                
                # Circulating supply (millions to billions)
                circ_supply = np.random.uniform(10, 1000) * 1e6
                unlock_amount = circ_supply * (unlock_pct / 100)
                
                unlock_date = current_date + timedelta(days=np.random.randint(0, 30))
                
                if unlock_date < end_date:
                    unlocks.append({
                        'token': token,
                        'unlock_date': unlock_date.isoformat(),
                        'unlock_amount': unlock_amount,
                        'circulating_supply': circ_supply,
                        'unlock_pct': unlock_pct
                    })
            
            current_date += timedelta(days=1)
        
        return unlocks
    
    def generate_price_paths(
        self,
        tokens: List[str],
        start_date: datetime,
        end_date: datetime,
        unlocks: List[Dict],
        initial_prices: Dict[str, float]
    ) -> pd.DataFrame:
        """
        Generate synthetic price paths with unlock impact.
        
        Model:
        - Base: GBM with 50% annual vol, 20% drift
        - Unlock impact: Add deterministic drift around unlock dates
        - 1% unlock → -0.6% total impact (per research)
        """
        dates = pd.date_range(start=start_date, end=end_date, freq='D')
        
        data = {}
        
        for token in tokens:
            price = initial_prices.get(token, 1.0)
            prices = [price]
            
            # Find unlocks for this token
            token_unlocks = [
                u for u in unlocks 
                if u['token'] == token
            ]
            
            for i in range(1, len(dates)):
                current_date = dates[i]
                
                # Base GBM
                daily_return = np.random.normal(0.0005, 0.03)  # 20% annual drift, 50% vol
                
                # Add unlock impact
                for unlock in token_unlocks:
                    unlock_date = datetime.fromisoformat(unlock['unlock_date'])
                    days_to_unlock = (unlock_date - current_date).days
                    unlock_pct = unlock['unlock_pct']
                    
                    # Impact model based on research:
                    # Days -7 to -2: Anticipation selling (-0.3% per 1% unlock)
                    # Days 0 to 1: Little impact (unlock day itself)
                    # Days 3 to 5: Selling pressure (-0.3% per 1% unlock)
                    
                    if unlock_pct >= 1.0:  # Only significant unlocks
                        if -7 <= days_to_unlock <= -2:
                            # Anticipation phase
                            impact = -0.0005 * unlock_pct / np.sqrt(max(1, abs(days_to_unlock)))
                            daily_return += impact
                        
                        elif 3 <= days_to_unlock <= 5:
                            # Post-unlock selling
                            impact = -0.001 * unlock_pct / np.sqrt(days_to_unlock - 2)
                            daily_return += impact
                        
                        elif 0 <= days_to_unlock <= 1:
                            # Unlock day - sometimes bounce (short covering)
                            if np.random.random() < 0.3:
                                daily_return += 0.005
                
                price = price * (1 + daily_return)
                price = max(price, 0.001)  # Price floor
                prices.append(price)
            
            data[token] = prices
        
        df = pd.DataFrame(data, index=dates)
        return df


class BacktestEngine:
    """Event-driven backtest engine for token unlock strategy."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.strategy: Optional[TokenUnlockStrategy] = None
        self.price_data: Optional[pd.DataFrame] = None
        self.results: List[Dict] = []
        
    def _load_config(self, config_path: Optional[str]) -> dict:
        """Load backtest configuration."""
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        
        return {
            'start_date': '2022-01-01',
            'end_date': '2026-01-01',
            'tokens': ['SOL', 'AVAX', 'UNI', 'ARB', 'OP', 'SUI', 'APT', 'DYDX', 'AXS', 'IMX'],
            'initial_prices': {
                'SOL': 100.0, 'AVAX': 50.0, 'UNI': 8.0, 'ARB': 1.5, 'OP': 2.0,
                'SUI': 1.0, 'APT': 8.0, 'DYDX': 2.5, 'AXS': 10.0, 'IMX': 1.5
            },
            'strategy_config': 'config/params.yaml'
        }
    
    def run_backtest(self) -> Dict:
        """Run full backtest."""
        print("="*60)
        print("TOKEN UNLOCK ARBITRAGE BACKTEST")
        print("="*60)
        
        # Generate synthetic data
        print("\n[1/4] Generating synthetic unlock schedule...")
        generator = SyntheticDataGenerator(seed=42)
        
        start_date = datetime.fromisoformat(self.config['start_date'])
        end_date = datetime.fromisoformat(self.config['end_date'])
        tokens = self.config['tokens']
        
        unlocks = generator.generate_unlock_schedule(
            tokens, start_date, end_date
        )
        
        significant = [u for u in unlocks if u['unlock_pct'] >= 1.0]
        print(f"  Total unlocks: {len(unlocks)}")
        print(f"  Significant (≥1%): {len(significant)}")
        print(f"  Date range: {start_date.date()} to {end_date.date()}")
        
        print("\n[2/4] Generating synthetic price paths...")
        self.price_data = generator.generate_price_paths(
            tokens, start_date, end_date, unlocks, self.config['initial_prices']
        )
        print(f"  Price data: {len(self.price_data)} days x {len(tokens)} tokens")
        
        # Initialize strategy
        print("\n[3/4] Initializing strategy...")
        self.strategy = TokenUnlockStrategy(self.config.get('strategy_config'))
        self.strategy.load_unlock_schedule(unlocks)
        
        # Run simulation
        print("\n[4/4] Running simulation...")
        print("-"*60)
        
        for date in self.price_data.index:
            prices = self.price_data.loc[date].to_dict()
            
            # Check for exits first
            self.strategy.check_exits(date, prices)
            
            # Check for entries
            self.strategy.generate_signals(date, prices)
        
        # Close any remaining positions at last price
        last_date = self.price_data.index[-1]
        last_prices = self.price_data.iloc[-1].to_dict()
        for token in list(self.strategy.positions.keys()):
            trade = self.strategy.positions[token]
            if trade.status.value == 'open':
                trade.close(last_prices[token], last_date)
                self.strategy.trade_history.append(trade)
                del self.strategy.positions[token]
        
        # Calculate metrics
        metrics = self.strategy.get_metrics()
        self.strategy.print_summary()
        
        return metrics
    
    def save_results(self, output_dir: str = "results"):
        """Save backtest results to files."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        # Save trade history
        trades_data = []
        for trade in self.strategy.trade_history:
            trades_data.append({
                'token': trade.token,
                'entry_date': trade.entry_date.isoformat() if trade.entry_date else None,
                'exit_date': trade.exit_date.isoformat() if trade.exit_date else None,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'position_size': trade.position_size,
                'signal_type': trade.signal_type.value,
                'pnl': trade.pnl,
                'pnl_pct': trade.pnl_pct,
            })
        
        with open(out_path / 'trades.json', 'w') as f:
            json.dump(trades_data, f, indent=2)
        
        # Save metrics
        metrics = self.strategy.get_metrics()
        with open(out_path / 'metrics.json', 'w') as f:
            json.dump(metrics, f, indent=2)
        
        # Save equity curve
        equity = [self.strategy.params['initial_capital']]
        for trade in sorted(self.strategy.trade_history, key=lambda x: x.exit_date or x.entry_date):
            if trade.pnl is not None:
                equity.append(equity[-1] + trade.pnl)
        
        equity_df = pd.DataFrame({
            'equity': equity
        })
        equity_df.to_csv(out_path / 'equity_curve.csv')
        
        print(f"\nResults saved to {output_dir}/")


if __name__ == "__main__":
    engine = BacktestEngine()
    metrics = engine.run_backtest()
    engine.save_results()
