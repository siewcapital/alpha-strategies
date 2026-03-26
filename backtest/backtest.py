"""
Backtest Engine for Polymarket 5-Minute BTC Signal Strategy

Generates synthetic market data and runs comprehensive backtests
to validate strategy performance across multiple market regimes.

Key findings from paper:
- v2 engine: 522× paper returns → -49.5% live (gap from slippage/fees)
- v3 engine: 7× better capital preservation
- Win rates: 25-27% (below 53% breakeven)
- Random walk at 5-min horizons confirmed
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class MarketRegime:
    """Market regime parameters."""
    name: str
    volatility: float  # Daily vol as fraction
    drift: float  # Mean return per 5-min bar
    trend_strength: float  # 0-1, how strong the trend is
    noise_ratio: float  # 0-1, how much random walk


class DataLoader:
    """
    Generates synthetic Polymarket and BTC data for backtesting.

    Uses realistic models based on observed market microstructure:
    1. BTC price follows geometric Brownian motion with drift
    2. Token price lags BTC with configurable delay
    3. Fee structure from Polymarket: ~1.56% at $0.50
    4. Slippage: 2-4 cents per token
    """

    def __init__(
        self,
        initial_btc_price: float = 100000.0,
        start_date: datetime = None,
        num_windows: int = 1000,
    ):
        """
        Initialize data loader.

        Args:
            initial_btc_price: Starting BTC price
            start_date: Start datetime
            num_windows: Number of 5-min windows to generate
        """
        self.initial_btc_price = initial_btc_price
        self.start_date = start_date or datetime(2026, 1, 1)
        self.num_windows = num_windows

    def generate_synthetic_data(
        self,
        regime: MarketRegime,
        seed: int = 42,
    ) -> pd.DataFrame:
        """
        Generate synthetic market data for a specific regime.

        Args:
            regime: Market regime parameters
            seed: Random seed for reproducibility

        Returns:
            DataFrame with columns: timestamp, btc_price, btc_open, token_price,
                                   btc_return, outcome
        """
        np.random.seed(seed)

        # Time array (5-min intervals)
        n = self.num_windows
        timestamps = [
            self.start_date + timedelta(seconds=300 * i)
            for i in range(n)
        ]

        # Generate BTC prices using GBM
        dt = 5 * 60  # 5 minutes in seconds
        annualization = 365 * 24 * 3600 / dt

        # Volatility per 5-min bar
        sigma = regime.volatility / np.sqrt(annualization)
        mu = regime.drift / annualization

        # Generate returns (n values for n prices)
        returns = np.random.normal(mu * dt, sigma * np.sqrt(dt), n)

        # Add trend component
        if regime.trend_strength > 0:
            trend_component = np.linspace(
                0,
                regime.trend_strength * sigma * np.sqrt(dt) * regime.trend_strength,
                n
            )
            returns += trend_component

        # Add random walk noise
        if regime.noise_ratio > 0:
            noise = np.random.normal(0, regime.noise_ratio * sigma * np.sqrt(dt), n)
            returns += noise

        # Build price series - use returns[1:] to get n-1 returns for n prices
        btc_prices = [self.initial_btc_price]
        for r in returns[1:]:
            btc_prices.append(btc_prices[-1] * np.exp(r))
        btc_prices = np.array(btc_prices)

        # Generate token prices (lag behind BTC)
        # Model: token_price = 0.5 + sensitivity * log(BTC_t / BTC_{t-1}) + noise
        sensitivity = 5.0  # 5x leverage
        btc_returns = np.diff(btc_prices) / btc_prices[:-1]  # n-1 returns for n prices

        # Use btc_returns[0] for first window outcome
        raw_token = np.zeros(n)
        raw_token[0] = 0.5  # First window neutral
        for i in range(1, n):
            raw_token[i] = 0.5 + sensitivity * btc_returns[i-1]

        # Add lag (token adjusts with delay)
        lag_factor = 0.7  # 70% current, 30% previous
        token_prices = np.zeros(n)
        token_prices[0] = 0.5
        for i in range(1, n):
            ideal = raw_token[i]
            token_prices[i] = lag_factor * ideal + (1 - lag_factor) * token_prices[i-1]

        # Add spread noise (order book friction)
        spread_noise = np.random.uniform(-0.02, 0.02, n)
        token_prices = token_prices + spread_noise
        token_prices = np.clip(token_prices, 0.01, 0.99)

        # Determine outcomes (UP if BTC went up) - n-1 outcomes for n prices
        outcomes = (btc_returns > 0).astype(int)

        # Create DataFrame with aligned lengths
        df = pd.DataFrame({
            'timestamp': timestamps,
            'btc_price': btc_prices,
            'btc_return': np.concatenate([[0], btc_returns]),  # Pad first to n
            'token_price': token_prices,
            'outcome': np.concatenate([[0], outcomes]),  # Pad first to n
        })

        # Window metadata
        df['window_id'] = [
            f"btc-updown-5m-{int(ts.timestamp() // 300 * 300)}"
            for ts in timestamps
        ]
        df['window_open_btc'] = btc_prices  # Same as close since it's 5-min

        return df

    def generate_multi_regime_data(
        self,
        regimes: list[tuple[MarketRegime, int]],
    ) -> pd.DataFrame:
        """
        Generate data across multiple regimes.

        Args:
            regimes: List of (regime, num_windows) tuples

        Returns:
            Combined DataFrame
        """
        dfs = []
        current_price = self.initial_btc_price
        current_time = self.start_date

        for regime, n_windows in regimes:
            loader = DataLoader(
                initial_btc_price=current_price,
                start_date=current_time,
                num_windows=n_windows,
            )
            df = loader.generate_synthetic_data(regime, seed=np.random.randint(0, 10000))
            dfs.append(df)

            current_price = df['btc_price'].iloc[-1]
            current_time = df['timestamp'].iloc[-1] + timedelta(seconds=300)

        return pd.concat(dfs, ignore_index=True)


class Backtester:
    """
    Backtest engine for Polymarket 5-min signal strategy.

    Runs strategy on generated/synthetic data and computes metrics.
    """

    def __init__(
        self,
        initial_balance: float = 1000.0,
        taker_fee: float = 0.0156,  # 1.56% at $0.50
        slippage_cents: float = 0.03,
    ):
        """
        Initialize backtester.

        Args:
            initial_balance: Starting balance
            taker_fee: Fee as fraction (0.0156 = 1.56%)
            slippage_cents: Slippage in cents per token
        """
        self.initial_balance = initial_balance
        self.taker_fee = taker_fee
        self.slippage_cents = slippage_cents

    def run_backtest(
        self,
        data: pd.DataFrame,
        signal_config: dict = None,
        position_config: dict = None,
        risk_config: dict = None,
    ) -> dict:
        """
        Run backtest on data.

        Args:
            data: DataFrame with btc_price, token_price, outcome, etc.
            signal_config: Signal engine config
            position_config: Position sizer config
            risk_config: Risk manager config

        Returns:
            Dict of backtest results
        """
        # Import strategy - handle both package and script import
        try:
            from ..src.strategy import PolymarketSignalStrategy
        except ImportError:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from src.strategy import PolymarketSignalStrategy

        # Initialize strategy
        strategy = PolymarketSignalStrategy(
            starting_balance=self.initial_balance,
            signal_config=signal_config,
            position_config=position_config,
            risk_config=risk_config,
            llm_filter_enabled=False,
            save_trades=False,
        )

        # Run simulation
        equity = [self.initial_balance]
        trade_log = []

        for i, row in data.iterrows():
            # Process market data
            signal, position = strategy.process_market_data(
                btc_price=row['btc_price'],
                token_price=row['token_price'],
                timestamp=row['timestamp'],
            )

            # Execute trade if valid
            if signal and position and position.size > 0:
                window_id = row['window_id']
                trade = strategy.execute_trade(
                    signal=signal,
                    position_size=position,
                    window_id=window_id,
                    timestamp=row['timestamp'],
                )

                # Calculate P&L
                won = bool(row['outcome'])
                if won:
                    # Win: get $1 per token minus fees
                    gross_pnl = position.size * (1 - trade.entry_price)
                else:
                    # Loss: lose token cost
                    gross_pnl = -position.size * trade.entry_price

                # Apply fees and slippage
                fees = position.size * (self.taker_fee + self.slippage_cents / 100)
                net_pnl = gross_pnl - fees

                # Record resolution
                strategy.record_resolution(
                    window_id=window_id,
                    won=won,
                    resolution_price=1.0 if won else 0.0,
                    pnl=net_pnl,
                )

                trade_log.append({
                    'window': window_id,
                    'direction': trade.direction,
                    'entry': trade.entry_price,
                    'size': position.size,
                    'won': won,
                    'pnl': net_pnl,
                    'signal_type': signal.signal_type.value,
                })

            equity.append(strategy.risk_manager.current_balance)

        # Calculate metrics
        final_balance = equity[-1]
        total_return = (final_balance - self.initial_balance) / self.initial_balance

        # Returns series
        returns = np.diff(equity) / equity[:-1]
        returns = returns[~np.isnan(returns)]

        # Sharpe ratio (annualized for 5-min data)
        if len(returns) > 0 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 288)  # 288 5-min periods per day
        else:
            sharpe = 0.0

        # Max drawdown
        peak = equity[0]
        max_dd = 0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd

        # Win rate
        wins = sum(1 for t in trade_log if t['won'])
        losses = len(trade_log) - wins
        win_rate = wins / len(trade_log) if trade_log else 0

        # Profit factor
        gross_wins = sum(t['pnl'] for t in trade_log if t['pnl'] > 0)
        gross_losses = abs(sum(t['pnl'] for t in trade_log if t['pnl'] < 0))
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')

        return {
            'initial_balance': self.initial_balance,
            'final_balance': final_balance,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd * 100,
            'num_trades': len(trade_log),
            'num_wins': wins,
            'num_losses': losses,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': gross_wins / wins if wins > 0 else 0,
            'avg_loss': gross_losses / losses if losses > 0 else 0,
            'equity_curve': equity,
            'trade_log': trade_log,
        }

    def run_regime_analysis(
        self,
        regimes: list[tuple[str, MarketRegime, int]],
        **kwargs,
    ) -> dict:
        """
        Run backtest across multiple market regimes.

        Args:
            regimes: List of (name, regime, num_windows) tuples
            **kwargs: Passed to run_backtest

        Returns:
            Dict mapping regime name to backtest results
        """
        loader = DataLoader(
            initial_btc_price=kwargs.pop('initial_btc_price', 100000.0),
            start_date=kwargs.pop('start_date', datetime(2026, 1, 1)),
        )

        results = {}
        for name, regime, n_windows in regimes:
            logger.info(f"Running backtest for regime: {name}")
            data = loader.generate_synthetic_data(regime)
            results[name] = self.run_backtest(data, **kwargs)

        return results


def generate_standard_regimes() -> list[tuple[str, MarketRegime, int]]:
    """Generate standard test regimes."""
    return [
        ('Bull_Trend', MarketRegime(
            name='Bull_Trend',
            volatility=0.02,  # 2% daily vol
            drift=0.001,  # Positive drift
            trend_strength=0.8,
            noise_ratio=0.3,
        ), 500),

        ('Bear_Trend', MarketRegime(
            name='Bear_Trend',
            volatility=0.025,
            drift=-0.001,
            trend_strength=0.8,
            noise_ratio=0.3,
        ), 500),

        ('Ranging', MarketRegime(
            name='Ranging',
            volatility=0.015,
            drift=0.0,
            trend_strength=0.2,
            noise_ratio=0.8,
        ), 500),

        ('High_Vol', MarketRegime(
            name='High_Vol',
            volatility=0.05,
            drift=0.0,
            trend_strength=0.3,
            noise_ratio=0.9,
        ), 500),

        ('Low_Vol', MarketRegime(
            name='Low_Vol',
            volatility=0.008,
            drift=0.0001,
            trend_strength=0.5,
            noise_ratio=0.5,
        ), 500),
    ]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Run backtest
    backtester = Backtester(initial_balance=1000.0)
    regimes = generate_standard_regimes()

    signal_config = {
        'momentum_weights': {30: 0.20, 60: 0.30, 120: 0.35, 240: 0.15},
        'trend_window_seconds': 600,
        'dislocation_btc_move_min': 0.0005,
    }

    results = backtester.run_regime_analysis(
        regimes=regimes,
        signal_config=signal_config,
    )

    # Print summary
    print("\n" + "="*80)
    print("REGIME ANALYSIS SUMMARY")
    print("="*80)

    for name, result in results.items():
        print(f"\n{name}:")
        print(f"  Return:     {result['total_return_pct']:+.2f}%")
        print(f"  Sharpe:     {result['sharpe_ratio']:.2f}")
        print(f"  Max DD:     {result['max_drawdown_pct']:.2f}%")
        print(f"  Win Rate:   {result['win_rate']:.1%}")
        print(f"  Trades:     {result['num_trades']}")

    # Save results
    output_path = '../results/backtest_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")
