"""
Backtest Engine for IV Skew Mean Reversion Strategy

Generates synthetic crypto options data and runs event-driven backtest.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import json
import yaml

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy import IVSkewReversionStrategy, TradeDirection, PositionStatus
from src.risk_manager import RiskManager


def generate_synthetic_vol_surface_data(
    start_date: str,
    end_date: str,
    params: Dict,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate synthetic volatility surface data for backtesting.

    Creates realistic BTC/ETH vol surface data including:
    - ATM straddle IV (mean-reverting around 80% base)
    - OTM put IV (follows ATM but with skew component)
    - OTM call IV (typically lower than ATM in crypto)
    - Realized vol (mean-reverting, jumps during crisis)
    - Spot prices (random walk with momentum)

    Args:
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        params: Strategy parameters dict
        seed: Random seed for reproducibility

    Returns:
        DataFrame with columns: timestamp, asset, spot, atm_iv, otm_put_iv,
        otm_call_iv, rv_30d, skew, skew_zscore
    """
    np.random.seed(seed)

    synth = params["synthetic"]
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    # Generate daily timestamps
    dates = pd.date_range(start, end, freq="D")
    n_days = len(dates)

    records = []

    for asset in ["BTC", "ETH"]:
        # Base vol differs by asset
        vol_base = synth["vol_surface_btc_base"] if asset == "BTC" else synth["vol_surface_eth_base"]
        spot_base = 50000 if asset == "BTC" else 3000

        # State variables (mean-reverting)
        vol_state = vol_base  # ATM vol state
        rv_state = vol_base * 0.9  # Realized vol state
        skew_state = synth["skew_mean"]  # Mean skew
        spot_state = spot_base
        crisis_active = False
        crisis_days_remaining = 0

        for i, date in enumerate(dates):
            # Crisis events (rare but impactful)
            if not crisis_active and np.random.random() < synth["crisis_frequency"]:
                crisis_active = True
                crisis_days_remaining = np.random.randint(3, 14)

            if crisis_active:
                crisis_days_remaining -= 1
                if crisis_days_remaining <= 0:
                    crisis_active = False

            # Mean-reverting vol (Ornstein-Uhlenbeck process)
            vol_mean_reversion_speed = 0.1
            vol_shock = np.random.normal(0, 0.05)
            vol_state = vol_state + vol_mean_reversion_speed * (vol_base - vol_state) + vol_shock
            vol_state = max(0.3, min(vol_state, 2.5))  # Bound vol

            # Realized vol (follows vol_state with lag and crisis spike)
            if crisis_active:
                rv_state = rv_state * 1.05 + synth["crisis_skew_impact"] / 100
            else:
                rv_state = rv_state + 0.05 * (vol_state - rv_state) + np.random.normal(0, 0.02)
            rv_state = max(0.2, min(rv_state, 2.5))

            # Skew mean-reversion (slower = more persistent extremes)
            skew_mean_reversion = 0.02  # Very slow = skew stays extreme for long periods
            skew_shock = np.random.normal(0, (synth["skew_std"] * 1.5) / 100)
            skew_state = skew_state + skew_mean_reversion * (synth["skew_mean"] - skew_state) + skew_shock

            # Crisis pushes skew more negative (puts get even more expensive)
            if crisis_active:
                skew_state -= np.random.uniform(3.0, 10.0)  # Bigger skew impact in crisis

            skew_state = max(-80, min(skew_state, -10))  # Bound skew wider

            # Scheduled skew extremes to create tradable events
            # Every ~60 days, skew tends toward extremes
            if i % 60 < 15 and i > 90:  # During specific windows
                skew_state = max(skew_state, skew_state - np.random.uniform(5, 15))

            # Spot price (random walk with momentum)
            daily_return = np.random.normal(0.0002, vol_state / np.sqrt(365))
            if crisis_active:
                daily_return -= np.random.uniform(0.01, 0.04)  # Crisis = negative returns
            spot_state *= (1 + daily_return)

            # IV surface construction
            atm_iv = vol_state
            otm_put_iv = atm_iv * (1 + skew_state / 100)  # Skew reduces put IV
            otm_call_iv = atm_iv * (1 - 0.05)  # Calls slightly cheaper

            # Realized vol
            rv_30d = rv_state

            records.append({
                "timestamp": date,
                "asset": asset,
                "spot": spot_state,
                "atm_iv": atm_iv,
                "otm_put_iv": otm_put_iv,
                "otm_call_iv": otm_call_iv,
                "rv_30d": rv_30d,
                "skew": skew_state,
                "crisis": crisis_active,
            })

    df = pd.DataFrame(records)
    df = df.sort_values(["timestamp", "asset"]).reset_index(drop=True)
    return df


def run_backtest(
    params: Dict,
    start_date: str,
    end_date: str,
    initial_capital: float = 1_000_000,
    output_dir: Optional[str] = None,
) -> Dict:
    """
    Run complete backtest of the IV Skew Mean Reversion strategy.

    Args:
        params: Strategy parameters dict
        start_date: Backtest start date
        end_date: Backtest end date
        initial_capital: Starting capital
        output_dir: Directory to save results

    Returns:
        Dict with full backtest results and performance metrics
    """
    print(f"=" * 60)
    print(f"IV SKEW MEAN REVERSION - BACKTEST")
    print(f"Period: {start_date} to {end_date}")
    print(f"Initial Capital: ${initial_capital:,.0f}")
    print(f"=" * 60)

    # Generate synthetic data
    print("\n[1/5] Generating synthetic vol surface data...")
    df = generate_synthetic_vol_surface_data(start_date, end_date, params)

    print(f"   Generated {len(df)} daily observations for BTC + ETH")
    print(f"   Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    # Initialize strategy
    print("\n[2/5] Initializing strategy...")
    strategy = IVSkewReversionStrategy(
        params=params,
        initial_capital=initial_capital,
        assets=["BTC", "ETH"],
    )
    risk_mgr = RiskManager(params, initial_capital)

    # Track daily portfolio values
    daily_values = []
    trade_log = []

    # Process each day
    print("\n[3/5] Running backtest simulation...")

    for date in sorted(df["timestamp"].unique()):
        daily_data = df[df["timestamp"] == date]

        # Track daily PnL
        prev_equity = strategy.state.portfolio_value

        for _, row in daily_data.iterrows():
            result = strategy.process_market_data(
                timestamp=row["timestamp"],
                asset=row["asset"],
                spot_price=row["spot"],
                atm_straddle_iv=row["atm_iv"],
                otm_put_iv=row["otm_put_iv"],
                otm_call_iv=row["otm_call_iv"],
                rv_30d=row["rv_30d"],
            )

            # Handle entry signals
            if result["new_entry"]:
                signal = result["new_entry"][0]
                metrics = signal["metrics"]
                direction = signal["direction"]

                # Calculate position size
                contracts, premium = risk_mgr.calculate_position_size(
                    signal_strength=signal["signal"]["signal_strength"],
                    portfolio_value=strategy.state.portfolio_value,
                    skew=metrics.skew,
                    rv_30d=metrics.rv_30d,
                    trade_direction=direction,
                    implied_vol=metrics.atm_iv,
                    days_to_expiry=21,
                )

                if contracts > 0:
                    trade = strategy.open_trade(
                        entry_signal=signal,
                        spot_price=row["spot"],
                        skew=metrics.skew,
                        premium_per_contract=premium,
                        contracts=contracts,
                    )
                    trade_log.append({
                        "date": date,
                        "asset": row["asset"],
                        "direction": direction.name,
                        "skew_entry": metrics.skew,
                        "spot_entry": row["spot"],
                        "contracts": contracts,
                        "premium": trade.premium_received,
                        "trade_id": trade.trade_id,
                    })

            # Handle exit signals
            if result["exit_trades"]:
                for trade in result["exit_trades"]:
                    trade_log.append({
                        "date": date,
                        "asset": trade.asset,
                        "direction": "EXIT",
                        "exit_reason": trade.status.value,
                        "skew_exit": trade.exit_skew,
                        "spot_exit": trade.exit_spot,
                        "pnl": trade.pnl,
                        "pnl_pct": trade.pnl_pct,
                        "days_held": trade.days_held,
                        "trade_id": trade.trade_id,
                    })

        # Daily equity record
        equity = strategy.state.portfolio_value
        daily_pnl = equity - prev_equity
        risk_mgr.record_daily_pnl(daily_pnl)

        daily_values.append({
            "date": date,
            "equity": equity,
            "cash": strategy.state.cash,
            "open_positions": len(strategy.state.positions),
            "drawdown": strategy.state.current_drawdown,
            "daily_pnl": daily_pnl,
        })

        # Reset circuit breaker at end of each day
        if risk_mgr.is_trading_halted():
            # Check if should resume
            if equity >= strategy.state.peak_equity * 0.95:  # Recovered 5%
                risk_mgr.resume_trading()

    # Calculate performance metrics
    print("\n[4/5] Calculating performance metrics...")
    metrics = strategy.get_performance_metrics()

    # Build equity curve
    equity_df = pd.DataFrame(daily_values)
    equity_df["equity"] = equity_df["equity"].astype(float)
    equity_df["drawdown"] = equity_df["drawdown"].astype(float)

    # Calculate rolling Sharpe
    if len(equity_df) > 30:
        equity_df["daily_return"] = equity_df["equity"].pct_change()
        rolling_mean = equity_df["daily_return"].rolling(30).mean()
        rolling_std = equity_df["daily_return"].rolling(30).std()
        equity_df["rolling_sharpe_30d"] = (rolling_mean / rolling_std) * np.sqrt(365)

    # Trade analysis
    trades_df = pd.DataFrame(trade_log)
    if len(trades_df) > 0:
        trades_df["date"] = pd.to_datetime(trades_df["date"])

    # Print results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    print(f"\n📊 PERFORMANCE METRICS")
    print(f"   Total Return:     {metrics['total_return']*100:.1f}%")
    print(f"   Total PnL:        ${metrics['total_pnl']:,.0f}")
    print(f"   Sharpe Ratio:     {metrics['sharpe']:.2f}")
    print(f"   Sortino Ratio:    {metrics['sortino']:.2f}")
    print(f"   Max Drawdown:      {metrics['max_drawdown']*100:.1f}%")

    print(f"\n📈 TRADE STATISTICS")
    print(f"   Total Trades:     {metrics['total_trades']}")
    print(f"   Winning Trades:   {metrics['winning_trades']}")
    print(f"   Losing Trades:    {metrics['losing_trades']}")
    print(f"   Win Rate:         {metrics['win_rate']*100:.1f}%")
    print(f"   Profit Factor:    {metrics['profit_factor']:.2f}")
    print(f"   Avg Win:          ${metrics['avg_win']:,.0f}")
    print(f"   Avg Loss:         ${metrics['avg_loss']:,.0f}")
    print(f"   Avg Days Held:    {metrics['avg_days_held']:.1f}")

    print(f"\n💰 PORTFOLIO")
    print(f"   Initial Capital:  ${initial_capital:,.0f}")
    print(f"   Final Equity:    ${equity_df['equity'].iloc[-1]:,.0f}")
    print(f"   Peak Equity:     ${equity_df['equity'].max():,.0f}")

    # Save results
    if output_dir:
        print(f"\n[5/5] Saving results to {output_dir}/...")
        os.makedirs(output_dir, exist_ok=True)

        # Save equity curve
        equity_df.to_csv(f"{output_dir}/equity_curve.csv", index=False)

        # Save trade log
        if len(trades_df) > 0:
            trades_df.to_csv(f"{output_dir}/trades.csv", index=False)

        # Save metrics
        with open(f"{output_dir}/metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)

        # Save final equity curve plot (text)
        with open(f"{output_dir}/equity_curve.txt", "w") as f:
            f.write("IV Skew Mean Reversion - Equity Curve\n")
            f.write(f"Period: {start_date} to {end_date}\n")
            f.write("=" * 40 + "\n")
            for _, row in equity_df.iterrows():
                f.write(f"{row['date'].strftime('%Y-%m-%d')}: ${row['equity']:,.0f} | DD: {row['drawdown']*100:.1f}%\n")

    print("\n✅ Backtest complete!")

    return {
        "metrics": metrics,
        "equity_curve": equity_df,
        "trades": trades_df,
        "params": params,
    }


if __name__ == "__main__":
    # Load params
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "params.yaml")

    with open(config_path) as f:
        params = yaml.safe_load(f)

    # Run backtest
    results = run_backtest(
        params=params,
        start_date=params["backtest"]["start_date"],
        end_date=params["backtest"]["end_date"],
        initial_capital=params["backtest"]["initial_capital"],
        output_dir=os.path.join(base_dir, "results"),
    )
