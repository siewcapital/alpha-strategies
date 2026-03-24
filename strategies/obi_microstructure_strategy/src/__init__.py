"""
Order Book Imbalance Microstructure Momentum Strategy

A high-frequency trading strategy that exploits order book imbalance
for short-term price prediction in crypto perpetual futures.
"""

from src.strategy import (
    OrderBookImbalanceStrategy,
    OrderBookSnapshot,
    OrderBookLevel,
    TradeSignal,
    SignalType,
    OrderSide
)

from src.indicators import (
    calculate_ema,
    calculate_atr,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_vwap,
    OrderBookPressureIndex
)

from src.signal_generator import (
    SignalGenerator,
    SignalConfirmation
)

from src.risk_manager import (
    RiskManager,
    RiskMetrics,
    PositionSizing,
    RiskStatus
)

__version__ = "1.0.0"
__author__ = "ATLAS Alpha Hunter"

__all__ = [
    'OrderBookImbalanceStrategy',
    'OrderBookSnapshot',
    'OrderBookLevel',
    'TradeSignal',
    'SignalType',
    'OrderSide',
    'SignalGenerator',
    'SignalConfirmation',
    'RiskManager',
    'RiskMetrics',
    'PositionSizing',
    'RiskStatus',
    'calculate_ema',
    'calculate_atr',
    'calculate_rsi',
    'calculate_bollinger_bands',
    'calculate_vwap',
    'OrderBookPressureIndex',
]
