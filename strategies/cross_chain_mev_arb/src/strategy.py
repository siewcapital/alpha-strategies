"""
Cross-Chain MEV Arbitrage Strategy - Main Orchestrator
Institutional-grade cross-chain arbitrage system.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import logging
import yaml
from pathlib import Path
from datetime import datetime, timedelta
import json

# Import strategy modules
from src.price_monitor import PriceMonitor, Chain, CrossChainSpread
from src.bridge_router import BridgeRouter, BridgeType
from src.gas_estimator import GasEstimator, GasQuote
from src.arb_detector import ArbitrageDetector, ArbitrageOpportunity, OpportunityType
from src.risk_manager import RiskManager, RiskMetrics, RiskCheckResult, RiskStatus
from src.signal_generator import SignalGenerator, TradeSignal, SignalType
from src.execution_engine import ExecutionEngine, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)


class StrategyStatus(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    EXECUTING = "executing"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass
class StrategyState:
    """Current state of the strategy"""
    status: StrategyStatus = StrategyStatus.IDLE
    portfolio_value_usd: float = 100_000.0
    total_pnl_usd: float = 0.0
    total_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_gas_spent_usd: float = 0.0
    active_positions: int = 0
    last_scan_time: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    uptime_seconds: float = 0.0
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.successful_trades / self.total_trades
    
    @property
    def avg_pnl_per_trade(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl_usd / self.total_trades


class CrossChainMEVStrategy:
    """
    Main orchestrator for Cross-Chain MEV Arbitrage.
    
    Strategy flow:
    1. Scan for cross-chain price spreads
    2. Detect arbitrage opportunities (spread > costs)
    3. Generate trade signals with sizing
    4. Risk check all signals
    5. Execute best opportunities
    6. Monitor and manage positions
    7. Record results and update state
    """
    
    def __init__(
        self,
        config_path: str = "config/params.yaml",
        initial_capital: float = 100_000,
    ):
        # Load configuration
        self.config = self._load_config(config_path)
        self.initial_capital = initial_capital
        
        # Initialize state
        self.state = StrategyState(portfolio_value_usd=initial_capital)
        
        # Initialize components
        self.gas_estimator = GasEstimator(self.config)
        self.price_monitor = PriceMonitor(
            chain_configs=self._build_chain_configs(),
            dex_configs=self._build_dex_configs(),
            gas_estimator=self.gas_estimator,
        )
        self.bridge_router = BridgeRouter(self.config)
        self.arb_detector = ArbitrageDetector(
            config=self.config,
            price_monitor=self.price_monitor,
            bridge_router=self.bridge_router,
            gas_estimator=self.gas_estimator,
        )
        self.risk_manager = RiskManager(self.config, initial_capital)
        self.signal_generator = SignalGenerator(
            config=self.config,
            arb_detector=self.arb_detector,
            risk_manager=self.risk_manager,
            gas_estimator=self.gas_estimator,
        )
        self.execution_engine = ExecutionEngine(
            config=self.config,
            gas_estimator=self.gas_estimator,
        )
        
        # Trading pairs to monitor
        self.pairs = self._build_pairs()
        self.chain_pairs = self._build_chain_pairs()
        
        # Control flags
        self._running = False
        self._scan_task = None
        self._execution_task = None
        
        logger.info(
            f"CrossChainMEVStrategy initialized | "
            f"Capital: ${initial_capital:,.0f} | "
            f"Pairs: {len(self.pairs)} | "
            f"Chains: {len(self.chain_pairs)}"
        )
    
    def _load_config(self, config_path: str) -> Dict:
        """Load YAML configuration"""
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                config = yaml.safe_load(f)
            logger.info(f"Config loaded from {config_path}")
            return config
        else:
            logger.warning(f"Config not found at {config_path}, using defaults")
            return self._default_config()
    
    def _default_config(self) -> Dict:
        """Default configuration if file not found"""
        return {
            'trading': {
                'pairs': [
                    {'base': 'WETH', 'quote': 'USDC', 'min_trade_usd': 5000, 'max_trade_usd': 500000},
                    {'base': 'WBTC', 'quote': 'USDC', 'min_trade_usd': 10000, 'max_trade_usd': 500000},
                ],
                'arbitrage': {
                    'min_spread_bps': 15,
                    'zscore_entry_threshold': 2.0,
                    'lookback_periods': 500,
                    'cooldown_seconds': 60,
                }
            },
            'risk': {
                'max_daily_trades': 20,
                'max_concurrent_trades': 3,
                'max_bridge_exposure_pct': 0.20,
                'max_daily_loss_pct': 0.03,
                'max_drawdown_pct': 0.10,
                'gas_spike_multiplier': 3.0,
            }
        }
    
    def _build_chain_configs(self) -> Dict[Chain, Dict]:
        """Build chain configuration dict"""
        chains_cfg = self.config.get('chains', {})
        return {
            Chain.ETHEREUM: chains_cfg.get('ethereum', {}),
            Chain.ARBITRUM: chains_cfg.get('arbitrum', {}),
            Chain.OPTIMISM: chains_cfg.get('optimism', {}),
            Chain.BASE: chains_cfg.get('base', {}),
        }
    
    def _build_dex_configs(self) -> Dict[str, Dict]:
        """Build DEX configuration dict"""
        dexes_cfg = self.config.get('dexes', {})
        return dexes_cfg
    
    def _build_pairs(self) -> List[str]:
        """Build list of trading pairs"""
        pairs_cfg = self.config.get('trading', {}).get('pairs', [])
        return [f"{p['base']}/{p['quote']}" for p in pairs_cfg]
    
    def _build_chain_pairs(self) -> List[Tuple[str, str]]:
        """Build list of chain pairs to monitor"""
        # Monitor ETH-ARB and ARB-OP as most liquid cross-chain pairs
        return [
            ('ethereum', 'arbitrum'),
            ('arbitrum', 'ethereum'),
            ('ethereum', 'optimism'),
            ('optimism', 'ethereum'),
            ('arbitrum', 'base'),
            ('base', 'arbitrum'),
            ('ethereum', 'base'),
            ('base', 'ethereum'),
        ]
    
    # ─── Main Control ────────────────────────────────────────────────────────
    
    async def start(self) -> None:
        """Start the strategy"""
        if self._running:
            logger.warning("Strategy already running")
            return
        
        self._running = True
        self.state.status = StrategyStatus.SCANNING
        
        await self.price_monitor.start()
        
        # Start background tasks
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._execution_task = asyncio.create_task(self._execution_loop())
        
        start_time = datetime.now()
        logger.info(f"Strategy started at {start_time}")
    
    async def stop(self) -> None:
        """Stop the strategy"""
        self._running = False
        self.state.status = StrategyStatus.STOPPED
        
        await self.price_monitor.stop()
        
        if self._scan_task:
            self._scan_task.cancel()
        if self._execution_task:
            self._execution_task.cancel()
        
        logger.info(f"Strategy stopped. Total uptime: {self.state.uptime_seconds:.0f}s")
    
    async def pause(self) -> None:
        """Pause the strategy"""
        self._running = False
        self.state.status = StrategyStatus.PAUSED
        logger.info("Strategy paused")
    
    # ─── Core Loops ──────────────────────────────────────────────────────────
    
    async def _scan_loop(self) -> None:
        """
        Main scanning loop - looks for arbitrage opportunities.
        Runs every 5 seconds.
        """
        while self._running:
            try:
                await self._scan_opportunities()
                self.state.last_scan_time = datetime.now()
                await asyncio.sleep(5)  # Scan every 5 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                await asyncio.sleep(10)
    
    async def _execution_loop(self) -> None:
        """
        Execution loop - processes signals and executes trades.
        Runs every 10 seconds.
        """
        while self._running:
            try:
                await self._process_signals()
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Execution loop error: {e}")
                await asyncio.sleep(10)
    
    async def _scan_opportunities(self) -> None:
        """Scan all chain pairs for arbitrage opportunities"""
        all_opportunities = []
        
        for pair in self.pairs:
            for chain_a, chain_b in self.chain_pairs:
                try:
                    # Detect opportunities
                    opps = await self.arb_detector.detect_opportunities(
                        pair=pair,
                        chain_a=chain_a,
                        chain_b=chain_b,
                        trade_size_usd=min(100_000, self.state.portfolio_value_usd * 0.10),
                    )
                    all_opportunities.extend(opps)
                except Exception as e:
                    logger.warning(f"Error scanning {pair} {chain_a}-{chain_b}: {e}")
                    continue
        
        # Generate signals from opportunities
        signals = []
        for opp in all_opportunities:
            signal = self.signal_generator.generate_signal(
                opportunity=opp,
                portfolio_value=self.state.portfolio_value_usd,
            )
            if signal.is_actionable():
                signals.append(signal)
        
        # Log best opportunity
        if all_opportunities:
            best = max(all_opportunities, key=lambda o: o.net_profit_usd)
            if best.is_profitable:
                logger.debug(
                    f"Best opportunity: {best.pair} | "
                    f"Spread: {best.spread_bps:.1f}bps | "
                    f"Net profit: ${best.net_profit_usd:.2f}"
                )
    
    async def _process_signals(self) -> None:
        """Process active signals and execute best opportunities"""
        signals = self.signal_generator.get_active_signals()
        
        if not signals:
            return
        
        # Filter to best signals
        best_signals = self.signal_generator.filter_signals(signals, top_n=1)
        
        for signal in best_signals:
            # Risk check
            risk_result = self.risk_manager.check_trade(
                opportunity=signal.opportunity,
                gas_estimator=self.gas_estimator,
            )
            
            if not risk_result.allowed:
                logger.info(f"Risk check failed: {risk_result.message}")
                continue
            
            # Apply size reduction if needed
            size = signal.recommended_size_usd
            if risk_result.reduction_factor < 1.0:
                size *= risk_result.reduction_factor
                logger.warning(f"Position reduced to ${size:,.0f}")
            
            # Execute
            self.state.status = StrategyStatus.EXECUTING
            await self._execute_trade(signal, size)
            
            # Brief pause between trades
            await asyncio.sleep(2)
    
    async def _execute_trade(
        self,
        signal: TradeSignal,
        size_usd: float,
    ) -> ExecutionResult:
        """Execute a single arbitrage trade"""
        opp = signal.opportunity
        self.state.status = StrategyStatus.EXECUTING
        
        logger.info(
            f"Executing: {opp.opportunity_id} | "
            f"Pair: {opp.pair} | "
            f"Size: ${size_usd:,.0f} | "
            f"Direction: {opp.direction}"
        )
        
        # Record position
        self.risk_manager.open_position(opp.opportunity_id, opp, size_usd)
        self.state.active_positions += 1
        
        # Execute
        result = await self.execution_engine.execute(opp, size_usd)
        
        # Update state
        self.state.total_trades += 1
        self.state.total_gas_spent_usd += result.total_gas_usd
        
        if result.is_success:
            self.state.successful_trades += 1
            self.state.total_pnl_usd += result.net_profit_usd
            self.state.portfolio_value_usd += result.net_profit_usd
            self.state.last_trade_time = datetime.now()
            logger.info(
                f"✅ Trade SUCCESS: {opp.opportunity_id} | "
                f"PnL: ${result.net_profit_usd:,.2f} | "
                f"Portfolio: ${self.state.portfolio_value_usd:,.2f}"
            )
        else:
            self.state.failed_trades += 1
            self.state.total_pnl_usd += result.net_profit_usd
            self.state.portfolio_value_usd += result.net_profit_usd
            logger.warning(
                f"❌ Trade FAILED: {opp.opportunity_id} | "
                f"Reason: {result.failure_reason} | "
                f"PnL: ${result.net_profit_usd:,.2f}"
            )
        
        # Record trade in risk manager
        self.risk_manager.record_trade(
            opportunity_id=opp.opportunity_id,
            opportunity=opp,
            executed_size_usd=size_usd,
            actual_pnl_usd=result.net_profit_usd,
            status="success" if result.is_success else "failed",
            failure_reason=result.failure_reason,
        )
        
        self.state.active_positions = max(0, self.state.active_positions - 1)
        self.state.status = StrategyStatus.SCANNING
        
        return result
    
    # ─── Backtest Interface ──────────────────────────────────────────────────
    
    async def run_backtest(
        self,
        start_date: str,
        end_date: str,
        initial_capital: float = 100_000,
        verbose: bool = True,
    ) -> Dict:
        """
        Run backtest for the strategy.
        
        Args:
            start_date: Start date string (YYYY-MM-DD)
            end_date: End date string (YYYY-MM-DD)
            initial_capital: Starting capital in USD
            verbose: Print results
            
        Returns:
            Dictionary with backtest results and metrics
        """
        from datetime import datetime as dt
        
        start_dt = dt.strptime(start_date, "%Y-%m-%d")
        end_dt = dt.strptime(end_date, "%Y-%m-%d")
        days = (end_dt - start_dt).days
        
        logger.info(f"Starting backtest: {start_date} to {end_date} ({days} days)")
        
        # Initialize backtest state
        self.initial_capital = initial_capital
        self.state = StrategyState(portfolio_value_usd=initial_capital)
        
        # Generate synthetic spread data
        synthetic_spreads = self._generate_synthetic_spreads(days)
        
        trades = []
        portfolio_values = []
        
        # Run simulation
        for day_idx, day_spreads in enumerate(synthetic_spreads):
            for spread_data in day_spreads:
                pair = spread_data['pair']
                spread_bps = spread_data['spread_bps']
                chain_a = spread_data['chain_a']
                chain_b = spread_data['chain_b']
                
                # Check if profitable
                if spread_bps < 15:  # Below minimum spread
                    continue
                
                # Check cooldown
                if self._in_cooldown(pair, chain_a, chain_b):
                    continue
                
                # Simulate opportunity
                opp = self._simulate_opportunity(
                    pair, chain_a, chain_b, spread_bps
                )
                
                if not opp.is_profitable:
                    continue
                
                # Risk check
                risk_result = self.risk_manager.check_trade(opp)
                if not risk_result.allowed:
                    continue
                
                # Size
                size = min(
                    opp.optimal_trade_size_usd,
                    self.state.portfolio_value_usd * 0.10
                )
                if size < 5000:
                    continue
                
                # Simulate execution result
                result = self._simulate_execution(opp, size)
                
                # Record
                self.state.total_trades += 1
                self.state.total_pnl_usd += result['net_pnl']
                self.state.total_gas_spent_usd += result['gas']
                self.state.portfolio_value_usd += result['net_pnl']
                
                if result['net_pnl'] > 0:
                    self.state.successful_trades += 1
                else:
                    self.state.failed_trades += 1
                
                # Record cooldown
                self._set_cooldown(pair, chain_a, chain_b)
                
                trades.append({
                    'day': day_idx,
                    'pair': pair,
                    'direction': opp.direction,
                    'spread_bps': spread_bps,
                    'size_usd': size,
                    'net_pnl': result['net_pnl'],
                    'gas': result['gas'],
                    'status': result['status'],
                })
                
                portfolio_values.append({
                    'day': day_idx,
                    'value': self.state.portfolio_value_usd,
                })
        
        # Calculate metrics
        metrics = self._calculate_metrics(trades, portfolio_values, initial_capital)
        
        if verbose:
            self._print_backtest_results(metrics, trades)
        
        return {
            'metrics': metrics,
            'trades': trades,
            'portfolio_values': portfolio_values,
            'config': {
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': initial_capital,
                'days': days,
            }
        }
    
    def _generate_synthetic_spreads(self, days: int) -> List[List[Dict]]:
        """Generate realistic synthetic cross-chain spread data"""
        import random
        import numpy as np
        
        spreads_by_day = []
        
        # Parameters from config
        spread_vol = self.config.get('backtest', {}).get('synthetic_spread_vol', 0.001)
        spread_mean = self.config.get('backtest', {}).get('synthetic_spread_mean', 0.0002)
        events_per_year = self.config.get('backtest', {}).get('cross_chain_events_per_year', 150)
        
        events_per_day = events_per_year / 365
        
        for day in range(days):
            day_spreads = []
            
            # Normal spreads (0-10 bps)
            if random.random() < 0.7:  # 70% no trade
                spread = abs(random.gauss(spread_mean, spread_vol))
                if spread < 0.001:  # Cap at 10bps
                    for pair, chain_pair in zip(self.pairs, self.chain_pairs):
                        day_spreads.append({
                            'pair': pair,
                            'spread_bps': spread * 10000,
                            'chain_a': chain_pair[0],
                            'chain_b': chain_pair[1],
                        })
            
            # Large spread events
            if random.random() < events_per_day / len(self.pairs):
                # Market event creates large spread
                event_spread = abs(random.gauss(0.005, 0.003))  # 30-80bps
                for pair, chain_pair in zip(self.pairs, self.chain_pairs):
                    day_spreads.append({
                        'pair': pair,
                        'spread_bps': event_spread * 10000,
                        'chain_a': chain_pair[0],
                        'chain_b': chain_pair[1],
                    })
            
            spreads_by_day.append(day_spreads)
        
        return spreads_by_day
    
    def _simulate_opportunity(
        self,
        pair: str,
        chain_a: str,
        chain_b: str,
        spread_bps: float,
    ) -> ArbitrageOpportunity:
        """Simulate an arbitrage opportunity from spread data"""
        import random
        
        base = pair.split("/")[0]
        quote = pair.split("/")[1]
        base_price = 1800 if base == "WETH" else (62000 if base == "WBTC" else 1.0)
        
        gross_profit = 100_000 * (spread_bps / 10000)
        total_cost = 100_000 * 0.003  # ~30bps all-in
        net_profit = gross_profit - total_cost
        
        direction = "A_TO_B" if random.random() > 0.5 else "B_TO_A"
        
        return ArbitrageOpportunity(
            opportunity_id=f"BT-{random.randint(100000, 999999)}",
            opportunity_type=OpportunityType.DIRECT_ARB,
            buy_chain=chain_a if direction == "A_TO_B" else chain_b,
            sell_chain=chain_b if direction == "A_TO_B" else chain_a,
            buy_dex="uniswap_v3",
            sell_dex="uniswap_v3",
            pair=pair,
            direction=direction,
            buy_price=base_price,
            sell_price=base_price * (1 + spread_bps / 10000),
            spread_bps=spread_bps,
            max_trade_size_usd=500_000,
            optimal_trade_size_usd=100_000,
            min_trade_size_usd=5000,
            buy_gas_usd=1.0,
            sell_gas_usd=1.0,
            bridge_fee_usd=8.0,
            slippage_usd=5.0,
            total_cost_usd=15.0,
            gross_profit_usd=gross_profit,
            net_profit_usd=net_profit,
            net_profit_bps=net_profit / 100_000 * 10000,
            is_profitable=net_profit > 0,
            confidence_score=0.75,
            detected_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=5),
            estimated_duration_secs=120,
            bridge_risk_score=5.0,
            mev_risk_score=5.0,
            finality_risk=2.0,
            spread_zscore=2.0,
            spread_percentile=90.0,
        )
    
    def _simulate_execution(self, opp: ArbitrageOpportunity, size: float) -> Dict:
        """Simulate trade execution outcome"""
        import random
        
        # Success rate based on confidence
        success_rate = 0.80 + opp.confidence_score * 0.15
        
        if random.random() < success_rate:
            # Success
            slippage_adj = random.uniform(0.995, 1.005)
            gross_pnl = size * (abs(opp.spread_bps) / 10000) * slippage_adj
            gas = opp.buy_gas_usd + opp.sell_gas_usd + opp.bridge_fee_usd
            net_pnl = gross_pnl - gas
            status = "success"
        else:
            # Failure
            gas = (opp.buy_gas_usd + opp.sell_gas_usd) * 0.5  # Partial gas spent
            net_pnl = -gas
            status = "failed"
        
        return {
            'net_pnl': net_pnl,
            'gas': gas,
            'status': status,
        }
    
    def _calculate_metrics(
        self,
        trades: List[Dict],
        portfolio_values: List[Dict],
        initial_capital: float,
    ) -> Dict:
        """Calculate backtest performance metrics"""
        import numpy as np
        
        if not trades:
            return {
                'total_return': 0,
                'sharpe': 0,
                'sortino': 0,
                'max_drawdown': 0,
                'win_rate': 0,
                'total_trades': 0,
            }
        
        pnls = [t['net_pnl'] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        # Returns
        final_value = portfolio_values[-1]['value'] if portfolio_values else initial_capital
        total_return = (final_value - initial_capital) / initial_capital
        
        # Daily returns
        if len(portfolio_values) > 1:
            values = [pv['value'] for pv in portfolio_values]
            daily_returns = np.diff(values) / values[:-1]
            daily_returns = daily_returns[np.isfinite(daily_returns)]
            
            if len(daily_returns) > 0:
                sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252) if np.std(daily_returns) > 0 else 0
                downside = daily_returns[daily_returns < 0]
                sortino = (np.mean(daily_returns) / np.std(downside) * np.sqrt(252)) if len(downside) > 0 and np.std(downside) > 0 else 0
            else:
                sharpe = sortino = 0
        else:
            sharpe = sortino = 0
        
        # Max drawdown
        values = [pv['value'] for pv in portfolio_values]
        peak = values[0]
        max_dd = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
        
        return {
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'final_value': final_value,
            'sharpe': sharpe,
            'sortino': sortino,
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd * 100,
            'win_rate': len(wins) / len(pnls) if pnls else 0,
            'total_trades': len(trades),
            'successful_trades': len(wins),
            'failed_trades': len(losses),
            'avg_pnl': np.mean(pnls) if pnls else 0,
            'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) < 0 else float('inf'),
            'total_pnl': sum(pnls),
        }
    
    def _print_backtest_results(self, metrics: Dict, trades: List) -> None:
        """Print backtest results"""
        print("\n" + "="*60)
        print("CROSS-CHAIN MEV ARBITRAGE - BACKTEST RESULTS")
        print("="*60)
        print(f"Total Trades:        {metrics['total_trades']}")
        print(f"Successful Trades:   {metrics['successful_trades']}")
        print(f"Failed Trades:       {metrics['failed_trades']}")
        print(f"Win Rate:            {metrics['win_rate']:.1%}")
        print(f"Total PnL:           ${metrics['total_pnl']:,.2f}")
        print(f"Total Return:        {metrics['total_return_pct']:.2f}%")
        print(f"Sharpe Ratio:        {metrics['sharpe']:.2f}")
        print(f"Sortino Ratio:       {metrics['sortino']:.2f}")
        print(f"Max Drawdown:        {metrics['max_drawdown_pct']:.2f}%")
        print(f"Profit Factor:       {metrics['profit_factor']:.2f}")
        print(f"Avg PnL/Trade:       ${metrics['avg_pnl']:,.2f}")
        print("="*60 + "\n")
    
    # ─── Utility Methods ──────────────────────────────────────────────────────
    
    def _in_cooldown(self, pair: str, chain_a: str, chain_b: str) -> bool:
        """Check cooldown for a pair/chain combination"""
        key = f"{pair}_{chain_a}_{chain_b}"
        return hasattr(self, '_cooldowns') and key in self._cooldowns
    
    def _set_cooldown(self, pair: str, chain_a: str, chain_b: str) -> None:
        """Set cooldown for a pair/chain combination"""
        if not hasattr(self, '_cooldowns'):
            self._cooldowns = {}
        key = f"{pair}_{chain_a}_{chain_b}"
        self._cooldowns[key] = datetime.now()
    
    def get_state(self) -> StrategyState:
        """Get current strategy state"""
        return self.state
    
    def get_metrics(self) -> RiskMetrics:
        """Get risk metrics"""
        return self.risk_manager.get_metrics()
    
    def get_recent_performance(self, n: int = 20) -> Dict:
        """Get recent performance stats"""
        return self.risk_manager.get_recent_performance(n)
    
    def export_state(self, path: str) -> None:
        """Export strategy state to JSON"""
        state = {
            'timestamp': datetime.now().isoformat(),
            'state': {
                'portfolio_value_usd': self.state.portfolio_value_usd,
                'total_pnl_usd': self.state.total_pnl_usd,
                'total_trades': self.state.total_trades,
                'win_rate': self.state.win_rate,
            },
            'metrics': {
                'daily_trades': self.risk_manager.get_metrics().daily_trades,
                'concurrent_trades': self.risk_manager.get_metrics().concurrent_trades,
            }
        }
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

async def main():
    """Main entry point for the strategy"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Cross-Chain MEV Arbitrage Strategy')
    parser.add_argument('--mode', choices=['live', 'backtest'], default='backtest')
    parser.add_argument('--capital', type=float, default=100_000)
    parser.add_argument('--start', default='2021-01-01')
    parser.add_argument('--end', default='2026-04-01')
    parser.add_argument('--config', default='config/params.yaml')
    
    args = parser.parse_args()
    
    strategy = CrossChainMEVStrategy(
        config_path=args.config,
        initial_capital=args.capital,
    )
    
    if args.mode == 'backtest':
        await strategy.run_backtest(
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
        )
    else:
        await strategy.start()
        await asyncio.Event().wait()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
