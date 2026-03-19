"""
OBI (Order Book Imbalance) Microstructure Strategy

Strategy: Exploit order book imbalances for short-term directional edge.
When bid/ask imbalance exceeds thresholds, take directional positions
with tight risk management.

Core Concept:
- Large bid imbalance (bids >> asks) = buying pressure = go long
- Large ask imbalance (asks >> bids) = selling pressure = go short

Entry Logic:
- Calculate OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
- Long when OBI > +0.3 (strong buying pressure)
- Short when OBI < -0.3 (strong selling pressure)
- Require confirmation: 2 consecutive OBI signals

Exit Logic:
- OBI reverts to neutral (-0.1 to +0.1)
- Time-based exit: Max 5 minutes
- Stop loss: 0.3% (tight, scalp-style)

Timeframe: Tick/L2 data, executed on 1-minute candles
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json


@dataclass
class OBISignal:
    """OBI trading signal."""
    timestamp: datetime
    direction: str  # 'long' or 'short'
    obi_value: float
    bid_volume: float
    ask_volume: float
    entry_price: float
    confidence: float  # 0-1 based on OBI magnitude


@dataclass
class OBITrade:
    """Completed trade record."""
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    exit_price: float
    size_usd: float
    pnl: float
    pnl_pct: float
    duration_minutes: float
    exit_reason: str


class OBIMicrostructureStrategy:
    """
    Order Book Imbalance microstructure strategy.
    
    Exploits short-term order flow imbalances for scalping
    opportunities with tight risk management.
    """
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        obi_threshold: float = 0.3,
        neutral_threshold: float = 0.1,
        max_hold_minutes: float = 5.0,
        stop_loss_pct: float = 0.003,
        take_profit_pct: float = 0.005,
        commission_rate: float = 0.0005,
        position_size_pct: float = 0.2
    ):
        self.initial_capital = initial_capital
        self.obi_threshold = obi_threshold
        self.neutral_threshold = neutral_threshold
        self.max_hold_minutes = max_hold_minutes
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.commission_rate = commission_rate
        self.position_size_pct = position_size_pct
        
        self.trades: List[OBITrade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_position: Optional[OBITrade] = None
        self.signal_history: List[OBISignal] = []
        
    def calculate_obi(self, bid_volume: float, ask_volume: float) -> float:
        """
        Calculate Order Book Imbalance.
        
        OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
        Range: -1 (all asks) to +1 (all bids)
        """
        total = bid_volume + ask_volume
        if total == 0:
            return 0.0
        return (bid_volume - ask_volume) / total
    
    def generate_signal(
        self,
        timestamp: datetime,
        bid_volume: float,
        ask_volume: float,
        price: float
    ) -> Optional[OBISignal]:
        """Generate trading signal from OBI data."""
        obi = self.calculate_obi(bid_volume, ask_volume)
        
        # Check for long signal
        if obi > self.obi_threshold:
            confidence = min((obi - self.obi_threshold) / (1 - self.obi_threshold), 1.0)
            return OBISignal(
                timestamp=timestamp,
                direction='long',
                obi_value=obi,
                bid_volume=bid_volume,
                ask_volume=ask_volume,
                entry_price=price,
                confidence=confidence
            )
        
        # Check for short signal
        elif obi < -self.obi_threshold:
            confidence = min((abs(obi) - self.obi_threshold) / (1 - self.obi_threshold), 1.0)
            return OBISignal(
                timestamp=timestamp,
                direction='short',
                obi_value=obi,
                bid_volume=bid_volume,
                ask_volume=ask_volume,
                entry_price=price,
                confidence=confidence
            )
        
        return None
    
    def confirm_signal(self, signal: OBISignal) -> bool:
        """
        Require confirmation: 2 consecutive signals in same direction.
        
        This reduces false positives from temporary order book anomalies.
        """
        if len(self.signal_history) < 1:
            return False
        
        last_signal = self.signal_history[-1]
        
        # Confirm if same direction within 2 minutes
        time_diff = (signal.timestamp - last_signal.timestamp).total_seconds() / 60
        if time_diff <= 2 and last_signal.direction == signal.direction:
            return True
        
        return False
    
    def run_backtest(
        self,
        timestamps: List[datetime],
        bid_volumes: List[float],
        ask_volumes: List[float],
        prices: List[float]
    ) -> Dict:
        """
        Run backtest on historical order book data.
        
        Args:
            timestamps: List of timestamps
            bid_volumes: List of bid volumes at L2 top
            ask_volumes: List of ask volumes at L2 top
            prices: List of mid prices
        """
        capital = self.initial_capital
        position = None
        
        for i in range(len(timestamps)):
            ts = timestamps[i]
            bid_vol = bid_volumes[i]
            ask_vol = ask_volumes[i]
            price = prices[i]
            
            # Generate signal
            signal = self.generate_signal(ts, bid_vol, ask_vol, price)
            
            if signal:
                self.signal_history.append(signal)
            
            # Check for position exit
            if position is not None:
                # Calculate unrealized PnL
                if position.direction == 'long':
                    unrealized_pct = (price - position.entry_price) / position.entry_price
                else:
                    unrealized_pct = (position.entry_price - price) / position.entry_price
                
                # Exit conditions
                exit_triggered = False
                exit_reason = ""
                
                # Time-based exit
                hold_time = (ts - position.entry_time).total_seconds() / 60
                if hold_time >= self.max_hold_minutes:
                    exit_triggered = True
                    exit_reason = "time_exit"
                
                # Stop loss
                elif unrealized_pct <= -self.stop_loss_pct:
                    exit_triggered = True
                    exit_reason = "stop_loss"
                
                # Take profit
                elif unrealized_pct >= self.take_profit_pct:
                    exit_triggered = True
                    exit_reason = "take_profit"
                
                # OBI reversion (neutral)
                elif signal is None:  # No signal means OBI is neutral
                    current_obi = self.calculate_obi(bid_vol, ask_vol)
                    if abs(current_obi) < self.neutral_threshold:
                        exit_triggered = True
                        exit_reason = "obi_reversion"
                
                if exit_triggered:
                    # Close position
                    position.exit_time = ts
                    position.exit_price = price
                    position.pnl_pct = unrealized_pct * 100
                    position.pnl = position.size_usd * unrealized_pct
                    position.exit_reason = exit_reason
                    position.duration_minutes = hold_time
                    
                    # Apply costs
                    commission = position.size_usd * self.commission_rate * 2
                    position.pnl -= commission
                    
                    capital += position.pnl
                    self.trades.append(position)
                    position = None
            
            # Check for position entry
            if position is None and signal is not None and len(self.signal_history) >= 2:
                if self.confirm_signal(signal):
                    position_size = capital * self.position_size_pct
                    
                    position = OBITrade(
                        entry_time=ts,
                        exit_time=ts,  # Will be updated on exit
                        direction=signal.direction,
                        entry_price=price,
                        exit_price=price,
                        size_usd=position_size,
                        pnl=0.0,
                        pnl_pct=0.0,
                        duration_minutes=0.0,
                        exit_reason=""
                    )
                    
                    # Deduct entry commission
                    capital -= position_size * self.commission_rate
            
            # Record equity
            current_equity = capital
            if position is not None:
                if position.direction == 'long':
                    unrealized = position.size_usd * (price - position.entry_price) / position.entry_price
                else:
                    unrealized = position.size_usd * (position.entry_price - price) / position.entry_price
                current_equity += unrealized
            
            self.equity_curve.append((ts, current_equity))
        
        # Close any open position at end
        if position is not None:
            final_price = prices[-1]
            position.exit_time = timestamps[-1]
            position.exit_price = final_price
            
            if position.direction == 'long':
                position.pnl = position.size_usd * (final_price - position.entry_price) / position.entry_price
            else:
                position.pnl = position.size_usd * (position.entry_price - final_price) / position.entry_price
            
            position.pnl_pct = (position.pnl / position.size_usd) * 100
            position.exit_reason = "end_of_data"
            position.duration_minutes = (timestamps[-1] - position.entry_time).total_seconds() / 60
            
            capital += position.pnl
            self.trades.append(position)
        
        return self.calculate_metrics(capital)
    
    def calculate_metrics(self, final_capital: float) -> Dict:
        """Calculate comprehensive performance metrics."""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'total_return_pct': 0.0,
                'max_drawdown_pct': 0.0,
                'sharpe_ratio': 0.0,
                'avg_trade_duration': 0.0
            }
        
        trades_df = pd.DataFrame([{
            'pnl': t.pnl,
            'pnl_pct': t.pnl_pct,
            'direction': t.direction,
            'duration': t.duration_minutes
        } for t in self.trades])
        
        winning_trades = trades_df[trades_df['pnl'] > 0]
        losing_trades = trades_df[trades_df['pnl'] <= 0]
        
        total_trades = len(self.trades)
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        
        gross_profit = winning_trades['pnl'].sum() if len(winning_trades) > 0 else 0
        gross_loss = abs(losing_trades['pnl'].sum()) if len(losing_trades) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        total_return_pct = ((final_capital - self.initial_capital) / self.initial_capital) * 100
        
        # Max drawdown
        equity_df = pd.DataFrame(self.equity_curve, columns=['timestamp', 'equity'])
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak']
        max_drawdown_pct = abs(equity_df['drawdown'].min()) * 100
        
        # Sharpe (annualized)
        returns = equity_df['equity'].pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(365 * 24 * 60)  # Minute data
        else:
            sharpe_ratio = 0.0
        
        return {
            'total_trades': total_trades,
            'win_rate': win_rate * 100,
            'profit_factor': profit_factor,
            'total_return_pct': total_return_pct,
            'max_drawdown_pct': max_drawdown_pct,
            'sharpe_ratio': sharpe_ratio,
            'avg_trade_return': trades_df['pnl_pct'].mean(),
            'avg_win': winning_trades['pnl_pct'].mean() if len(winning_trades) > 0 else 0,
            'avg_loss': losing_trades['pnl_pct'].mean() if len(losing_trades) > 0 else 0,
            'avg_trade_duration': trades_df['duration'].mean(),
            'final_capital': final_capital,
            'initial_capital': self.initial_capital
        }


def generate_synthetic_obi_data(minutes: int = 10080) -> Tuple[List, List, List, List]:
    """
    Generate synthetic order book data for backtesting.
    Simulates OBI patterns with mean-reverting behavior.
    """
    np.random.seed(42)
    
    timestamps = pd.date_range(end=pd.Timestamp.now(), periods=minutes, freq='min')
    
    # Generate base volumes
    base_bid = 100000
    base_ask = 100000
    
    bid_volumes = []
    ask_volumes = []
    prices = []
    
    price = 100.0
    
    for i in range(minutes):
        # Create OBI mean reversion pattern
        obi_bias = np.sin(i / 100) * 0.5 + np.random.normal(0, 0.2)
        
        bid_vol = base_bid * (1 + obi_bias + np.random.uniform(-0.3, 0.3))
        ask_vol = base_ask * (1 - obi_bias + np.random.uniform(-0.3, 0.3))
        
        bid_volumes.append(max(bid_vol, 1000))
        ask_volumes.append(max(ask_vol, 1000))
        
        # Price follows OBI direction with lag
        price_change = np.random.normal(0, 0.0005)
        if i > 5:
            obi_lag = (bid_volumes[i-5] - ask_volumes[i-5]) / (bid_volumes[i-5] + ask_volumes[i-5])
            price_change += obi_lag * 0.0003  # Small predictive edge
        
        price *= (1 + price_change)
        prices.append(price)
    
    return timestamps.tolist(), bid_volumes, ask_volumes, prices


def main():
    print("=" * 70)
    print("OBI MICROSTRUCTURE STRATEGY BACKTEST")
    print("=" * 70)
    print()
    print("Strategy: Order Book Imbalance Scalping")
    print("Core Edge: Exploiting short-term order flow imbalances")
    print()
    
    # Generate data
    print("Generating synthetic order book data (1 week, 1-minute resolution)...")
    timestamps, bid_vols, ask_vols, prices = generate_synthetic_obi_data(minutes=10080)
    print(f"Data points: {len(timestamps)}")
    print(f"Price range: ${min(prices):.2f} - ${max(prices):.2f}")
    print()
    
    # Run backtest
    print("Running backtest...")
    strategy = OBIMicrostructureStrategy()
    results = strategy.run_backtest(timestamps, bid_vols, ask_vols, prices)
    
    # Display results
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    print(f"\nInitial Capital:       ${results['initial_capital']:,.2f}")
    print(f"Final Capital:         ${results['final_capital']:,.2f}")
    print(f"Total Return:          {results['total_return_pct']:+.2f}%")
    print()
    print(f"Total Trades:          {results['total_trades']}")
    print(f"Win Rate:              {results['win_rate']:.1f}%")
    print(f"Profit Factor:         {results['profit_factor']:.2f}")
    print()
    print(f"Avg Trade Return:      {results['avg_trade_return']:+.2f}%")
    print(f"Avg Win:               {results['avg_win']:+.2f}%")
    print(f"Avg Loss:              {results['avg_loss']:+.2f}%")
    print(f"Avg Trade Duration:    {results['avg_trade_duration']:.1f} min")
    print()
    print(f"Max Drawdown:          {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:          {results['sharpe_ratio']:.2f}")
    print()
    
    # Save results
    with open('/Users/siewbrayden/.openclaw/workspace/alpha-strategies/strategies/obi_microstructure_strategy/results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print("Results saved to results.json")
    
    return results


if __name__ == "__main__":
    main()
