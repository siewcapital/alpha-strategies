"""
Backtest Engine for Options Dispersion Trading Strategy
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
import yaml

import sys
sys.path.insert(0, '/Users/siewbrayden/.openclaw/agents/atlas/workspace/strategies/options-dispersion')

from src.strategy import DispersionStrategy, Trade
from src.indicators import CorrelationCalculator, CorrelationMetrics
from backtest.data_loader import DataLoader


class BacktestEngine:
    """
    Event-driven backtest engine for dispersion strategy
    """
    
    def __init__(
        self,
        params: Dict,
        initial_capital: float = 1_000_000
    ):
        self.params = params
        self.initial_capital = initial_capital
        
        self.strategy: Optional[DispersionStrategy] = None
        self.results: Dict = {}
        
        # Performance tracking
        self.equity_curve: List[Dict] = []
        self.daily_returns: List[float] = []
        self.trades: List[Trade] = []
        
    def run(
        self,
        data: Dict,
        verbose: bool = False
    ) -> Dict:
        """
        Run backtest on historical data
        """
        # Initialize strategy
        self.strategy = DispersionStrategy(
            params=self.params,
            initial_capital=self.initial_capital
        )
        
        # Store price data in strategy
        self.strategy.index_prices = data['index_prices']
        self.strategy.constituent_prices = data['constituent_prices']
        
        # Get date range
        dates = data['index_prices'].index
        weights = data['weights']
        
        print(f"Running backtest from {dates[0]} to {dates[-1]}")
        print(f"Total days: {len(dates)}")
        
        # Initialize correlation calculator
        corr_calc = CorrelationCalculator(
            lookback_window=self.params['signals']['correlation']['lookback_window']
        )
        
        # Main backtest loop
        for i, date in enumerate(dates):
            if i < 90:  # Skip first 90 days for correlation calculation
                continue
            
            # Get current data
            current_index_price = data['index_prices'].loc[date]
            current_index_iv = data['options_data']['index']['implied_vol'].loc[date]
            current_vix = data['options_data']['vix'].loc[date]
            
            # Get constituent data
            constituent_vols = pd.Series({
                symbol: data['options_data']['constituents'][symbol]['implied_vol'].loc[date]
                for symbol in data['symbols']
            })
            
            constituent_prices = pd.Series({
                symbol: data['options_data']['constituents'][symbol]['price'].loc[date]
                for symbol in data['symbols']
            })
            
            # Get historical returns for correlation calculation
            hist_returns = data['constituent_returns'].loc[:date].tail(90)
            
            # Update correlation metrics
            metrics = corr_calc.update(
                timestamp=date,
                index_vol=current_index_iv,
                constituent_vols=constituent_vols,
                weights=weights,
                returns=hist_returns if len(hist_returns) >= 30 else None
            )
            
            # Prepare market data for strategy
            market_data = {
                'index_price': current_index_price,
                'index_iv': current_index_iv,
                'vix': current_vix,
                'index_vega': current_index_iv * 0.4,  # Approximate ATM straddle vega
                'avg_constituent_vega': constituent_vols.mean() * 0.4,
                'constituents': {
                    symbol: {
                        'price': constituent_prices[symbol],
                        'implied_vol': constituent_vols[symbol]
                    }
                    for symbol in data['symbols']
                },
                'correlation': metrics.implied_correlation,
                'zscore': metrics.correlation_zscore
            }
            
            # Update strategy
            result = self.strategy.update(date, metrics, market_data)
            
            # Record equity
            self.equity_curve.append({
                'date': date,
                'equity': self.strategy.current_capital,
                'position': result.get('position', 'flat'),
                'action': result.get('action', 'NONE'),
                'implied_correlation': metrics.implied_correlation,
                'correlation_zscore': metrics.correlation_zscore
            })
            
            if verbose and result.get('action') not in ['NO_SIGNAL', 'HOLD']:
                print(f"{date.date()}: {result}")
            
            # Progress indicator
            if i % 252 == 0 and i > 90:
                print(f"Progress: {date.date()} - Equity: ${self.strategy.current_capital:,.0f}")
        
        # Store results
        self.trades = self.strategy.trade_history
        
        # Calculate performance metrics
        self.results = self._calculate_metrics()
        
        return self.results
    
    def _calculate_metrics(self) -> Dict:
        """
        Calculate performance metrics
        """
        if len(self.equity_curve) == 0:
            return {}
        
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['daily_return'] = equity_df['equity'].pct_change()
        
        # Basic metrics
        final_equity = equity_df['equity'].iloc[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital
        
        # Risk metrics
        returns = equity_df['daily_return'].dropna()
        volatility = returns.std() * np.sqrt(252)
        
        # Sharpe ratio (assuming 0% risk-free rate)
        sharpe = (returns.mean() * 252) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        # Maximum drawdown
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak']
        max_drawdown = equity_df['drawdown'].min()
        
        # Calmar ratio
        calmar = (returns.mean() * 252) / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # Trade statistics
        if len(self.trades) > 0:
            trade_pnls = [t.pnl for t in self.trades]
            winning_trades = [p for p in trade_pnls if p > 0]
            losing_trades = [p for p in trade_pnls if p <= 0]
            
            trade_metrics = {
                'total_trades': len(self.trades),
                'winning_trades': len(winning_trades),
                'losing_trades': len(losing_trades),
                'win_rate': len(winning_trades) / len(self.trades) * 100,
                'avg_win': np.mean(winning_trades) if winning_trades else 0,
                'avg_loss': np.mean(losing_trades) if losing_trades else 0,
                'profit_factor': abs(sum(winning_trades) / sum(losing_trades)) if losing_trades and sum(losing_trades) != 0 else float('inf'),
                'avg_trade_return': np.mean([t.return_pct for t in self.trades]),
                'avg_holding_days': np.mean([t.holding_days for t in self.trades])
            }
        else:
            trade_metrics = {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'avg_trade_return': 0,
                'avg_holding_days': 0
            }
        
        return {
            'initial_capital': self.initial_capital,
            'final_equity': final_equity,
            'total_return': total_return * 100,
            'annualized_return': (final_equity / self.initial_capital) ** (252 / len(equity_df)) - 1 if len(equity_df) > 0 else 0,
            'volatility': volatility * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown * 100,
            'calmar_ratio': calmar,
            'trades': trade_metrics,
            'equity_curve': equity_df,
            'trade_list': self.trades
        }
    
    def print_report(self):
        """
        Print formatted backtest report
        """
        print("\n" + "="*60)
        print("OPTIONS DISPERSION TRADING STRATEGY - BACKTEST REPORT")
        print("="*60)
        
        print(f"\n📊 PERFORMANCE SUMMARY")
        print(f"Initial Capital:    ${self.results['initial_capital']:,.0f}")
        print(f"Final Equity:       ${self.results['final_equity']:,.0f}")
        print(f"Total Return:       {self.results['total_return']:.2f}%")
        print(f"Annualized Return:  {self.results['annualized_return']*100:.2f}%")
        print(f"Volatility:         {self.results['volatility']:.2f}%")
        print(f"Sharpe Ratio:       {self.results['sharpe_ratio']:.2f}")
        print(f"Max Drawdown:       {self.results['max_drawdown']:.2f}%")
        print(f"Calmar Ratio:       {self.results['calmar_ratio']:.2f}")
        
        print(f"\n📈 TRADE STATISTICS")
        trades = self.results['trades']
        print(f"Total Trades:       {trades['total_trades']}")
        print(f"Winning Trades:     {trades['winning_trades']}")
        print(f"Losing Trades:      {trades['losing_trades']}")
        print(f"Win Rate:           {trades['win_rate']:.1f}%")
        print(f"Avg Win:            ${trades['avg_win']:,.0f}")
        print(f"Avg Loss:           ${trades['avg_loss']:,.0f}")
        print(f"Profit Factor:      {trades['profit_factor']:.2f}")
        print(f"Avg Holding Days:   {trades['avg_holding_days']:.1f}")
        
        print("\n" + "="*60)
        
        # Verdict
        sharpe = self.results['sharpe_ratio']
        max_dd = abs(self.results['max_drawdown'])
        
        if sharpe > 1.0 and max_dd < 20:
            verdict = "✅ PASS - Strategy shows strong risk-adjusted returns"
        elif sharpe > 0.5 and max_dd < 30:
            verdict = "⚠️ NEEDS WORK - Promising but requires refinement"
        else:
            verdict = "❌ FAIL - Strategy underperforms"
        
        print(f"\nVERDICT: {verdict}")
        print("="*60 + "\n")


def main():
    """
    Main backtest runner
    """
    # Load configuration
    config_path = '/Users/siewbrayden/.openclaw/agents/atlas/workspace/strategies/options-dispersion/config/params.yaml'
    with open(config_path, 'r') as f:
        params = yaml.safe_load(f)
    
    # Load data
    print("Loading market data...")
    data_loader = DataLoader(use_synthetic=True)
    data = data_loader.load(
        start_date=params['backtest']['start_date'],
        end_date=params['backtest']['end_date']
    )
    
    # Run backtest
    print("\nStarting backtest...")
    engine = BacktestEngine(
        params=params,
        initial_capital=params['backtest']['initial_capital']
    )
    
    results = engine.run(data, verbose=False)
    engine.print_report()
    
    return results


if __name__ == "__main__":
    main()
