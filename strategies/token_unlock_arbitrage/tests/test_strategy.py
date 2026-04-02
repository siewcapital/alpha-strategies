"""
Unit Tests for Token Unlock Arbitrage Strategy
==============================================

Run with: python -m pytest tests/test_strategy.py -v
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strategy import (
    TokenUnlockStrategy,
    UnlockEvent,
    Trade,
    SignalType,
    PositionStatus
)
from risk_manager import RiskManager, RiskLimits, LiquidityFilter
from data_fetcher import CoinGeckoDataSource, DataAggregator


class TestUnlockEvent:
    """Test UnlockEvent dataclass."""
    
    def test_unlock_pct_calculation(self):
        """Test unlock percentage calculation."""
        unlock = UnlockEvent(
            token="SOL",
            unlock_date=datetime.now(),
            unlock_amount=10_000_000,
            circulating_supply=443_000_000
        )
        
        expected_pct = (10_000_000 / 443_000_000) * 100
        assert abs(unlock.unlock_pct - expected_pct) < 0.001
    
    def test_significant_threshold(self):
        """Test significance threshold (1% of supply)."""
        small_unlock = UnlockEvent(
            token="TEST",
            unlock_date=datetime.now(),
            unlock_amount=500_000,
            circulating_supply=100_000_000
        )
        assert not small_unlock.is_significant  # 0.5% < 1%
        
        large_unlock = UnlockEvent(
            token="TEST",
            unlock_date=datetime.now(),
            unlock_amount=2_000_000,
            circulating_supply=100_000_000
        )
        assert large_unlock.is_significant  # 2% > 1%
    
    def test_impact_score(self):
        """Test impact score calculation."""
        unlock = UnlockEvent(
            token="SOL",
            unlock_date=datetime.now(),
            unlock_amount=4_430_000,  # 1% of supply
            circulating_supply=443_000_000
        )
        
        # Research: 1% unlock ≈ 0.3% price drop
        assert unlock.impact_score < 0
        assert abs(unlock.impact_score + 0.3) < 0.01


class TestTrade:
    """Test Trade dataclass."""
    
    def test_short_trade_pnl(self):
        """Test PnL calculation for short trades."""
        trade = Trade(
            token="SOL",
            entry_date=datetime.now(),
            entry_price=100.0,
            position_size=10000,
            signal_type=SignalType.SHORT
        )
        
        # Price drops to $97 (3% gain for short)
        trade.close(exit_price=97.0, exit_date=datetime.now())
        
        expected_pnl = (100 - 97) * (10000 / 100)  # $300
        assert abs(trade.pnl - expected_pnl) < 0.01
        assert abs(trade.pnl_pct - 0.03) < 0.001
    
    def test_short_trade_loss(self):
        """Test loss calculation for short trades."""
        trade = Trade(
            token="SOL",
            entry_date=datetime.now(),
            entry_price=100.0,
            position_size=10000,
            signal_type=SignalType.SHORT
        )
        
        # Price rises to $102 (2% loss for short)
        trade.close(exit_price=102.0, exit_date=datetime.now())
        
        assert trade.pnl < 0
        assert abs(trade.pnl_pct + 0.02) < 0.001


class TestTokenUnlockStrategy:
    """Test main strategy logic."""
    
    @pytest.fixture
    def strategy(self):
        return TokenUnlockStrategy()
    
    @pytest.fixture
    def sample_unlocks(self):
        return [
            {
                'token': 'SOL',
                'unlock_date': (datetime.now() + timedelta(days=2)).isoformat(),
                'unlock_amount': 5_000_000,
                'circulating_supply': 443_000_000
            },
            {
                'token': 'AVAX',
                'unlock_date': (datetime.now() + timedelta(days=5)).isoformat(),
                'unlock_amount': 9_500_000,
                'circulating_supply': 377_000_000
            },
            {
                'token': 'SMALL',
                'unlock_date': (datetime.now() + timedelta(days=2)).isoformat(),
                'unlock_amount': 100_000,
                'circulating_supply': 100_000_000  # 0.1% - not significant
            }
        ]
    
    def test_load_unlocks(self, strategy, sample_unlocks):
        """Test loading unlock schedule."""
        strategy.load_unlock_schedule(sample_unlocks)
        
        assert len(strategy.unlocks) == 3
        assert sum(1 for u in strategy.unlocks if u.is_significant) == 2
    
    def test_entry_signal_generation(self, strategy, sample_unlocks):
        """Test entry signal generation."""
        strategy.load_unlock_schedule(sample_unlocks)
        
        # Today is 2 days before SOL unlock
        today = datetime.now()
        prices = {'SOL': 100.0, 'AVAX': 50.0, 'SMALL': 1.0}
        
        signals = strategy.generate_signals(today, prices)
        
        # Should generate SHORT signal for SOL (significant, 2 days before)
        assert len(signals) == 1
        assert signals[0].token == 'SOL'
        assert signals[0].signal_type == SignalType.SHORT
    
    def test_no_duplicate_positions(self, strategy, sample_unlocks):
        """Test no duplicate positions for same token."""
        strategy.load_unlock_schedule(sample_unlocks)
        
        today = datetime.now()
        prices = {'SOL': 100.0}
        
        # Generate signal first time
        signals = strategy.generate_signals(today, prices)
        assert len(signals) == 1
        
        # Try again - should not generate duplicate
        signals = strategy.generate_signals(today, prices)
        assert len(signals) == 0
    
    def test_exit_on_time(self, strategy, sample_unlocks):
        """Test time-based exit."""
        strategy.load_unlock_schedule(sample_unlocks)
        
        # Enter position
        entry_date = datetime.now()
        prices = {'SOL': 100.0}
        strategy.generate_signals(entry_date, prices)
        
        # Move to day 4 after unlock
        sol_unlock = datetime.fromisoformat(sample_unlocks[0]['unlock_date'])
        exit_date = sol_unlock + timedelta(days=4)
        prices = {'SOL': 97.0}  # 3% drop
        
        exits = strategy.check_exits(exit_date, prices)
        
        assert len(exits) == 1
        assert exits[0].pnl > 0  # Profitable short
    
    def test_stop_loss(self, strategy, sample_unlocks):
        """Test stop loss trigger."""
        strategy.load_unlock_schedule(sample_unlocks)
        
        entry_date = datetime.now()
        prices = {'SOL': 100.0}
        strategy.generate_signals(entry_date, prices)
        
        # Price rises 3% (past 2% stop loss)
        next_date = entry_date + timedelta(days=1)
        prices = {'SOL': 103.0}
        
        exits = strategy.check_exits(next_date, prices)
        
        assert len(exits) == 1
        assert exits[0].pnl < 0  # Loss
    
    def test_kelly_position_sizing(self, strategy):
        """Test Kelly criterion position sizing."""
        kelly = strategy._kelly_criterion(
            win_rate=0.65,
            avg_win=0.03,
            avg_loss=0.02
        )
        
        # Kelly = (0.65 * 1.5 - 0.35) / 1.5 = 0.4167
        # But capped at 50%
        assert 0 < kelly <= 0.5
    
    def test_metrics_calculation(self, strategy, sample_unlocks):
        """Test performance metrics calculation."""
        strategy.load_unlock_schedule(sample_unlocks)
        
        # Create some trades
        trade1 = Trade(
            token='SOL',
            entry_date=datetime.now(),
            entry_price=100.0,
            exit_price=97.0,
            exit_date=datetime.now() + timedelta(days=5),
            position_size=10000,
            signal_type=SignalType.SHORT,
            status=PositionStatus.CLOSED,
            pnl=300.0,
            pnl_pct=0.03
        )
        
        trade2 = Trade(
            token='AVAX',
            entry_date=datetime.now(),
            entry_price=50.0,
            exit_price=51.0,
            exit_date=datetime.now() + timedelta(days=5),
            position_size=5000,
            signal_type=SignalType.SHORT,
            status=PositionStatus.CLOSED,
            pnl=-100.0,
            pnl_pct=-0.02
        )
        
        strategy.trade_history = [trade1, trade2]
        strategy.portfolio_value = 100000 + 200
        
        metrics = strategy.get_metrics()
        
        assert metrics['total_trades'] == 2
        assert metrics['win_rate'] == 0.5
        assert metrics['profit_factor'] == 3.0  # 300/100


class TestRiskManager:
    """Test risk management."""
    
    @pytest.fixture
    def risk(self):
        return RiskManager(RiskLimits(
            max_position_pct=0.10,
            max_drawdown=0.20
        ))
    
    def test_position_size_cap(self, risk):
        """Test position size capping."""
        valid, size = risk.check_position_size(
            proposed_size=20000,
            portfolio_value=100000,
            existing_positions={}
        )
        
        assert valid
        assert size == 10000  # Capped at 10%
    
    def test_portfolio_heat_limit(self, risk):
        """Test portfolio heat limit."""
        valid, size = risk.check_position_size(
            proposed_size=10000,
            portfolio_value=100000,
            existing_positions={
                'SOL': 8000,
                'AVAX': 5000
            }
        )
        
        # 13k already deployed, 15k max heat, only 2k available
        assert size < 3000
    
    def test_drawdown_circuit_breaker(self, risk):
        """Test drawdown circuit breaker."""
        # Normal drawdown
        assert risk.check_drawdown(90000, 100000)  # 10% DD
        assert risk.status.value == 'green'
        
        # Critical drawdown
        assert not risk.check_drawdown(75000, 100000)  # 25% DD
        assert risk.status.value == 'red'
        assert risk.circuit_breaker_triggered is not None
    
    def test_circuit_breaker_cooldown(self, risk):
        """Test circuit breaker cooldown."""
        from datetime import datetime, timedelta
        
        # Trigger circuit breaker
        risk.check_drawdown(75000, 100000)
        assert not risk.can_trade()
        
        # Simulate cooldown passed
        risk.circuit_breaker_triggered = datetime.now() - timedelta(hours=25)
        assert risk.can_trade()


class TestLiquidityFilter:
    """Test liquidity filtering."""
    
    @pytest.fixture
    def filter(self):
        return LiquidityFilter(
            min_daily_volume=1_000_000,
            min_market_cap=50_000_000
        )
    
    def test_sufficient_liquidity(self, filter):
        """Test token with sufficient liquidity."""
        assert filter.is_tradeable(
            token='SOL',
            volume_24h=10_000_000,
            market_cap=50_000_000_000,
            position_size=5000
        )
    
    def test_insufficient_volume(self, filter):
        """Test token with low volume."""
        assert not filter.is_tradeable(
            token='LOWVOL',
            volume_24h=100_000,
            market_cap=100_000_000,
            position_size=5000
        )
    
    def test_position_too_large(self, filter):
        """Test position exceeding volume limit."""
        assert not filter.is_tradeable(
            token='SOL',
            volume_24h=1_000_000,
            market_cap=100_000_000,
            position_size=50000  # 5% of volume
        )


class TestDataSources:
    """Test data fetching components."""
    
    def test_coingecko_initialization(self):
        """Test CoinGecko data source initialization."""
        ds = CoinGeckoDataSource()
        assert ds.session is not None
    
    def test_data_aggregator(self):
        """Test data aggregator."""
        agg = DataAggregator()
        assert agg.coingecko is not None
        assert agg.tokenunlocks is not None


if __name__ == "__main__":
    # Run tests with pytest if available
    try:
        import pytest
        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not installed. Running basic assertions...")
        
        # Basic smoke tests
        strategy = TokenUnlockStrategy()
        unlock = UnlockEvent("SOL", datetime.now(), 5_000_000, 443_000_000)
        assert unlock.is_significant
        print("✓ Basic tests passed")
