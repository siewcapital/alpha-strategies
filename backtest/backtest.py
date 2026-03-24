"""
Backtest Engine for Funding Rate Arbitrage

Simulates strategy performance on historical data.

Author: ATLAS (Siew's Capital)
Date: 2026-03-24
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

from strategy import ArbitrageOpportunity, FundingRate, FundingRateArbitrageStrategy, Position, SignalType
from src.data_fetcher import MockDataFetcher

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Backtesting engine for funding rate arbitrage.
    
    Simulates strategy execution with realistic costs and slippage.
    """
    
    def __init__(self, config_path: str = "config/params.yaml"):
        """
        Initialize backtest engine.
        
        Args:
            config_path: Path to configuration file
        """
        # Load config
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Strategy parameters
        self.initial_capital = self.config.get("backtest", {}).get("initial_capital", 100000)
        self.capital = self.initial_capital
        self.start_date = self.config.get("backtest", {}).get("start_date", "2023-01-01")
        self.end_date = self.config.get("backtest", {}).get("end_date", "2026-03-24")
        self.assets = self.config.get("backtest", {}).get("assets", ["BTC", "ETH", "SOL"])
        
        # Costs
        self.maker_fee = self.config["costs"]["maker_fee"]
        self.taker_fee = self.config["costs"]["taker_fee"]
        self.slippage = self.config["costs"]["expected_slippage"]
        
        # Initialize strategy and data fetcher
        self.strategy = FundingRateArbitrageStrategy(config_path)
        self.data_fetcher = MockDataFetcher(self.config)
        
        # Results storage
        self.trades: List[dict] = []
        self.equity_curve: List[dict] = []
        self.daily_returns: List[float] = []
        
        logger.info(f"Backtest initialized: ${self.initial_capital:,.2f}")
    
    def generate_historical_data(
        self,
        days: int = 500
    ) -> pd.DataFrame:
        """
        Generate realistic historical funding rate data.
        
        Args:
            days: Number of days of data
            
        Returns:
            DataFrame with historical funding rates
        """
        dates = pd.date_range(
            start=self.start_date,
            end=self.end_date,
            freq='8H'  # 8-hour funding periods
        )
        
        data = []
        
        for date in dates:
            for exchange in ["binance", "bybit", "okx"]:
                for symbol in self.assets:
                    # Generate realistic funding rates
                    # Base rate depends on market conditions
                    base_volatility = 0.0005 if symbol in ["BTC", "ETH"] else 0.001
                    
                    # Add market regime effects
                    regime_multiplier = self._get_regime_multiplier(date)
                    
                    rate = np.random.normal(0, base_volatility * regime_multiplier)
                    
                    # Add exchange bias
                    exchange_bias = {
                        "binance": 0.00003,
                        "bybit": -0.00001,
                        "okx": 0.00002
                    }.get(exchange, 0)
                    
                    rate += exchange_bias
                    
                    # Cap at reasonable values
                    rate = max(-0.001, min(0.001, rate))
                    
                    # Generate mark price (simplified random walk)
                    base_price = {
                        "BTC": 70000, "ETH": 2100, "SOL": 180,
                        "BNB": 630, "XRP": 0.55, "ADA": 0.45,
                        "DOGE": 0.08, "AVAX": 35, "DOT": 7, "MATIC": 0.85
                    }.get(symbol, 100)
                    
                    price = base_price * (1 + np.random.normal(0, 0.02))
                    
                    data.append({
                        "timestamp": date,
                        "exchange": exchange,
                        "symbol": symbol,
                        "funding_rate": rate,
                        "mark_price": price,
                        "index_price": price * (1 + np.random.normal(0, 0.001))
                    })
        
        return pd.DataFrame(data)
    
    def _get_regime_multiplier(self, date: datetime) -> float:
        """
        Get market regime multiplier.
        
        Simulates different market conditions:
        - Bull market: higher positive funding
        - Bear market: higher negative funding
        - Chop: random funding
        """
        # Simplified regime simulation
        month = date.month
        
        # Summer (May-Oct): typically lower volatility
        if month in [5, 6, 7, 8, 9, 10]:
            return 0.8
        # Winter (Nov-Apr): typically higher volatility
        else:
            return 1.2
    
    def run_backtest(self) -> Dict:
        """
        Run the backtest.
        
        Returns:
            Dict of backtest results
        """
        logger.info("Starting backtest...")
        
        # Generate historical data
        historical_data = self.generate_historical_data()
        
        # Get unique timestamps
        timestamps = sorted(historical_data["timestamp"].unique())
        
        logger.info(f"Running backtest over {len(timestamps)} funding periods")
        
        # Run simulation
        for i, ts in enumerate(timestamps):
            # Get data for this timestamp
            period_data = historical_data[historical_data["timestamp"] == ts]
            
            # Build funding data structure
            funding_data = {}
            for exchange in ["binance", "bybit", "okx"]:
                funding_data[exchange] = {}
                exchange_data = period_data[period_data["exchange"] == exchange]
                
                for _, row in exchange_data.iterrows():
                    funding_data[exchange][row["symbol"]] = FundingRate(
                        exchange=exchange,
                        symbol=row["symbol"],
                        rate=row["funding_rate"],
                        next_settle=ts + timedelta(hours=8),
                        mark_price=row["mark_price"],
                        index_price=row["index_price"],
                        timestamp=ts
                    )
            
            # Scan for opportunities
            opportunities = self.strategy.scan_opportunities(funding_data)
            
            # Process opportunities
            for opp in opportunities[:3]:  # Take top 3
                # Check if we should enter
                if opp.symbol not in self.strategy.positions:
                    # Generate signal
                    signal_type, position = self.strategy.generate_signal(
                        opp, self.capital
                    )
                    
                    if signal_type == SignalType.ENTER_LONG:
                        # Simulate execution with slippage
                        executed = self._simulate_entry(position)
                        
                        if executed:
                            # Record trade
                            self.trades.append({
                                "timestamp": ts,
                                "symbol": position.symbol,
                                "type": "ENTRY",
                                "exchange_pair": f"{position.long_exchange}/{position.short_exchange}",
                                "size": position.size,
                                "long_rate": position.entry_long_rate,
                                "short_rate": position.entry_short_rate,
                                "margin_used": position.margin_used,
                                "pnl": 0
                            })
            
            # Update positions and collect funding
            self._update_positions(ts)
            
            # Record equity
            self.equity_curve.append({
                "timestamp": ts,
                "capital": self.capital,
                "positions": len(self.strategy.positions),
                "total_pnl": self.strategy.total_pnl
            })
            
            # Log progress
            if (i + 1) % 100 == 0:
                logger.info(f"Period {i+1}/{len(timestamps)}: Capital ${self.capital:,.2f}")
        
        # Close all positions at end
        self._close_all_positions(timestamps[-1])
        
        # Calculate metrics
        results = self._calculate_metrics()
        
        logger.info(f"Backtest complete. Final capital: ${self.capital:,.2f}")
        
        return results
    
    def _simulate_entry(self, position: Position) -> bool:
        """
        Simulate position entry with costs.
        
        Args:
            position: Position to enter
            
        Returns:
            True if entry successful
        """
        # Check capital
        if position.margin_used > self.capital:
            return False
        
        # Apply costs
        entry_cost = position.margin_used * (self.taker_fee + self.slippage)
        
        # Reduce capital
        self.capital -= entry_cost
        
        # Add position
        self.strategy.positions[position.symbol] = position
        
        return True
    
    def _update_positions(self, timestamp: datetime):
        """
        Update positions, collect funding, check exits.
        
        Args:
            timestamp: Current timestamp
        """
        # Simulate time passing (8 hours)
        time_passed = timedelta(hours=8)
        
        # For each position, add funding received
        for symbol, position in list(self.strategy.positions.items()):
            # Simulate holding for 8 hours
            # In real backtest, would use actual funding rates
            
            # Calculate funding received
            # (Simplified - uses entry rates)
            periods_held = 1
            
            # Funding on long side (positive rate = we receive)
            long_funding = position.size * position.entry_long_rate * periods_held
            
            # Funding on short side
            short_funding = position.size * position.entry_short_rate * periods_held
            
            # Net funding
            net_funding = long_funding + short_funding
            
            # Add to capital
            self.capital += net_funding
            
            # Check exit conditions
            if self.strategy.check_exit_conditions(position):
                self._close_position(position, timestamp)
    
    def _close_position(self, position: Position, timestamp: datetime):
        """
        Close a position.
        
        Args:
            position: Position to close
            timestamp: Current timestamp
        """
        # Calculate PnL
        pnl = self.strategy.calculate_position_pnl(position)
        
        # Apply exit costs
        exit_cost = position.margin_used * (self.taker_fee + self.slippage)
        
        # Return margin
        self.capital += position.margin_used
        self.capital += pnl - exit_cost
        
        # Record trade
        self.trades.append({
            "timestamp": timestamp,
            "symbol": position.symbol,
            "type": "EXIT",
            "exchange_pair": f"{position.long_exchange}/{position.short_exchange}",
            "size": position.size,
            "margin_used": position.margin_used,
            "pnl": pnl - exit_cost,
            "holding_period": position.days_held()
        })
        
        # Remove position
        del self.strategy.positions[position.symbol]
    
    def _close_all_positions(self, timestamp: datetime):
        """Close all remaining positions."""
        for position in list(self.strategy.positions.values()):
            self._close_position(position, timestamp)
    
    def _calculate_metrics(self) -> Dict:
        """
        Calculate backtest performance metrics.
        
        Returns:
            Dict of metrics
        """
        if not self.equity_curve:
            return {}
        
        # Get series
        capital_series = pd.Series([e["capital"] for e in self.equity_curve])
        returns = capital_series.pct_change().dropna()
        
        # Calculate metrics
        total_return = (self.capital - self.initial_capital) / self.initial_capital
        
        # Annualized return (assuming 3 funding periods per day)
        periods_per_day = 3
        days = len(self.equity_curve) / periods_per_day
        annualization_factor = 365 / days
        annualized_return = (1 + total_return) ** annualization_factor - 1
        
        # Sharpe ratio (assuming risk-free rate of 0)
        if returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(365 * periods_per_day)
        else:
            sharpe = 0
        
        # Max drawdown
        running_max = capital_series.cummax()
        drawdown = (capital_series - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # Win rate
        closed_trades = [t for t in self.trades if t["type"] == "EXIT"]
        if closed_trades:
            wins = [t for t in closed_trades if t["pnl"] > 0]
            win_rate = len(wins) / len(closed_trades)
        else:
            win_rate = 0
        
        # Profit factor
        if closed_trades:
            gross_profit = sum(t["pnl"] for t in closed_trades if t["pnl"] > 0)
            gross_loss = abs(sum(t["pnl"] for t in closed_trades if t["pnl"] < 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        else:
            profit_factor = 0
        
        metrics = {
            "initial_capital": self.initial_capital,
            "final_capital": self.capital,
            "total_return": total_return,
            "annualized_return": annualized_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_trades": len(closed_trades),
            "winning_trades": len([t for t in closed_trades if t["pnl"] > 0]),
            "losing_trades": len([t for t in closed_trades if t["pnl"] <= 0]),
            "avg_holding_period": np.mean([t.get("holding_period", 0) for t in closed_trades]) if closed_trades else 0
        }
        
        return metrics
    
    def save_results(self, output_dir: str = "results"):
        """
        Save backtest results to files.
        
        Args:
            output_dir: Output directory
        """
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        # Save trades
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv(f"{output_dir}/trades.csv", index=False)
        
        # Save equity curve
        if self.equity_curve:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.to_csv(f"{output_dir}/equity_curve.csv", index=False)
        
        # Save metrics
        metrics = self._calculate_metrics()
        if metrics:
            import json
            with open(f"{output_dir}/metrics.json", 'w') as f:
                json.dump(metrics, f, indent=2)
        
        logger.info(f"Results saved to {output_dir}/")


def main():
    """Run backtest."""
    logging.basicConfig(level=logging.INFO)
    
    engine = BacktestEngine()
    results = engine.run_backtest()
    
    print("\n" + "="*50)
    print("BACKTEST RESULTS")
    print("="*50)
    print(f"Initial Capital:    ${results.get('initial_capital', 0):,.2f}")
    print(f"Final Capital:     ${results.get('final_capital', 0):,.2f}")
    print(f"Total Return:      {results.get('total_return', 0):.2%}")
    print(f"Annualized Return: {results.get('annualized_return', 0):.2%}")
    print(f"Sharpe Ratio:      {results.get('sharpe_ratio', 0):.2f}")
    print(f"Max Drawdown:      {results.get('max_drawdown', 0):.2%}")
    print(f"Win Rate:          {results.get('win_rate', 0):.2%}")
    print(f"Profit Factor:     {results.get('profit_factor', 0):.2f}")
    print(f"Total Trades:      {results.get('total_trades', 0)}")
    print("="*50)
    
    # Save results
    engine.save_results()


if __name__ == "__main__":
    main()
