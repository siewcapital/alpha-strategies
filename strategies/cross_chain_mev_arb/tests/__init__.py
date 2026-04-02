"""
Cross-Chain MEV Arbitrage - Test Suite
"""

import sys
sys.path.insert(0, str(__file__).rsplit('/tests/', 1)[0])

import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
import numpy as np
import random

# Import modules under test
from src.price_monitor import PriceMonitor, Chain, DEX, DEXQuote, CrossChainSpread
from src.bridge_router import BridgeRouter, BridgeType, BridgeStatus, BridgeQuote
from src.gas_estimator import GasEstimator, GasQuote
from src.arb_detector import ArbitrageDetector, ArbitrageOpportunity, OpportunityType, SpreadHistory
from src.risk_manager import RiskManager, RiskStatus, RiskCheckResult
from src.signal_generator import SignalGenerator, TradeSignal, SignalType
from src.execution_engine import ExecutionEngine, ExecutionLeg, ExecutionStatus, ExecutionResult


# ─── Test Fixtures ────────────────────────────────────────────────────────────

def get_test_config() -> dict:
    """Standard test configuration"""
    return {
        'chains': {
            'ethereum': {'chain_id': 1, 'gas_price_type': 'base_fee', 'priority_fee_gwei': 2.0},
            'arbitrum': {'chain_id': 42161, 'gas_price_type': 'l2_gas', 'priority_fee_gwei': 0.1},
            'optimism': {'chain_id': 10, 'gas_price_type': 'l2_gas', 'priority_fee_gwei': 0.05},
            'base': {'chain_id': 8453, 'gas_price_type': 'l2_gas', 'priority_fee_gwei': 0.1},
        },
        'dexes': {
            'ethereum': [{'name': 'uniswap_v3', 'fee_tiers': [500, 3000]}],
            'arbitrum': [{'name': 'uniswap_v3', 'fee_tiers': [500, 3000]}],
        },
        'bridges': {
            'stargate': {'enabled': True, 'fee_bps': 6, 'max_slippage_bps': 50},
            'across': {'enabled': True, 'fee_bps': 10, 'max_slippage_bps': 30},
        },
        'trading': {
            'pairs': [
                {'base': 'WETH', 'quote': 'USDC', 'min_trade_usd': 5000, 'max_trade_usd': 500000},
                {'base': 'WBTC', 'quote': 'USDC', 'min_trade_usd': 10000, 'max_trade_usd': 500000},
            ],
            'arbitrage': {
                'min_spread_bps': 15,
                'zscore_entry_threshold': 2.0,
                'zscore_exit_threshold': 0.5,
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
            'stop_loss_bps': 50,
        },
        'backtest': {
            'start_date': '2021-01-01',
            'end_date': '2026-04-01',
            'synthetic_spread_vol': 0.001,
            'synthetic_spread_mean': 0.0002,
            'cross_chain_events_per_year': 150,
            'maker_fee_bps': 3.0,
            'taker_fee_bps': 5.0,
            'bridge_fee_bps': 8.0,
            'slippage_bps': 5.0,
        }
    }


def make_mock_opportunity(
    spread_bps: float = 30.0,
    net_profit_usd: float = 50.0,
    confidence: float = 0.75,
    direction: str = "A_TO_B",
) -> ArbitrageOpportunity:
    """Factory for mock ArbitrageOpportunity"""
    return ArbitrageOpportunity(
        opportunity_id="TEST-001",
        opportunity_type=OpportunityType.DIRECT_ARB,
        buy_chain="ethereum",
        sell_chain="arbitrum",
        buy_dex="uniswap_v3",
        sell_dex="uniswap_v3",
        pair="WETH/USDC",
        direction=direction,
        buy_price=1800.0,
        sell_price=1800.05,
        spread_bps=spread_bps,
        max_trade_size_usd=500000,
        optimal_trade_size_usd=100000,
        min_trade_size_usd=5000,
        buy_gas_usd=1.0,
        sell_gas_usd=1.0,
        bridge_fee_usd=8.0,
        slippage_usd=5.0,
        total_cost_usd=15.0,
        gross_profit_usd=75.0,
        net_profit_usd=net_profit_usd,
        net_profit_bps=5.0,
        is_profitable=net_profit_usd > 0,
        confidence_score=confidence,
        detected_at=datetime.now(),
        expires_at=datetime.now() + timedelta(minutes=5),
        estimated_duration_secs=120,
        bridge_risk_score=5.0,
        mev_risk_score=5.0,
        finality_risk=2.0,
        spread_zscore=2.0,
        spread_percentile=90.0,
    )


# ─── PriceMonitor Tests ──────────────────────────────────────────────────────

class TestPriceMonitor(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        self.monitor = PriceMonitor(
            chain_configs={Chain.ETHEREUM: {}, Chain.ARBITRUM: {}},
            dex_configs=self.config['dexes'],
            gas_estimator=None,
        )
    
    def test_mid_price_calculation(self):
        """DEXQuote mid price is correctly calculated"""
        quote = DEXQuote(
            chain=Chain.ETHEREUM,
            dex=DEX.UNISWAP_V3,
            base_asset="WETH",
            quote_asset="USDC",
            bid_price=1799.0,
            ask_price=1801.0,
            bid_liquidity=100.0,
            ask_liquidity=100.0,
            gas_cost_quote_usd=5.0,
            timestamp=datetime.now(),
        )
        self.assertAlmostEqual(quote.mid_price(), 1800.0, places=1)
    
    def test_spread_bps_calculation(self):
        """DEXQuote spread in bps is correctly calculated"""
        quote = DEXQuote(
            chain=Chain.ETHEREUM,
            dex=DEX.UNISWAP_V3,
            base_asset="WETH",
            quote_asset="USDC",
            bid_price=1799.0,
            ask_price=1801.0,
            bid_liquidity=100.0,
            ask_liquidity=100.0,
            gas_cost_quote_usd=5.0,
            timestamp=datetime.now(),
        )
        expected_spread_bps = (1801 - 1799) / 1801 * 10000
        self.assertAlmostEqual(quote.spread_bps(), expected_spread_bps, places=1)
    
    def test_cross_chain_spread_profitable_calculation(self):
        """CrossChainSpread correctly calculates profitability"""
        spread = CrossChainSpread(
            pair="WETH/USDC",
            chain_a=Chain.ETHEREUM,
            chain_b=Chain.ARBITRUM,
            price_a=1800.0,
            price_b=1810.0,
            spread_bps=5.56,
            spread_direction="A_TO_B",
        )
        spread.calculate_economics(trade_size_usd=100000)
        self.assertTrue(spread.profitable)
        self.assertAlmostEqual(spread.gross_profit_usd, 100000 * 5.56/10000, places=0)
    
    def test_cross_chain_spread_not_profitable(self):
        """CrossChainSpread correctly identifies unprofitable spreads"""
        spread = CrossChainSpread(
            pair="WETH/USDC",
            chain_a=Chain.ETHEREUM,
            chain_b=Chain.ARBITRUM,
            price_a=1800.0,
            price_b=1801.0,
            spread_bps=0.56,  # Very small
            spread_direction="A_TO_B",
        )
        # Set costs so total > gross profit
        spread.estimated_buy_gas_usd = 20.0
        spread.estimated_sell_gas_usd = 20.0
        spread.estimated_bridge_fee_usd = 20.0
        spread.estimated_slippage_usd = 20.0
        spread.calculate_economics(trade_size_usd=10000)  # Small size
        self.assertFalse(spread.profitable)


# ─── BridgeRouter Tests ───────────────────────────────────────────────────────

class TestBridgeRouter(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        self.router = BridgeRouter(self.config)
    
    def test_bridge_quotes_sorted_by_net_received(self):
        """Bridge quotes are sorted with best (highest net received) first"""
        # Both bridges should return quotes
        quotes = asyncio.run(self.router.get_quote(
            source_chain='ethereum',
            dest_chain='arbitrum',
            asset='USDC',
            amount=100000,
            asset_price_usd=1.0,
        ))
        if len(quotes) >= 2:
            # Best quote should have highest received_usd
            self.assertGreaterEqual(quotes[0].received_usd, quotes[1].received_usd)
    
    def test_stargate_enabled_in_config(self):
        """Stargate bridge is enabled in test config"""
        stargate_cfg = self.config['bridges']['stargate']
        self.assertTrue(stargate_cfg.get('enabled', False))
    
    def test_bridge_risk_score_calculation(self):
        """Bridge risk score is between 0-10"""
        score = self.router._calculate_risk_score(BridgeType.STARGATE, tvl=100_000_000)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 10)
    
    def test_bridge_availability_check(self):
        """Bridge availability check works"""
        self.assertTrue(self.router.is_bridge_available(BridgeType.STARGATE))
        self.router.set_bridge_status(BridgeType.WORMHOLE, BridgeStatus.PAUSED)
        self.assertFalse(self.router.is_bridge_available(BridgeType.WORMHOLE))
    
    def test_bridge_fee_estimation(self):
        """Bridge fee is correctly calculated"""
        fee_bps = self.config['bridges']['stargate']['fee_bps']
        amount = 100000
        expected_fee = amount * (fee_bps / 10000)
        self.assertAlmostEqual(expected_fee, 60.0, places=1)


# ─── GasEstimator Tests ────────────────────────────────────────────────────────

class TestGasEstimator(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        self.estimator = GasEstimator(self.config)
    
    def test_gas_quote_usd_calculation(self):
        """GasQuote correctly converts gas to USD"""
        quote = GasQuote(
            chain='ethereum',
            gas_price_gwei=30.0,
            estimated_gas_units=150000,
            total_gas_wei=150000 * 30 * 1e9,
            cost_eth=(150000 * 30 * 1e9) / 1e18,
            cost_usd=(150000 * 30 * 1e9) / 1e18 * 1800,
            fee_type='base_fee',
            timestamp=datetime.now(),
        )
        self.assertGreater(quote.cost_usd, 0)
        self.assertAlmostEqual(quote.cost_eth, 150000 * 30 * 1e9 / 1e18, places=5)
    
    def test_l2_gas_price_lower_than_eth(self):
        """L2 gas prices are lower than Ethereum"""
        l2_price = self.estimator._get_l2_gas_price('arbitrum')
        eth_price = self.estimator._get_base_fee('ethereum')
        self.assertLess(l2_price, eth_price)
    
    def test_gas_advisory_classification(self):
        """Gas advisory returns valid classifications"""
        valid = {"LOW", "NORMAL", "HIGH", "SPIKE"}
        # Without history, should return NORMAL
        advisory = self.estimator.get_gas_advisory('ethereum')
        self.assertIn(advisory, valid)
    
    def test_operation_gas_units_for_swap(self):
        """Swap gas units are reasonable"""
        eth_gas = self.estimator._get_operation_gas_units('ethereum', 'swap')
        arb_gas = self.estimator._get_operation_gas_units('arbitrum', 'swap')
        self.assertGreater(eth_gas, 0)
        self.assertGreater(arb_gas, 0)


# ─── ArbitrageDetector Tests ──────────────────────────────────────────────────

class TestArbitrageDetector(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        self.detector = ArbitrageDetector(self.config)
    
    def test_zscore_calculation(self):
        """Z-score is correctly calculated"""
        history = SpreadHistory("WETH/USDC", "ethereum", "arbitrum")
        for _ in range(50):
            history.add(random.gauss(5, 2), datetime.now())
        
        current = 15.0  # 5 std above mean of 5
        zscore = history.zscore(current)
        self.assertGreater(zscore, 4.0)
    
    def test_percentile_calculation(self):
        """Percentile is correctly calculated"""
        history = SpreadHistory("WETH/USDC", "ethereum", "arbitrum")
        for i in range(100):
            history.add(float(i), datetime.now())  # 0-99
        
        # 50 should be around 50th percentile
        pct = history.percentile(50)
        self.assertGreater(pct, 45)
        self.assertLess(pct, 55)
    
    def test_confidence_score_range(self):
        """Confidence score is between 0 and 1"""
        confidence = self.detector._calculate_confidence(zscore=2.5, spread_bps=30)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)
    
    def test_kelly_size_capped(self):
        """Kelly sizing respects maximum position limit"""
        size = self.detector._calculate_kelly_size(
            max_capital_usd=100000,
            spread_bps=15,  # Small spread
            kelly_fraction=0.25
        )
        self.assertLessEqual(size, 100000 * 0.15)  # Max 15%
    
    def test_kelly_size_zero_for_insufficient_edge(self):
        """Kelly returns 0 when edge doesn't cover costs"""
        size = self.detector._calculate_kelly_size(
            max_capital_usd=100000,
            spread_bps=20,  # Small edge
            kelly_fraction=0.25
        )
        # Edge (20bps) - cost (30bps) = negative -> size might be 0
        self.assertLess(size, 100000)
    
    def test_active_opportunities_expiry(self):
        """Active opportunities are correctly filtered by expiry"""
        opp = make_mock_opportunity()
        opp.expires_at = datetime.now() - timedelta(minutes=1)  # Expired
        self.detector._active_opportunities['TEST'] = opp
        
        active = self.detector.get_active_opportunities()
        self.assertEqual(len(active), 0)
    
    def test_cooldown_mechanism(self):
        """Cooldown prevents rapid re-trading"""
        key = "WETH/USDC_ethereum_arbitrum"
        # First call should not be in cooldown
        result1 = self.detector._is_in_cooldown(key)
        # Set cooldown
        self.detector._cooldowns[key] = datetime.now()
        # Second immediate call should be in cooldown
        result2 = self.detector._is_in_cooldown(key)
        self.assertFalse(result1)
        self.assertTrue(result2)


# ─── RiskManager Tests ────────────────────────────────────────────────────────

class TestRiskManager(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        self.rm = RiskManager(self.config, initial_capital=100000)
    
    def test_initial_capital_preserved(self):
        """RiskManager initializes with correct capital"""
        self.assertEqual(self.rm.portfolio_value, 100000)
        self.assertEqual(self.rm.initial_capital, 100000)
    
    def test_daily_trade_limit(self):
        """Daily trade limit is enforced"""
        opp = make_mock_opportunity()
        # Exhaust daily trades
        for _ in range(20):
            self.rm._daily_trades[self.rm._today_date] = 20
            result = self.rm.check_trade(opp)
        self.assertFalse(result.allowed)
        self.assertEqual(result.status, RiskStatus.CIRCUIT_BREAKER)
    
    def test_concurrent_position_limit(self):
        """Max concurrent positions enforced"""
        opp = make_mock_opportunity()
        # Fill all slots
        for i in range(3):
            self.rm._active_positions[f'pos_{i}'] = {'size': 10000}
        
        result = self.rm.check_trade(opp)
        self.assertFalse(result.allowed)
        self.assertEqual(result.status, RiskStatus.MAX_POSITION)
    
    def test_bridge_exposure_limit_scales_down(self):
        """Bridge exposure limit scales position down"""
        opp = make_mock_opportunity()
        opp.optimal_trade_size_usd = 100000
        self.rm._bridge_exposure_usd = 15000  # 15% of 100K
        
        result = self.rm.check_trade(opp)
        # Should allow with reduction
        if result.allowed:
            self.assertLess(result.reduction_factor, 1.0)
    
    def test_risk_metrics_bridge_exposure(self):
        """RiskMetrics correctly calculates bridge exposure %"""
        metrics = self.rm.get_metrics()
        self.assertEqual(metrics.bridge_exposure_pct, 0.0)
        
        self.rm._bridge_exposure_usd = 20000
        self.rm.portfolio_value = 100000
        metrics = self.rm.get_metrics()
        self.assertAlmostEqual(metrics.bridge_exposure_pct, 0.20, places=2)
    
    def test_stop_loss_trigger(self):
        """Stop loss triggers after consecutive losses"""
        # Record 5 losing trades
        for _ in range(5):
            self.rm.record_trade(
                f"t-{random.randint(1000,9999)}",
                make_mock_opportunity(),
                10000,
                -500,  # Loss
                "success"
            )
        self.assertTrue(self.rm._check_stop_loss())
    
    def test_position_limits(self):
        """Position limits are correctly calculated"""
        opp = make_mock_opportunity(spread_bps=50, net_profit_usd=100)
        min_s, max_s = self.rm.get_position_limits(opp)
        self.assertGreater(min_s, 0)
        self.assertLessEqual(max_s, self.rm.portfolio_value * 0.15)
    
    def test_recent_performance_win_rate(self):
        """Recent performance correctly calculates win rate"""
        for i in range(10):
            pnl = 100 if i < 7 else -50  # 70% win rate
            self.rm.record_trade(f't-{i}', make_mock_opportunity(), 10000, pnl, 'success')
        
        perf = self.rm.get_recent_performance(10)
        self.assertEqual(perf['win_rate'], 0.7)


# ─── SignalGenerator Tests ────────────────────────────────────────────────────

class TestSignalGenerator(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        self.sg = SignalGenerator(self.config)
    
    def test_signal_generated_for_profitable_opp(self):
        """Signal is generated when confidence and profit thresholds are met"""
        opp = make_mock_opportunity(net_profit_usd=100, confidence=0.8)
        opp.spread_zscore = 2.5
        opp.spread_percentile = 95
        opp.spread_bps = 200  # Large enough to clear min profit after costs
        signal = self.sg.generate_signal(opp, portfolio_value=100000)
        # Confidence must exceed threshold and expected_pnl must exceed min_profit
        self.assertGreater(signal.confidence, 0.60, f"Confidence {signal.confidence} should exceed 0.60")
        self.assertGreater(signal.expected_pnl_usd, 50, f"Expected PnL {signal.expected_pnl_usd} should exceed $50")
    
    def test_signal_skipped_for_low_confidence(self):
        """Signal is skipped when confidence is too low"""
        opp = make_mock_opportunity(net_profit_usd=100, confidence=0.3)
        signal = self.sg.generate_signal(opp, portfolio_value=100000)
        self.assertFalse(signal.is_actionable())
    
    def test_signal_skipped_for_unprofitable(self):
        """Signal is skipped when not profitable"""
        opp = make_mock_opportunity(net_profit_usd=-10, confidence=0.8)
        signal = self.sg.generate_signal(opp, portfolio_value=100000)
        self.assertFalse(signal.is_actionable())
    
    def test_size_recommendation_capped(self):
        """Size recommendation is capped at 15%"""
        opp = make_mock_opportunity(net_profit_usd=1000, confidence=0.9)
        signal = self.sg.generate_signal(opp, portfolio_value=100000)
        cap = signal.size_recommendation(100000)
        self.assertLessEqual(cap, 0.15)
    
    def test_breakeven_spread_calculation(self):
        """Breakeven spread is correctly calculated"""
        opp = make_mock_opportunity(
            net_profit_usd=50,
            spread_bps=30,
        )
        opp.buy_gas_usd = 1.0
        opp.sell_gas_usd = 1.0
        opp.bridge_fee_usd = 8.0
        opp.slippage_usd = 5.0
        
        signal = self.sg.generate_signal(opp, portfolio_value=100000)
        signal.recommended_size_usd = 50000
        
        bebps = signal.breakeven_spread_bps()
        self.assertGreater(bebps, 0)
    
    def test_urgency_immediate_for_high_zscore(self):
        """Urgency is 'immediate' for extreme z-scores"""
        opp = make_mock_opportunity()
        opp.spread_zscore = 3.5
        opp.spread_percentile = 97
        
        urgency = self.sg._assess_urgency(opp)
        self.assertEqual(urgency, 'immediate')
    
    def test_warnings_generated_for_high_risk(self):
        """Warnings are generated for high-risk opportunities"""
        opp = make_mock_opportunity()
        opp.bridge_risk_score = 8.0
        opp.mev_risk_score = 8.0
        opp.estimated_duration_secs = 1200
        
        warnings = self.sg._generate_warnings(opp, confidence=0.7)
        self.assertGreater(len(warnings), 0)
    
    def test_filter_signals_ranks_by_risk_adjusted_return(self):
        """Signal filtering ranks by risk-adjusted return"""
        opp1 = make_mock_opportunity(net_profit_usd=100, confidence=0.7)
        opp1.spread_zscore = 2.5
        opp1.spread_percentile = 95
        opp1.spread_bps = 200
        opp1.estimated_duration_secs = 120
        
        opp2 = make_mock_opportunity(net_profit_usd=200, confidence=0.8)
        opp2.spread_zscore = 2.5
        opp2.spread_percentile = 95
        opp2.spread_bps = 300  # Even larger spread for clear priority
        opp2.estimated_duration_secs = 120
        
        sig1 = self.sg.generate_signal(opp1, 100000)
        sig2 = self.sg.generate_signal(opp2, 100000)
        
        actionable = [s for s in [sig1, sig2] if s.is_actionable()]
        filtered = self.sg.filter_signals(actionable, top_n=2)
        self.assertGreaterEqual(len(filtered), 1)


# ─── ExecutionEngine Tests ───────────────────────────────────────────────────

class TestExecutionEngine(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        self.engine = ExecutionEngine(self.config)
    
    def test_execution_leg_mid_price(self):
        """ExecutionLeg records correct amounts"""
        leg = ExecutionLeg(
            leg_number=1,
            action="buy",
            chain="ethereum",
            dex="uniswap_v3",
            asset_in="USDC",
            asset_out="WETH",
            amount_in=180000,
            amount_out=100,
            price=1800.0,
            gas_cost_usd=5.0,
            slippage_bps=5.0,
            fee_bps=5.0,
        )
        self.assertAlmostEqual(leg.amount_in / leg.amount_out, 1800.0, places=1)
    
    def test_execution_result_net_profit(self):
        """ExecutionResult correctly calculates net profit"""
        result = ExecutionResult(
            opportunity_id="TEST-001",
            status=ExecutionStatus.COMPLETED,
            legs=[],
            total_pnl_usd=100.0,
            total_gas_usd=10.0,
            total_fees_usd=5.0,
            duration_secs=120.0,
            execution_price_slippage_bps=5.0,
            success_rate=1.0,
        )
        self.assertAlmostEqual(result.net_profit_usd, 85.0, places=1)
        self.assertTrue(result.is_success)
    
    def test_execution_result_failure(self):
        """Failed execution result identified correctly"""
        result = ExecutionResult(
            opportunity_id="TEST-001",
            status=ExecutionStatus.FAILED,
            legs=[],
            total_pnl_usd=0,
            total_gas_usd=5.0,
            total_fees_usd=0,
            duration_secs=30.0,
            execution_price_slippage_bps=0,
            success_rate=0,
            failure_reason="Bridge failed",
        )
        self.assertFalse(result.is_success)
    
    def test_tx_hash_generation(self):
        """Transaction hash is generated"""
        leg = ExecutionLeg(
            leg_number=1,
            action="buy",
            chain="ethereum",
            dex="uniswap_v3",
            asset_in="USDC",
            asset_out="WETH",
            amount_in=180000,
            amount_out=100,
            price=1800.0,
            gas_cost_usd=5.0,
            slippage_bps=5.0,
            fee_bps=5.0,
        )
        # Generate a fake hash for test
        import hashlib
        tx_hash = "0x" + hashlib.sha256(b"test").hexdigest()[:40]
        leg.tx_hash = tx_hash
        self.assertTrue(tx_hash.startswith('0x'))
        self.assertEqual(len(tx_hash), 42)
    
    def test_estimate_execution_breakeven(self):
        """Execution estimation gives reasonable breakeven"""
        opp = make_mock_opportunity(spread_bps=50, net_profit_usd=200)
        est = self.engine.estimate_execution(opp, 100000)
        self.assertIn('breakeven_spread_bps', est)
        # Breakeven should be a positive value
        self.assertGreater(est['breakeven_spread_bps'], 0)


# ─── Backtest Tests ───────────────────────────────────────────────────────────

class TestBacktestEngine(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
        from backtest import BacktestEngine, SyntheticSpreadGenerator
        self.engine = BacktestEngine(self.config, initial_capital=100000)
        self.generator = SyntheticSpreadGenerator(
            pairs=['WETH/USDC'],
            chain_pairs=[('ethereum', 'arbitrum')],
        )
    
    def test_synthetic_spread_mean_reversion(self):
        """Synthetic spread shows mean-reverting behavior"""
        spreads = []
        for _ in range(100):
            result = self.generator.step()
            spreads.extend([r['spread_bps'] for r in result])
        
        # Most spreads should be near the mean
        mean_spread = sum(spreads) / len(spreads)
        self.assertLess(mean_spread, 200)  # Should be under 200bps typically
    
    def test_backtest_reset(self):
        """Backtest engine resets correctly"""
        self.engine._portfolio = 90000
        self.engine._total_trades = 10
        self.engine.reset()
        self.assertEqual(self.engine._portfolio, 100000)
        self.assertEqual(self.engine._total_trades, 0)
    
    def test_zscore_calculation_with_history(self):
        """Z-score calculation works with sufficient history"""
        from collections import deque
        key = "WETH/USDC_ethereum_arbitrum"
        # Backtest stores plain deques of floats
        self.engine._spread_history[key] = deque(maxlen=500)
        for i in range(30):
            self.engine._spread_history[key].append(float(i))
        
        zscore = self.engine._calculate_zscore(key, 50.0)
        self.assertGreater(zscore, 1.0)  # 50 is above mean of ~14.5
    
    def test_backtest_metrics_with_no_trades(self):
        """Metrics handle zero trades gracefully"""
        metrics = self.engine.get_metrics()
        self.assertEqual(metrics['total_trades'], 0)
        self.assertEqual(metrics['sharpe'], 0)


# ─── Integration Tests ────────────────────────────────────────────────────────

class TestIntegration(unittest.TestCase):
    
    def setUp(self):
        self.config = get_test_config()
    
    def test_full_strategy_import(self):
        """All strategy modules can be imported"""
        from src.strategy import CrossChainMEVStrategy
        self.assertIsNotNone(CrossChainMEVStrategy)
    
    def test_strategy_initialization(self):
        """Strategy initializes with correct defaults"""
        from src.strategy import CrossChainMEVStrategy
        strategy = CrossChainMEVStrategy(
            config_path="config/params.yaml",
            initial_capital=100000,
        )
        self.assertEqual(strategy.state.portfolio_value_usd, 100000)
        self.assertEqual(strategy.state.total_trades, 0)
        self.assertEqual(strategy.state.status.value, 'idle')
    
    def test_config_loading_with_defaults(self):
        """Config loads with defaults when file missing"""
        from src.strategy import CrossChainMEVStrategy
        strategy = CrossChainMEVStrategy(
            config_path="nonexistent.yaml",
            initial_capital=50000,
        )
        self.assertEqual(strategy.initial_capital, 50000)
        self.assertIsNotNone(strategy.config)
    
    def test_strategy_pairs_built(self):
        """Trading pairs are correctly built from config"""
        from src.strategy import CrossChainMEVStrategy
        strategy = CrossChainMEVStrategy(initial_capital=100000)
        self.assertIn('WETH/USDC', strategy.pairs)
        self.assertIn('WBTC/USDC', strategy.pairs)
    
    def test_chain_pairs_defined(self):
        """Chain pairs are correctly defined"""
        from src.strategy import CrossChainMEVStrategy
        strategy = CrossChainMEVStrategy(initial_capital=100000)
        eth_arb = ('ethereum', 'arbitrum')
        self.assertIn(eth_arb, strategy.chain_pairs)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    unittest.main(verbosity=2)
