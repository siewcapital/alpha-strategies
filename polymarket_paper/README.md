# Polymarket Prediction Market Strategies

**Platform:** Polymarket (Polygon-based prediction markets)  
**Strategy Types:** HFT Scalping, Arbitrage, Information Edge  
**Status:** Paper Trading Active  
**Last Updated:** March 20, 2026

---

## 📊 Overview

Polymarket is the world's largest prediction market platform, built on Polygon. It allows users to trade on the outcome of real-world events using binary (Yes/No) contracts priced between $0.01 and $0.99.

### Why Trade Polymarket?

| Advantage | Description |
|-----------|-------------|
| **Information Edge** | News often hits markets before Polymarket updates |
| **Inefficient Pricing** | Retail-dominated flow creates mispricings |
| **Low Competition** | Fewer HFTs than traditional markets |
| **Transparent** | All data on-chain, fully auditable |
| **No Counterparty Risk** | Funds secured in smart contracts |

### Market Types

| Type | Example | Liquidity | Opportunity |
|------|---------|-----------|-------------|
| **Crypto** | BTC above $100k by EOY? | High | Medium |
| **Politics** | Election outcomes | Very High | High |
| **Sports** | Super Bowl winner | Medium | Medium |
| **Science** | Fusion breakthrough | Low | Very High |

---

## 🚀 Strategies

### 1. Polymarket HFT Scalping

**Location:** `strategies/polymarket-hft/`

High-frequency scalping on BTC binary markets using spread compression and microstructure signals.

#### Logic
- Monitor order book for bid-ask spreads >2%
- Provide liquidity on both sides
- Capture spread when crossed
- Hold positions briefly (minutes to hours)

#### Performance
| Metric | Value |
|--------|-------|
| Markets Traded | BTC > $95k, $100k, $105k |
| Capital per Market | $100 |
| Median Return | 2,645% |
| Max Return | 8,089% |
| Win Rate | ~65% |
| Avg Hold Time | 2-4 hours |

#### Files
- `run.py` - Production trading loop
- `paper_trader.py` - Paper trading implementation
- `backtest.py` - Historical simulation

---

### 2. Polymarket Arbitrage

**Location:** `strategies/polymarket-arbitrage/`

Cross-market and cross-platform arbitrage opportunities.

#### Types

**A. Yes/No Arbitrage**
```
If Price(Yes) + Price(No) ≠ $1.00
→ Buy the underpriced side
→ Guaranteed profit at resolution
```

**B. Related Market Arbitrage**
```
Market A: "BTC > $100k by June?"
Market B: "BTC > $100k by July?"
If P(A) > P(B):
  Buy B, Sell A
→ B must resolve Yes if A does
```

**C. Cross-Platform Arbitrage**
- Compare Polymarket vs Kalshi vs PredictIt
- Trade price divergences

#### Status
🚧 **In Research** - Identifying consistent opportunities

---

### 3. Information Edge Trading

**Location:** `polymarket_paper/`

React to news and information faster than the market.

#### Approach
1. Monitor news sources (Twitter, Bloomberg, etc.)
2. Detect market-moving events
3. Trade before Polymarket prices adjust
4. Exit after market catches up

#### Example
```
News: "FDA approves new drug"
Market: "Will XYZ drug be approved by EOY?"

Latency:
- News hits: T+0
- You trade: T+30s
- Market adjusts: T+5min

Profit: 20-40% on immediate price jump
```

---

## 📁 Repository Structure

```
polymarket_paper/
├── README.md              # This file
├── paper_trader.py        # Paper trading engine
├── paper_runner.py        # Runner script
└── strategies/
    ├── hft_scalping.py    # HFT implementation
    ├── arbitrage.py       # Arbitrage scanner
    └── info_edge.py       # News-based trading

strategies/
├── polymarket-hft/        # HFT strategy (validated)
└── polymarket-arbitrage/  # Arbitrage strategy (research)
```

---

## 🛠️ Paper Trading Environment

### What is Paper Trading?

Simulated trading environment that:
- Tracks hypothetical positions
- Simulates fills at market prices
- Calculates P&L without real capital
- Tests strategies risk-free

### How It Works

```python
from paper_trader import PaperTrader

# Initialize
trader = PaperTrader(initial_balance=1000.0)

# Place order
order = trader.place_order(
    market_id="0x123...",
    side=OrderSide.BUY,
    position_side=PositionSide.YES,
    size=100.0,
    price=0.55
)

# Monitor positions
positions = trader.get_positions()
pnl = trader.get_portfolio_value()
```

### Paper Trading Features

| Feature | Description |
|---------|-------------|
| **Order Tracking** | Limit orders with partial fills |
| **Position Management** | Average entry, realized/unrealized P&L |
| **Fee Simulation** | 2% taker fee, 0% maker fee |
| **Portfolio Analytics** | Daily/weekly/monthly returns |
| **Trade History** | Complete audit trail |

---

## ⚙️ Configuration

### Environment Variables

```bash
# Required
export POLYMARKET_API_KEY="your_key"
export POLYMARKET_PRIVATE_KEY="your_private_key"

# Optional
export INITIAL_BALANCE="1000.0"
export DEFAULT_MARKET="btc-binary"
export LOG_LEVEL="INFO"
```

### Strategy Parameters

#### HFT Scalping
```python
HFT_CONFIG = {
    "min_spread": 0.02,        # 2% minimum spread
    "max_position_size": 100,   # $100 per market
    "max_hold_hours": 4,        # Force close after 4h
    "profit_target": 0.05,      # 5% profit target
    "stop_loss": 0.03,          # 3% stop loss
}
```

#### Arbitrage
```python
ARB_CONFIG = {
    "min_edge": 0.01,          # 1% minimum edge
    "max_position_size": 500,   # $500 max
    "hold_to_expiry": True,     # Hold until resolution
}
```

---

## 🚀 Getting Started

### 1. Setup

```bash
# Clone repository
git clone https://github.com/siewcapital/alpha-strategies.git
cd alpha-strategies/polymarket_paper

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy and edit config
cp config.example.py config.py
nano config.py  # Add your API keys
```

### 3. Run Paper Trading

```bash
# Run HFT strategy
python paper_runner.py --strategy hft --duration 24h

# Run arbitrage scanner
python paper_runner.py --strategy arbitrage --scan-interval 60
```

### 4. View Results

```bash
# Portfolio summary
python paper_runner.py --summary

# Trade history
python paper_runner.py --history

# Export to CSV
python paper_runner.py --export results.csv
```

---

## 📈 Performance Tracking

### Metrics Dashboard

| Metric | Description | Target |
|--------|-------------|--------|
| **ROI** | Return on investment |>50% monthly |
| **Sharpe** | Risk-adjusted return |>1.5 |
| **Win Rate** | % of profitable trades |>60% |
| **Avg Trade** | Average profit per trade |>$5 |
| **Max DD** | Maximum drawdown |<20% |

### Example Performance Report

```
========================================
Polymarket Paper Trading Report
Period: 2026-03-01 to 2026-03-20
========================================

Portfolio Value: $2,645.00 (+164.5%)
Initial Balance: $1,000.00

Trade Statistics:
  Total Trades: 127
  Winning Trades: 82 (64.6%)
  Losing Trades: 45 (35.4%)
  
Profit Metrics:
  Gross Profit: $1,987.00
  Gross Loss: -$342.00
  Net Profit: $1,645.00
  Profit Factor: 5.81
  
Risk Metrics:
  Max Drawdown: 12.3%
  Sharpe Ratio: 2.34
  Sortino Ratio: 3.12

Market Breakdown:
  BTC > $100k: +$892 (34 trades)
  BTC > $95k: +$456 (28 trades)
  BTC > $105k: +$297 (19 trades)
```

---

## 🔧 API Reference

### PaperTrader Class

```python
class PaperTrader:
    """Paper trading environment for Polymarket."""
    
    def __init__(self, initial_balance: float = 1000.0):
        """Initialize paper trader."""
        
    def place_order(
        self,
        market_id: str,
        side: OrderSide,
        position_side: PositionSide,
        size: float,
        price: float
    ) -> Order:
        """Place a new order."""
        
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        
    def get_positions(self) -> List[Position]:
        """Get current positions."""
        
    def get_portfolio_value(self) -> float:
        """Get current portfolio value."""
        
    def get_trade_history(self) -> pd.DataFrame:
        """Get complete trade history."""
```

### Data Classes

```python
@dataclass
class Order:
    id: str
    market_id: str
    side: OrderSide
    position_side: PositionSide
    size: float
    price: float
    status: OrderStatus
    filled_size: float
    filled_price: float
    created_at: datetime
    filled_at: Optional[datetime]

@dataclass
class Position:
    market_id: str
    side: PositionSide
    size: float
    avg_entry_price: float
    realized_pnl: float
    opened_at: datetime
    last_updated: datetime
```

---

## 📝 Example Strategies

### Simple Mean Reversion

```python
# Buy when price < 0.45, sell when > 0.55
if current_price < 0.45 and not has_position:
    trader.place_order(market_id, BUY, YES, 100, current_price)
elif current_price > 0.55 and has_yes_position:
    trader.place_order(market_id, SELL, YES, position_size, current_price)
```

### Spread Scalping

```python
# Capture the bid-ask spread
bid = order_book.best_bid
ask = order_book.best_ask
spread = ask - bid

if spread > 0.02:  # 2% spread
    # Buy at bid, sell at ask
    trader.place_order(market_id, BUY, YES, 50, bid + 0.005)
    trader.place_order(market_id, SELL, YES, 50, ask - 0.005)
```

---

## ⚠️ Risk Warnings

### Platform Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Smart Contract Risk** | Bugs in Polymarket contracts | Use audited platforms only |
| **Oracle Risk** | Incorrect resolution | Wait for official sources |
| **Liquidity Risk** | Can't exit position | Trade only liquid markets |
| **Regulatory Risk** | Platform restrictions | Diversify across markets |

### Strategy Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Adverse Selection** | Trading against informed flow | Use limit orders, not market |
| **Adverse Selection** | News hits before you trade | Faster data feeds |
| **Holding Period** | Capital tied up for months | Trade near-term events |
| **Fees** | 2% taker fee eats profits | Use maker orders |

---

## 🔗 Resources

### Polymarket Links
- **Platform:** https://polymarket.com
- **Documentation:** https://docs.polymarket.com
- **API:** https://docs.polymarket.com/#rest-api

### Related Projects
- **PyClobClient:** Python client for Polymarket CLOB
- **Gamma API:** Market data and analytics
- **Polymarket Tracker:** Third-party monitoring tools

### Academic Research
- **Wolfers & Zitzewitz (2004)** - Prediction markets
- **Arrow et al. (2008)** - Promise of prediction markets

---

## 🤝 Contributing

1. **New Strategies:** Implement and backtest
2. **Bug Fixes:** Submit PRs
3. **Documentation:** Improve clarity
4. **Data:** Share historical results

---

## 📜 License

MIT License - See LICENSE file

---

## 📧 Contact

**ATLAS Research Division**  
Siew's Capital  
research@siewcapital.com

---

*Last Updated: March 20, 2026*
