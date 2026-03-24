"""
Enhanced Dashboard with WebSocket Support for Real-time Feeds
Adds Socket.IO for live price updates and strategy events.
"""

from flask import Flask, jsonify, render_template_string, request
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import json
from pathlib import Path
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import threading
import time
import asyncio
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'trading_connectors'))

try:
    from ccxt_connector import CCXTExchangeConnector, MultiExchangeConnector
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    logging.warning("CCXT not available - running in simulation mode")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'alpha-strategies-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


# Dashboard HTML Template with WebSocket Support
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alpha Strategies Dashboard - Real-time</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1419;
            color: #e6e6e6;
            line-height: 1.6;
        }
        .header {
            background: linear-gradient(135deg, #1a1f2e 0%, #252b3d 100%);
            padding: 20px 30px;
            border-bottom: 1px solid #2a3142;
        }
        .header h1 { font-size: 24px; font-weight: 600; color: #fff; }
        .header .subtitle { color: #8b949e; font-size: 14px; margin-top: 4px; }
        .connection-status {
            position: fixed;
            top: 20px;
            right: 30px;
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 12px;
            background: rgba(0,0,0,0.5);
            border-radius: 20px;
            font-size: 12px;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #3fb950;
            animation: pulse 2s infinite;
        }
        .status-dot.disconnected { background: #f85149; animation: none; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .container { padding: 20px 30px; max-width: 1400px; margin: 0 auto; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: #1a1f2e;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #2a3142;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }
        .card h3 {
            font-size: 14px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #2a3142;
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #8b949e; font-size: 13px; }
        .metric-value { font-size: 16px; font-weight: 600; }
        .metric-value.updating { animation: flash 0.5s; }
        @keyframes flash {
            0%, 100% { color: inherit; }
            50% { color: #58a6ff; }
        }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        .neutral { color: #58a6ff; }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-active { background: rgba(63, 185, 80, 0.15); color: #3fb950; }
        .status-paused { background: rgba(210, 153, 34, 0.15); color: #d29922; }
        .status-error { background: rgba(248, 81, 73, 0.15); color: #f85149; }
        .strategy-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #2a3142;
        }
        .strategy-row:last-child { border-bottom: none; }
        .strategy-info h4 { font-size: 14px; margin-bottom: 2px; }
        .strategy-info span { font-size: 12px; color: #8b949e; }
        .pnl-display { text-align: right; }
        .pnl-display .amount { font-size: 16px; font-weight: 600; }
        .pnl-display .trades { font-size: 12px; color: #8b949e; }
        .refresh-info {
            text-align: center;
            color: #6e7681;
            font-size: 12px;
            margin-top: 20px;
        }
        .log-container {
            background: #0d1117;
            border-radius: 8px;
            padding: 15px;
            max-height: 300px;
            overflow-y: auto;
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 12px;
        }
        .log-entry { margin: 2px 0; padding: 2px 0; }
        .log-entry.new { animation: fadeIn 0.5s; }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .log-time { color: #6e7681; }
        .log-info { color: #58a6ff; }
        .log-success { color: #3fb950; }
        .log-error { color: #f85149; }
        .log-trade { color: #d29922; }
        .price-ticker {
            display: flex;
            gap: 30px;
            padding: 15px;
            background: #0d1117;
            border-radius: 8px;
            margin-bottom: 20px;
            overflow-x: auto;
        }
        .price-item {
            display: flex;
            flex-direction: column;
            min-width: 100px;
        }
        .price-symbol { font-size: 11px; color: #8b949e; }
        .price-value { font-size: 18px; font-weight: 600; }
        .price-change {
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            display: inline-block;
            margin-top: 2px;
        }
        .price-change.up { background: rgba(63, 185, 80, 0.2); color: #3fb950; }
        .price-change.down { background: rgba(248, 81, 73, 0.2); color: #f85149; }
        .funding-rates {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
        }
        .funding-item {
            background: #0d1117;
            padding: 10px;
            border-radius: 6px;
            text-align: center;
        }
        .funding-symbol { font-size: 11px; color: #8b949e; }
        .funding-rate {
            font-size: 14px;
            font-weight: 600;
            margin-top: 4px;
        }
        .funding-rate.positive { color: #f85149; }
        .funding-rate.negative { color: #3fb950; }
        .chart-container {
            height: 250px;
            margin-top: 15px;
        }
    </style>
</head>
<body>
    <div class="connection-status">
        <div class="status-dot" id="status-dot"></div>
        <span id="connection-text">Connecting...</span>
    </div>

    <div class="header">
        <h1>🎯 Alpha Strategies Dashboard</h1>
        <div class="subtitle">Real-time Strategy Monitoring with WebSocket Feeds</div>
    </div>
    
    <div class="container">
        <!-- Live Price Ticker -->
        <div class="price-ticker" id="price-ticker">
            <div class="price-item">
                <span class="price-symbol">BTC/USDT</span>
                <span class="price-value" id="price-btc">$--</span>
                <span class="price-change" id="change-btc">--</span>
            </div>
            <div class="price-item">
                <span class="price-symbol">ETH/USDT</span>
                <span class="price-value" id="price-eth">$--</span>
                <span class="price-change" id="change-eth">--</span>
            </div>
            <div class="price-item">
                <span class="price-symbol">SOL/USDT</span>
                <span class="price-value" id="price-sol">$--</span>
                <span class="price-change" id="change-sol">--</span>
            </div>
        </div>

        <!-- Funding Rates -->
        <div class="card" style="margin-bottom: 20px;">
            <h3>💰 Live Funding Rates</h3>
            <div class="funding-rates" id="funding-rates">
                <div class="funding-item">
                    <div class="funding-symbol">BTC</div>
                    <div class="funding-rate" id="funding-btc">--</div>
                </div>
                <div class="funding-item">
                    <div class="funding-symbol">ETH</div>
                    <div class="funding-rate" id="funding-eth">--</div>
                </div>
                <div class="funding-item">
                    <div class="funding-symbol">SOL</div>
                    <div class="funding-rate" id="funding-sol">--</div>
                </div>
            </div>
        </div>

        <!-- Portfolio Overview -->
        <div class="grid">
            <div class="card">
                <h3>Portfolio Overview</h3>
                <div class="metric">
                    <span class="metric-label">Total Equity</span>
                    <span class="metric-value neutral" id="total-equity">${{ metrics.portfolio.total_equity | default('0.00') }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total P&L</span>
                    <span class="metric-value {% if metrics.portfolio.total_pnl|default(0) > 0 %}positive{% elif metrics.portfolio.total_pnl|default(0) < 0 %}negative{% else %}neutral{% endif %}" id="total-pnl">
                        ${{ metrics.portfolio.total_pnl | default('0.00') }}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total Return</span>
                    <span class="metric-value {% if metrics.portfolio.return_pct|default(0) > 0 %}positive{% elif metrics.portfolio.return_pct|default(0) < 0 %}negative{% else %}neutral{% endif %}" id="total-return">
                        {{ metrics.portfolio.return_pct | default('0.00') }}%
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Active Strategies</span>
                    <span class="metric-value neutral" id="active-strategies">{{ metrics.active_strategies | default(0) }}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Performance Metrics</h3>
                <div class="metric">
                    <span class="metric-label">Win Rate</span>
                    <span class="metric-value neutral" id="win-rate">{{ metrics.performance.win_rate | default('0') }}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Profit Factor</span>
                    <span class="metric-value neutral" id="profit-factor">{{ metrics.performance.profit_factor | default('0.00') }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Max Drawdown</span>
                    <span class="metric-value negative" id="max-drawdown">{{ metrics.performance.max_drawdown | default('0.00') }}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Sharpe Ratio</span>
                    <span class="metric-value neutral" id="sharpe-ratio">{{ metrics.performance.sharpe_ratio | default('0.00') }}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Risk Status</h3>
                <div class="metric">
                    <span class="metric-label">Exposure</span>
                    <span class="metric-value neutral" id="exposure">{{ metrics.risk.exposure_pct | default('0') }}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Open Positions</span>
                    <span class="metric-value neutral" id="open-positions">{{ metrics.risk.open_positions | default(0) }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Daily Loss</span>
                    <span class="metric-value {% if metrics.risk.daily_loss|default(0) < 0 %}negative{% else %}neutral{% endif %}" id="daily-loss">
                        ${{ metrics.risk.daily_loss | default('0.00') }}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Circuit Breaker</span>
                    <span class="metric-value {% if metrics.risk.circuit_breaker %}negative{% else %}positive{% endif %}" id="circuit-breaker">
                        {{ "TRIPPED" if metrics.risk.circuit_breaker else "Normal" }}
                    </span>
                </div>
            </div>
        </div>
        
        <!-- Strategy List -->
        <div class="card">
            <h3>Active Strategies</h3>
            <div id="strategy-list">
                {% for strategy in strategies %}
                <div class="strategy-row" data-strategy="{{ strategy.name }}">
                    <div class="strategy-info">
                        <h4>{{ strategy.name }}</h4>
                        <span>{{ strategy.description | default('') }}</span>
                    </div>
                    <div>
                        <span class="status-badge status-{{ strategy.status }}">{{ strategy.status.upper() }}</span>
                    </div>
                    <div class="pnl-display">
                        <div class="amount {% if strategy.pnl > 0 %}positive{% elif strategy.pnl < 0 %}negative{% else %}neutral{% endif %}">
                            ${{ "%.2f" | format(strategy.pnl | default(0)) }}
                        </div>
                        <div class="trades">{{ strategy.trades | default(0) }} trades</div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <!-- Live Logs -->
        <div class="card" style="margin-top: 20px;">
            <h3>Recent Activity</h3>
            <div class="log-container" id="logs">
                {% for log in logs %}
                <div class="log-entry">
                    <span class="log-time">[{{ log.time }}]</span>
                    <span class="log-{{ log.level }}">{{ log.message }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="refresh-info">
            WebSocket Connected | Last update: <span id="last-update">{{ last_update }}</span>
        </div>
    </div>
    
    <script>
        // Initialize Socket.IO connection
        const socket = io();
        
        // Connection status
        socket.on('connect', () => {
            console.log('Connected to WebSocket');
            document.getElementById('status-dot').classList.remove('disconnected');
            document.getElementById('connection-text').textContent = 'Live';
        });
        
        socket.on('disconnect', () => {
            console.log('Disconnected from WebSocket');
            document.getElementById('status-dot').classList.add('disconnected');
            document.getElementById('connection-text').textContent = 'Disconnected';
        });
        
        // Price updates
        socket.on('price_update', (data) => {
            const { symbol, price, change24h } = data;
            const symbolLower = symbol.toLowerCase();
            
            const priceEl = document.getElementById(`price-${symbolLower}`);
            const changeEl = document.getElementById(`change-${symbolLower}`);
            
            if (priceEl) {
                priceEl.textContent = `$${price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                priceEl.classList.add('updating');
                setTimeout(() => priceEl.classList.remove('updating'), 500);
            }
            
            if (changeEl) {
                const changePct = (change24h * 100).toFixed(2);
                changeEl.textContent = `${changePct > 0 ? '+' : ''}${changePct}%`;
                changeEl.className = `price-change ${changePct >= 0 ? 'up' : 'down'}`;
            }
        });
        
        // Funding rate updates
        socket.on('funding_update', (data) => {
            const { symbol, rate } = data;
            const symbolLower = symbol.toLowerCase();
            const el = document.getElementById(`funding-${symbolLower}`);
            
            if (el) {
                const ratePct = (rate * 100).toFixed(4);
                el.textContent = `${ratePct}%`;
                el.className = `funding-rate ${rate > 0 ? 'positive' : 'negative'}`;
            }
        });
        
        // Metrics updates
        socket.on('metrics_update', (data) => {
            if (data.total_equity) document.getElementById('total-equity').textContent = `$${data.total_equity.toFixed(2)}`;
            if (data.total_pnl) {
                const pnlEl = document.getElementById('total-pnl');
                pnlEl.textContent = `$${data.total_pnl.toFixed(2)}`;
                pnlEl.className = `metric-value ${data.total_pnl >= 0 ? 'positive' : 'negative'}`;
            }
            if (data.win_rate) document.getElementById('win-rate').textContent = `${data.win_rate.toFixed(1)}%`;
            if (data.sharpe_ratio) document.getElementById('sharpe-ratio').textContent = data.sharpe_ratio.toFixed(2);
        });
        
        // Strategy updates
        socket.on('strategy_update', (data) => {
            // Could refresh the strategy list here
            console.log('Strategy update:', data);
        });
        
        // New log entry
        socket.on('log_entry', (data) => {
            const logsContainer = document.getElementById('logs');
            const entry = document.createElement('div');
            entry.className = 'log-entry new';
            entry.innerHTML = `<span class="log-time">[${data.time}]</span> <span class="log-${data.level}">${data.message}</span>`;
            logsContainer.insertBefore(entry, logsContainer.firstChild);
            
            // Keep only last 50 entries
            while (logsContainer.children.length > 50) {
                logsContainer.removeChild(logsContainer.lastChild);
            }
            
            setTimeout(() => entry.classList.remove('new'), 500);
        });
        
        // Trade notification
        socket.on('trade_executed', (data) => {
            const logsContainer = document.getElementById('logs');
            const entry = document.createElement('div');
            entry.className = 'log-entry new';
            entry.innerHTML = `<span class="log-time">[${data.time}]</span> <span class="log-trade">🔄 TRADE: ${data.strategy} - ${data.side} ${data.symbol} @ $${data.price}</span>`;
            logsContainer.insertBefore(entry, logsContainer.firstChild);
        });
        
        // Update timestamp
        socket.on('heartbeat', (data) => {
            document.getElementById('last-update').textContent = data.time;
        });
    </
</script>
</body>
</html>
"""


@dataclass
class StrategyStatus:
    """Strategy status data."""
    name: str
    status: str  # active, paused, error
    description: str = ""
    pnl: float = 0.0
    trades: int = 0
    last_update: Optional[datetime] = None


@dataclass
class DashboardMetrics:
    """Dashboard metrics container."""
    portfolio: Dict = None
    performance: Dict = None
    risk: Dict = None
    active_strategies: int = 0
    
    def __post_init__(self):
        if self.portfolio is None:
            self.portfolio = {}
        if self.performance is None:
            self.performance = {}
        if self.risk is None:
            self.risk = {}


class DashboardDataStore:
    """In-memory data store for dashboard metrics."""
    
    def __init__(self):
        self.strategies: Dict[str, StrategyStatus] = {}
        self.metrics = DashboardMetrics()
        self.logs: List[Dict] = []
        self.last_update = datetime.now()
        self.price_data: Dict[str, Dict] = {}
        self.funding_data: Dict[str, float] = {}
    
    def update_strategy(self, strategy: StrategyStatus):
        """Update strategy status."""
        self.strategies[strategy.name] = strategy
        self.metrics.active_strategies = len([s for s in self.strategies.values() if s.status == 'active'])
        self.last_update = datetime.now()
    
    def update_metrics(self, metrics: DashboardMetrics):
        """Update dashboard metrics."""
        self.metrics = metrics
        self.last_update = datetime.now()
    
    def add_log(self, message: str, level: str = 'info'):
        """Add log entry."""
        entry = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'message': message,
            'level': level
        }
        self.logs.append(entry)
        self.logs = self.logs[-100:]  # Keep last 100
        return entry
    
    def update_price(self, symbol: str, price: float, change24h: float = 0):
        """Update price data."""
        self.price_data[symbol] = {
            'price': price,
            'change24h': change24h,
            'timestamp': datetime.now()
        }
    
    def update_funding(self, symbol: str, rate: float):
        """Update funding rate."""
        self.funding_data[symbol] = rate
    
    def get_data(self) -> Dict:
        """Get all dashboard data."""
        return {
            'strategies': [asdict(s) for s in self.strategies.values()],
            'metrics': asdict(self.metrics),
            'logs': self.logs[-20:],  # Last 20 logs
            'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S'),
            'prices': self.price_data,
            'funding': self.funding_data
        }


# Global data store
data_store = DashboardDataStore()


# Flask Routes
@app.route('/')
def index():
    """Main dashboard page."""
    data = data_store.get_data()
    return render_template_string(DASHBOARD_TEMPLATE, **data)


@app.route('/api/metrics')
def api_metrics():
    """API endpoint for metrics."""
    return jsonify(data_store.get_data())


@app.route('/api/strategies', methods=['GET', 'POST'])
def api_strategies():
    """Strategy management endpoint."""
    if request.method == 'POST':
        data = request.json
        strategy = StrategyStatus(
            name=data.get('name'),
            status=data.get('status', 'paused'),
            description=data.get('description', ''),
            pnl=data.get('pnl', 0.0),
            trades=data.get('trades', 0),
            last_update=datetime.now()
        )
        data_store.update_strategy(strategy)
        log_entry = data_store.add_log(f"Strategy '{strategy.name}' updated: {strategy.status}", 'info')
        
        # Emit to all connected clients
        socketio.emit('strategy_update', asdict(strategy))
        socketio.emit('log_entry', log_entry)
        
        return jsonify({'status': 'success'})
    
    return jsonify([asdict(s) for s in data_store.strategies.values()])


@app.route('/api/log', methods=['POST'])
def api_log():
    """Add log entry."""
    data = request.json
    log_entry = data_store.add_log(
        message=data.get('message', ''),
        level=data.get('level', 'info')
    )
    socketio.emit('log_entry', log_entry)
    return jsonify({'status': 'success'})


# WebSocket Events
@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'data': 'Connected to Alpha Strategies Dashboard'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    logger.info(f"Client disconnected: {request.sid}")


# Background tasks
class DataFeedManager:
    """Manages real-time data feeds via WebSocket."""
    
    def __init__(self):
        self.running = False
        self.connector = None
        self.thread = None
    
    def start(self):
        """Start data feed manager."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop)
        self.thread.daemon = True
        self.thread.start()
        logger.info("Data feed manager started")
    
    def _run_async_loop(self):
        """Run async event loop in thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._feed_loop())
    
    async def _feed_loop(self):
        """Main data feed loop."""
        symbols = ['BTC', 'ETH', 'SOL']
        
        if CCXT_AVAILABLE:
            try:
                self.connector = CCXTExchangeConnector('binance', testnet=True)
                logger.info("Connected to Binance for real-time data")
            except Exception as e:
                logger.warning(f"Could not connect to Binance: {e}")
                self.connector = None
        
        while self.running:
            try:
                if self.connector:
                    # Real data from exchange
                    for symbol in symbols:
                        try:
                            # Get price
                            ticker = await self.connector.get_ticker(f"{symbol}USDT")
                            if ticker:
                                data_store.update_price(symbol, ticker.last, 0)
                                socketio.emit('price_update', {
                                    'symbol': symbol,
                                    'price': ticker.last,
                                    'change24h': 0
                                })
                            
                            # Get funding rate
                            funding = await self.connector.get_funding_rate(f"{symbol}USDT")
                            if funding:
                                data_store.update_funding(symbol, funding.funding_rate)
                                socketio.emit('funding_update', {
                                    'symbol': symbol,
                                    'rate': funding.funding_rate
                                })
                        except Exception as e:
                            logger.debug(f"Error fetching {symbol}: {e}")
                else:
                    # Simulated data for demo
                    import random
                    for symbol in symbols:
                        base_price = {'BTC': 70000, 'ETH': 2500, 'SOL': 150}[symbol]
                        price = base_price * (1 + random.uniform(-0.02, 0.02))
                        data_store.update_price(symbol, price, random.uniform(-0.05, 0.05))
                        socketio.emit('price_update', {
                            'symbol': symbol,
                            'price': price,
                            'change24h': random.uniform(-0.05, 0.05)
                        })
                        
                        funding_rate = random.uniform(-0.001, 0.001)
                        data_store.update_funding(symbol, funding_rate)
                        socketio.emit('funding_update', {
                            'symbol': symbol,
                            'rate': funding_rate
                        })
                
                # Send heartbeat
                socketio.emit('heartbeat', {
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
                await asyncio.sleep(5)  # Update every 5 seconds
                
            except Exception as e:
                logger.error(f"Feed loop error: {e}")
                await asyncio.sleep(5)
    
    def stop(self):
        """Stop data feed manager."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Data feed manager stopped")


# Global data feed manager
data_feed = DataFeedManager()


def init_sample_data():
    """Initialize with sample data for demonstration."""
    strategies = [
        StrategyStatus(
            name="Polymarket HFT",
            status="active",
            description="High-frequency trading on Polymarket",
            pnl=2645.50,
            trades=1240
        ),
        StrategyStatus(
            name="Cross-Exchange Funding Arb",
            status="active",
            description="Funding rate arbitrage across exchanges",
            pnl=425.30,
            trades=89
        ),
        StrategyStatus(
            name="SOL RSI Mean Reversion",
            status="paused",
            description="RSI-based mean reversion on SOL (REQUIRES OPTIMIZATION)",
            pnl=-1594.00,
            trades=188
        ),
        StrategyStatus(
            name="OBI Microstructure",
            status="paused",
            description="Order book imbalance strategy",
            pnl=-338.00,
            trades=23
        ),
        StrategyStatus(
            name="Hoffman IRB",
            status="active",
            description="Multi-asset impulse system",
            pnl=892.15,
            trades=156
        ),
        StrategyStatus(
            name="VRP Harvester",
            status="paused",
            description="Volatility risk premium harvesting",
            pnl=0.0,
            trades=0
        ),
        StrategyStatus(
            name="Options Dispersion",
            status="paused",
            description="Index vs components dispersion trade",
            pnl=0.0,
            trades=0
        ),
        StrategyStatus(
            name="Polymarket Arbitrage",
            status="active",
            description="Paper trading - Live API integration",
            pnl=0.0,
            trades=0
        )
    ]
    
    for s in strategies:
        data_store.update_strategy(s)
    
    # Set sample metrics
    data_store.metrics.portfolio = {
        'total_equity': 15473.75,
        'total_pnl': 4473.75,
        'return_pct': 44.74,
        'active_strategies': 4
    }
    
    data_store.metrics.performance = {
        'win_rate': 68.5,
        'profit_factor': 2.34,
        'max_drawdown': 28.85,  # Updated from SOL RSI re-evaluation
        'sharpe_ratio': 1.85
    }
    
    data_store.metrics.risk = {
        'exposure_pct': 45.3,
        'open_positions': 12,
        'daily_loss': -120.50,
        'circuit_breaker': False
    }
    
    # Sample logs
    data_store.add_log("Dashboard initialized with WebSocket support", 'info')
    data_store.add_log("CCXT connector: Testnet validation PASSED", 'success')
    data_store.add_log("SOL RSI Strategy: REQUIRES OPTIMIZATION (Real data: -15.94%)", 'error')
    data_store.add_log("Polymarket HFT: Ready for paper trading", 'success')
    data_store.add_log("Funding Arb: Monitoring rate differentials", 'info')


def run_dashboard(host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
    """Run the dashboard server with WebSocket support."""
    init_sample_data()
    data_feed.start()
    
    logger.info(f"Starting dashboard on http://{host}:{port}")
    logger.info("WebSocket support enabled for real-time feeds")
    
    try:
        socketio.run(app, host=host, port=port, debug=debug)
    finally:
        data_feed.stop()


if __name__ == '__main__':
    run_dashboard(debug=True)
