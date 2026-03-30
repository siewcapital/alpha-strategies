"""
Funding Rate Arbitrage Strategy V2

Production-ready cross-exchange funding rate arbitrage for crypto perpetual futures.
"""

__version__ = "2.0.0"
__author__ = "ATLAS"

from .strategy import (
    FundingArbitrageStrategy,
    FundingAnalyzer,
    SignalGenerator,
    RiskManager,
    FundingPrediction,
    FundingOpportunity,
    Signal,
    Position,
    Portfolio,
    SignalType,
    PositionSide,
)

__all__ = [
    "FundingArbitrageStrategy",
    "FundingAnalyzer",
    "SignalGenerator",
    "RiskManager",
    "FundingPrediction",
    "FundingOpportunity",
    "Signal",
    "Position",
    "Portfolio",
    "SignalType",
    "PositionSide",
]
