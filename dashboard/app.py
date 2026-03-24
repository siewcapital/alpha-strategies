"""
Alpha Strategies Monitoring Dashboard
Flask-based dashboard for real-time strategy monitoring.
"""

from flask import Flask, jsonify, render_template_string, request
from datetime import datetime, timedelta
import json
from pathlib import Path
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import threading
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# Dashboard HTML Template
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alpha Strategies Dashboard</title>
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
        .log-time { color: #6e7681; }
        .log-info { color: #58a6ff; }
        .log-success { color: #3fb950; }
        .log-error { color: #f85149; }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 1px solid #2a3142;
        }
        .tab {
            padding: 10px 20px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            font-size: 14px;
            color: #8b949e;
        }
        .tab.active {
            color: #58a6ff;
            border-bottom-color: #58a6ff;
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 Alpha Strategies Dashboard</h1>
        <div class="subtitle">Real-time Strategy Monitoring \u0026 Performance Tracking</div>
    </div>
    
    <div class="container">
        <!-- Portfolio Overview -->
        <div class="grid">
            <div class="card">
                <h3>Portfolio Overview</h3>
                <div class="metric">
                    <span class="metric-label">Total Equity</span>
                    <span class="metric-value neutral">${{ metrics.portfolio.total_equity | default('0.00') }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total P\u0026L</span>
                    <span class="metric-value {% if metrics.portfolio.total_pnl|default(0) > 0 %}positive{% elif metrics.portfolio.total_pnl|default(0) < 0 %}negative{% else %}neutral{% endif %}">
                        ${{ metrics.portfolio.total_pnl | default('0.00') }}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total Return</span>
                    <span class="metric-value {% if metrics.portfolio.return_pct|default(0) > 0 %}positive{% elif metrics.portfolio.return_pct|default(0) < 0 %}negative{% else %}neutral{% endif %}">
                        {{ metrics.portfolio.return_pct | default('0.00') }}%
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Active Strategies</span>
                    <span class="metric-value neutral">{{ metrics.active_strategies | default(0) }}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Performance Metrics</h3>
                <div class="metric">
                    <span class="metric-label">Win Rate</span>
                    <span class="metric-value neutral">{{ metrics.performance.win_rate | default('0') }}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Profit Factor</span>
                    <span class="metric-value neutral">{{ metrics.performance.profit_factor | default('0.00') }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Max Drawdown</span>
                    <span class="metric-value negative">{{ metrics.performance.max_drawdown | default('0.00') }}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Sharpe Ratio</span>
                    <span class="metric-value neutral">{{ metrics.performance.sharpe_ratio | default('0.00') }}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Risk Status</h3>
                <div class="metric">
                    <span class="metric-label">Exposure</span>
                    <span class="metric-value neutral">{{ metrics.risk.exposure_pct | default('0') }}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Open Positions</span>
                    <span class="metric-value neutral">{{ metrics.risk.open_positions | default(0) }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Daily Loss</span>
                    <span class="metric-value {% if metrics.risk.daily_loss|default(0) < 0 %}negative{% else %}neutral{% endif %}">
                        ${{ metrics.risk.daily_loss | default('0.00') }}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Circuit Breaker</span>
                    <span class="metric-value {% if metrics.risk.circuit_breaker %}negative{% else %}positive{% endif %}">
                        {{ "TRIPPED" if metrics.risk.circuit_breaker else "Normal" }}
                    </span>
                </div>
            </div>
        </div>
        
        <!-- Strategy List -->
        <div class="card">
            <h3>Active Strategies</h3>
            {% for strategy in strategies %}
            <div class="strategy-row">
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
            Dashboard refreshes every 5 seconds | Last update: {{ last_update }}
        </div>
    </div>
    
    <script>
        // Auto-refresh every 5 seconds
        setInterval(() => {
            fetch('/api/metrics')
                .then(r => r.json())
                .then(data => {
                    // Could update DOM here for smoother refresh
                });
        }, 5000);
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
        self.logs.append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'message': message,
            'level': level
        })
        # Keep only last 100 logs
        self.logs = self.logs[-100:]
    
    def get_data(self) -> Dict:
        """Get all dashboard data."""
        return {
            'strategies': [asdict(s) for s in self.strategies.values()],
            'metrics': asdict(self.metrics),
            'logs': self.logs[-20:],  # Last 20 logs
            'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S')
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
        data_store.add_log(f"Strategy '{strategy.name}' updated: {strategy.status}", 'info')
        return jsonify({'status': 'success'})
    
    return jsonify([asdict(s) for s in data_store.strategies.values()])


@app.route('/api/log', methods=['POST'])
def api_log():
    """Add log entry."""
    data = request.json
    data_store.add_log(
        message=data.get('message', ''),
        level=data.get('level', 'info')
    )
    return jsonify({'status': 'success'})


# Initialize with sample data
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
            description="RSI-based mean reversion on SOL",
            pnl=-51.20,
            trades=45
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
        )
    ]
    
    for s in strategies:
        data_store.update_strategy(s)
    
    # Set sample metrics
    data_store.metrics.portfolio = {
        'total_equity': 15473.75,
        'total_pnl': 4473.75,
        'return_pct': 44.74,
        'active_strategies': 3
    }
    
    data_store.metrics.performance = {
        'win_rate': 68.5,
        'profit_factor': 2.34,
        'max_drawdown': 8.2,
        'sharpe_ratio': 1.85
    }
    
    data_store.metrics.risk = {
        'exposure_pct': 45.3,
        'open_positions': 12,
        'daily_loss': -120.50,
        'circuit_breaker': False
    }
    
    # Sample logs
    data_store.add_log("Dashboard initialized", 'info')
    data_store.add_log("Polymarket HFT: Connected to CLOB API", 'success')
    data_store.add_log("Funding Arb: Scanning for opportunities", 'info')
    data_store.add_log("SOL RSI: Strategy paused - needs optimization", 'error')


def run_dashboard(host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
    """Run the dashboard server."""
    init_sample_data()
    logger.info(f"Starting dashboard on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_dashboard(debug=True)
