"""
Cross-Chain MEV Arbitrage - Backtest Engine
Event-driven backtesting with realistic cost modeling.
"""

import sys
sys.path.insert(0, str(__file__).rsplit('/backtest/', 1)[0])

from typing import Dict, List, Optional, Tuple
import numpy as np
import logging
from datetime import datetime, timedelta
from collections import deque
import random

logger = logging.getLogger(__name__)


class SyntheticSpreadGenerator:
    """
    Generates realistic synthetic cross-chain spread data.
    
    Models:
    - Mean-reverting spreads (Ornstein-Uhlenbeck)
    - Jump events (news, liquidations, depegs)
    - Diurnal patterns
    - Cross-chain correlation
    """
    
    def __init__(
        self,
        pairs: List[str],
        chain_pairs: List[Tuple[str, str]],
        spread_vol: float = 0.001,
        spread_mean: float = 0.0002,
        jump_prob: float = 0.02,
        jump_mean: float = 0.003,
    ):
        self.pairs = pairs
        self.chain_pairs = chain_pairs
        self.spread_vol = spread_vol
        self.spread_mean = spread_mean
        self.jump_prob = jump_prob
        self.jump_mean = jump_mean
        
        # State for OU process
        self._spread_state: Dict[str, float] = {p: spread_mean for p in pairs}
        self._theta = 0.1  # Mean reversion speed
        self._mu = spread_mean
        
    def step(self, dt: float = 1/86400) -> List[Dict]:
        """
        Generate spread values for one time step.
        
        Returns list of spread dicts for all pair/chain combinations.
        """
        results = []
        
        for pair in self.pairs:
            # Ornstein-Uhlenbeck process
            state = self._spread_state[pair]
            
            # Mean reversion
            dW = random.gauss(0, 1) * self.spread_vol
            drift = self._theta * (self._mu - state) * dt
            diffusion = dW
            
            new_state = state + drift + diffusion
            
            # Jump event
            if random.random() < self.jump_prob:
                jump = random.gauss(self.jump_mean, self.jump_mean / 2)
                new_state += jump
            
            # Bounds
            new_state = max(0.0001, min(0.02, new_state))
            self._spread_state[pair] = new_state
            
            # Generate for each chain pair
            for chain_a, chain_b in self.chain_pairs:
                spread_bps = new_state * 10000
                
                # Add small noise per chain pair
                noise = random.gauss(0, 0.5)
                spread_bps += noise
                
                results.append({
                    'timestamp': datetime.now(),
                    'pair': pair,
                    'chain_a': chain_a,
                    'chain_b': chain_b,
                    'spread_bps': spread_bps,
                    'spread_state': new_state,
                })
        
        return results


class BacktestEngine:
    """
    Event-driven backtest engine for cross-chain MEV arbitrage.
    
    Features:
    - Realistic cost modeling (gas, slippage, fees, bridge fees)
    - Position tracking with PnL
    - Risk management simulation
    - Multi-scenario testing
    """
    
    def __init__(
        self,
        config: Dict,
        initial_capital: float = 100_000,
    ):
        self.config = config
        self.initial_capital = initial_capital
        
        # Trading parameters
        arb_config = config.get('trading', {}).get('arbitrage', {})
        self.min_spread_bps = arb_config.get('min_spread_bps', 15)
        self.zscore_threshold = arb_config.get('zscore_entry_threshold', 2.0)
        
        # Cost parameters
        backtest_config = config.get('backtest', {})
        self.maker_fee_bps = backtest_config.get('maker_fee_bps', 3.0)
        self.taker_fee_bps = backtest_config.get('taker_fee_bps', 5.0)
        self.bridge_fee_bps = backtest_config.get('bridge_fee_bps', 8.0)
        self.slippage_bps = backtest_config.get('slippage_bps', 5.0)
        
        # State
        self._portfolio = initial_capital
        self._positions: List[Dict] = []
        self._trades: List[Dict] = []
        self._portfolio_history: List[float] = [initial_capital]
        self._spread_history: Dict[str, deque] = {}
        self._cooldowns: Dict[str, datetime] = {}
        
        # Metrics
        self._total_trades = 0
        self._successful_trades = 0
        self._failed_trades = 0
        
    def reset(self) -> None:
        """Reset backtest state"""
        self._portfolio = self.initial_capital
        self._positions = []
        self._trades = []
        self._portfolio_history = [self.initial_capital]
        self._spread_history = {}
        self._cooldowns = {}
        self._total_trades = 0
        self._successful_trades = 0
        self._failed_trades = 0
    
    def process_spreads(
        self,
        spreads: List[Dict],
        timestamp: datetime,
    ) -> List[Dict]:
        """Process a batch of spread observations and generate trades"""
        new_trades = []
        
        for spread in spreads:
            pair = spread['pair']
            chain_a = spread['chain_a']
            chain_b = spread['chain_b']
            spread_bps = spread['spread_bps']
            
            key = f"{pair}_{chain_a}_{chain_b}"
            
            # Record spread history
            if key not in self._spread_history:
                self._spread_history[key] = deque(maxlen=500)
            self._spread_history[key].append(spread_bps)
            
            # Check cooldown
            if key in self._cooldowns:
                if (timestamp - self._cooldowns[key]).total_seconds() < 60:
                    continue
            
            # Entry check
            if spread_bps < self.min_spread_bps:
                continue
            
            # Z-score check
            zscore = self._calculate_zscore(key, spread_bps)
            if abs(zscore) < self.zscore_threshold:
                continue
            
            # Position sizing
            kelly_fraction = 0.25
            spread_edge = spread_bps - 30  # Subtract ~30bps costs
            if spread_edge <= 0:
                continue
            
            position_size = self._portfolio * kelly_fraction * (spread_edge / 10000)
            position_size = min(position_size, self._portfolio * 0.15)
            position_size = max(position_size, 5000)
            
            # Calculate PnL
            gross_pnl = position_size * (spread_bps / 10000)
            costs = (
                position_size * (self.maker_fee_bps + self.taker_fee_bps) / 10000 +
                position_size * self.bridge_fee_bps / 10000 +
                position_size * self.slippage_bps / 10000 +
                2.0  # $2 gas per leg
            )
            net_pnl = gross_pnl - costs
            
            # Simulate execution (85% success rate for cross-chain)
            success_prob = 0.85
            if random.random() < success_prob:
                self._portfolio += net_pnl
                self._successful_trades += 1
                status = 'success'
            else:
                # Partial loss on failure
                failure_loss = position_size * 0.001
                self._portfolio -= failure_loss
                net_pnl = -failure_loss
                self._failed_trades += 1
                status = 'failed'
            
            # Set cooldown
            self._cooldowns[key] = timestamp
            
            # Record trade
            trade = {
                'timestamp': timestamp,
                'pair': pair,
                'chain_a': chain_a,
                'chain_b': chain_b,
                'spread_bps': spread_bps,
                'zscore': zscore,
                'size_usd': position_size,
                'gross_pnl': gross_pnl,
                'costs': costs,
                'net_pnl': net_pnl,
                'status': status,
                'portfolio': self._portfolio,
            }
            self._trades.append(trade)
            new_trades.append(trade)
            self._total_trades += 1
            self._portfolio_history.append(self._portfolio)
        
        return new_trades
    
    def _calculate_zscore(self, key: str, spread_bps: float) -> float:
        """Calculate z-score for a spread observation"""
        if key not in self._spread_history or len(self._spread_history[key]) < 20:
            return 0.0
        
        history = list(self._spread_history[key])
        mean = np.mean(history)
        std = np.std(history)
        
        if std == 0:
            return 0.0
        return (spread_bps - mean) / std
    
    def get_metrics(self) -> Dict:
        """Calculate backtest performance metrics"""
        if not self._trades:
            return {
                'total_return': 0,
                'sharpe': 0,
                'sortino': 0,
                'max_drawdown': 0,
                'win_rate': 0,
                'total_trades': 0,
            }
        
        pnls = [t['net_pnl'] for t in self._trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        # Returns
        total_return = (self._portfolio - self.initial_capital) / self.initial_capital
        
        # Daily returns from portfolio history
        if len(self._portfolio_history) > 1:
            values = np.array(self._portfolio_history)
            daily_returns = np.diff(values) / values[:-1]
            daily_returns = daily_returns[np.isfinite(daily_returns)]
            
            if len(daily_returns) > 0:
                mean_ret = np.mean(daily_returns)
                std_ret = np.std(daily_returns)
                sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0
                
                downside = daily_returns[daily_returns < 0]
                sortino = (mean_ret / np.std(downside) * np.sqrt(252)) if len(downside) > 0 and np.std(downside) > 0 else 0
            else:
                sharpe = sortino = 0
        else:
            sharpe = sortino = 0
        
        # Max drawdown
        values = np.array(self._portfolio_history)
        peak = np.maximum.accumulate(values)
        drawdowns = (peak - values) / peak
        max_dd = np.max(drawdowns) if len(drawdowns) > 0 else 0
        
        return {
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'final_value': self._portfolio,
            'sharpe': sharpe,
            'sortino': sortino,
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd * 100,
            'win_rate': len(wins) / len(pnls) if pnls else 0,
            'total_trades': self._total_trades,
            'successful_trades': self._successful_trades,
            'failed_trades': self._failed_trades,
            'avg_pnl': np.mean(pnls) if pnls else 0,
            'total_pnl': sum(pnls),
            'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) < 0 else float('inf'),
            'avg_winner': np.mean(wins) if wins else 0,
            'avg_loser': np.mean(losses) if losses else 0,
        }
    
    def get_trades(self) -> List[Dict]:
        return self._trades
    
    def get_portfolio_history(self) -> List[float]:
        return self._portfolio_history


async def run_full_backtest(
    config: Dict,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000,
    verbose: bool = True,
) -> Dict:
    """
    Run a full backtest simulation.
    
    Args:
        config: Strategy configuration dict
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        initial_capital: Starting capital USD
        verbose: Print results
        
    Returns:
        Dict with metrics, trades, and portfolio history
    """
    from datetime import datetime as dt
    
    start_dt = dt.strptime(start_date, "%Y-%m-%d")
    end_dt = dt.strptime(end_date, "%Y-%m-%d")
    days = (end_dt - start_dt).days
    
    # Trading pairs
    pairs = ['WETH/USDC', 'WBTC/USDC']
    chain_pairs = [
        ('ethereum', 'arbitrum'),
        ('ethereum', 'optimism'),
        ('arbitrum', 'base'),
    ]
    
    # Initialize
    engine = BacktestEngine(config, initial_capital)
    spread_gen = SyntheticSpreadGenerator(pairs, chain_pairs)
    
    logger.info(f"Running backtest: {days} days ({start_date} to {end_date})")
    
    # Run simulation
    steps_per_day = 24  # Hourly checks
    total_steps = days * steps_per_day
    
    for step in range(total_steps):
        # Generate spreads
        spreads = spread_gen.step(dt=1.0)
        
        # Process
        timestamp = start_dt + timedelta(hours=step / steps_per_day * 24)
        engine.process_spreads(spreads, timestamp)
        
        # Progress
        if step % (total_steps // 10) == 0:
            pct = step / total_steps * 100
            logger.info(f"Backtest progress: {pct:.0f}% | Portfolio: ${engine._portfolio:,.0f}")
    
    # Calculate final metrics
    metrics = engine.get_metrics()
    
    if verbose:
        print("\n" + "="*60)
        print("CROSS-CHAIN MEV ARBITRAGE BACKTEST")
        print("="*60)
        print(f"Period:             {start_date} to {end_date} ({days} days)")
        print(f"Initial Capital:    ${initial_capital:,.0f}")
        print(f"Final Value:        ${metrics['final_value']:,.2f}")
        print(f"Total Return:       {metrics['total_return_pct']:.2f}%")
        print(f"Sharpe Ratio:       {metrics['sharpe']:.2f}")
        print(f"Sortino Ratio:      {metrics['sortino']:.2f}")
        print(f"Max Drawdown:        {metrics['max_drawdown_pct']:.2f}%")
        print("-"*60)
        print(f"Total Trades:       {metrics['total_trades']}")
        print(f"Successful:         {metrics['successful_trades']}")
        print(f"Failed:             {metrics['failed_trades']}")
        print(f"Win Rate:           {metrics['win_rate']:.1%}")
        print(f"Profit Factor:      {metrics['profit_factor']:.2f}")
        print(f"Avg PnL / Trade:   ${metrics['avg_pnl']:,.2f}")
        print("="*60 + "\n")
    
    return {
        'metrics': metrics,
        'trades': engine.get_trades(),
        'portfolio_history': engine.get_portfolio_history(),
        'config': {
            'start_date': start_date,
            'end_date': end_date,
            'days': days,
            'initial_capital': initial_capital,
        }
    }
