"""
Performance Metrics Dashboard
Standalone dashboard for visualizing strategy backtest performance metrics.
"""

from flask import Flask, render_template_string, jsonify
from datetime import datetime
import json
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Strategy performance data from PERFORMANCE.md and individual results
STRATEGY_DATA = {
    "polymarket_hft": {
        "name": "Polymarket HFT",
        "status": "Validated",
        "type": "High-Frequency Arbitrage",
        "timeframe": "5-minute",
        "total_return": 2645.0,
        "win_rate": 58.0,
        "profit_factor": 2.9,
        "max_drawdown": 15.0,
        "sharpe_ratio": 3.5,
        "return_dd_ratio": 176.0,
        "confidence": "⭐⭐⭐⭐⭐",
        "trades_per_month": 196560,
        "edge_per_trade": 0.3,
        "data_quality": "Validated"
    },
    "funding_arb": {
        "name": "Cross-Exchange Funding Arb",
        "status": "Implemented",
        "type": "Market Neutral",
        "timeframe": "8-hour cycles",
        "total_return": 20.0,  # APR midpoint
        "win_rate": 70.0,
        "profit_factor": 2.1,
        "max_drawdown": 6.5,
        "sharpe_ratio": 2.25,
        "return_dd_ratio": 3.1,
        "confidence": "⭐⭐⭐⭐",
        "trades_per_month": 90,
        "edge_per_trade": 0.02,
        "data_quality": "Synthetic OU"
    },
    "hoffman_irb": {
        "name": "Hoffman IRB",
        "status": "Validated",
        "type": "Trend-Following Pullback",
        "timeframe": "1H",
        "total_return": 139.56,
        "win_rate": 61.2,
        "profit_factor": 1.06,
        "max_drawdown": 31.5,
        "sharpe_ratio": 0.96,
        "return_dd_ratio": 4.43,
        "confidence": "⭐⭐⭐⭐",
        "trades_per_month": 45,
        "edge_per_trade": 1.5,
        "data_quality": "Validated"
    },
    "sol_rsi_original": {
        "name": "SOL RSI Mean Reversion (Original)",
        "status": "Backtested",
        "type": "Mean Reversion",
        "timeframe": "1H",
        "total_return": -15.94,
        "win_rate": 57.98,
        "profit_factor": 0.94,
        "max_drawdown": 28.85,
        "sharpe_ratio": -0.24,
        "return_dd_ratio": 0.55,
        "confidence": "⭐⭐",
        "trades_per_month": 4,
        "edge_per_trade": -0.08,
        "data_quality": "Real Data"
    },
    "sol_rsi_optimized": {
        "name": "SOL RSI Mean Reversion (Optimized)",
        "status": "Ready",
        "type": "Mean Reversion + Regime Filter",
        "timeframe": "4H",
        "total_return": 4.46,
        "win_rate": 100.0,
        "profit_factor": None,
        "max_drawdown": 0.66,
        "sharpe_ratio": 6.77,
        "return_dd_ratio": 6.76,
        "confidence": "⭐⭐⭐⭐",
        "trades_per_month": 1,
        "edge_per_trade": 1.49,
        "data_quality": "Real Data"
    },
    "obi_micro": {
        "name": "OBI Microstructure",
        "status": "Backtested",
        "type": "Microstructure Scalping",
        "timeframe": "1-minute",
        "total_return": -33.8,
        "win_rate": 25.4,
        "profit_factor": 0.22,
        "max_drawdown": 33.8,
        "sharpe_ratio": -232.0,
        "return_dd_ratio": 1.0,
        "confidence": "⭐",
        "trades_per_month": 13935,
        "edge_per_trade": -0.02,
        "data_quality": "Synthetic L1"
    },
    "vrp_harvester": {
        "name": "VRP Harvester",
        "status": "Implemented",
        "type": "Short Volatility",
        "timeframe": "Option Expiry",
        "total_return": 23.0,  # APR midpoint
        "win_rate": 64.0,
        "profit_factor": 1.5,
        "max_drawdown": 15.0,
        "sharpe_ratio": 1.7,
        "return_dd_ratio": 1.53,
        "confidence": "⭐⭐⭐",
        "trades_per_month": 8,
        "edge_per_trade": 2.88,
        "data_quality": "Synthetic"
    }
}

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alpha Strategies - Performance Metrics</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e14;
            color: #e6e6e6;
            line-height: 1.6;
        }
        .header {
            background: linear-gradient(135deg, #1a2332 0%, #252b3d 100%);
            padding: 30px;
            border-bottom: 1px solid #2a3142;
        }
        .header h1 { font-size: 28px; font-weight: 600; color: #fff; }
        .header .subtitle { color: #8b949e; font-size: 14px; margin-top: 4px; }
        .header .timestamp { color: #6e7681; font-size: 12px; margin-top: 8px; }
        .container { padding: 30px; max-width: 1600px; margin: 0 auto; }
        
        /* Summary Cards */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        .summary-card {
            background: #161b22;
            border-radius: 12px;
            padding: 24px;
            border: 1px solid #30363d;
            text-align: center;
        }
        .summary-card h3 {
            font-size: 12px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
        }
        .summary-card .value {
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .summary-card .label {
            font-size: 13px;
            color: #6e7681;
        }
        
        /* Main Table */
        .table-container {
            background: #161b22;
            border-radius: 12px;
            border: 1px solid #30363d;
            overflow: hidden;
            margin-bottom: 40px;
        }
        .table-header {
            background: #1f242c;
            padding: 20px 24px;
            border-bottom: 1px solid #30363d;
        }
        .table-header h2 {
            font-size: 18px;
            font-weight: 600;
            color: #fff;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            background: #1f242c;
            padding: 14px 16px;
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            border-bottom: 1px solid #30363d;
        }
        th.sortable { cursor: pointer; }
        th.sortable:hover { color: #58a6ff; }
        td {
            padding: 16px;
            border-bottom: 1px solid #21262d;
            font-size: 14px;
        }
        tr:hover { background: #1f242c; }
        tr:last-child td { border-bottom: none; }
        
        /* Strategy Name Cell */
        .strategy-name {
            font-weight: 600;
            color: #fff;
        }
        .strategy-type {
            font-size: 12px;
            color: #8b949e;
            margin-top: 2px;
        }
        
        /* Status Badges */
        .status {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }
        .status-validated { background: rgba(63, 185, 80, 0.15); color: #3fb950; }
        .status-ready { background: rgba(63, 185, 80, 0.15); color: #3fb950; }
        .status-implemented { background: rgba(88, 166, 255, 0.15); color: #58a6ff; }
        .status-backtested { background: rgba(210, 153, 34, 0.15); color: #d29922; }
        
        /* Metric Values */
        .metric-positive { color: #3fb950; font-weight: 600; }
        .metric-negative { color: #f85149; font-weight: 600; }
        .metric-neutral { color: #58a6ff; }
        .metric-value {
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 13px;
        }
        
        /* Rankings Section */
        .rankings-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 24px;
            margin-bottom: 40px;
        }
        .ranking-card {
            background: #161b22;
            border-radius: 12px;
            border: 1px solid #30363d;
            padding: 24px;
        }
        .ranking-card h3 {
            font-size: 14px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 20px;
        }
        .ranking-item {
            display: flex;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #21262d;
        }
        .ranking-item:last-child { border-bottom: none; }
        .rank-number {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 700;
            margin-right: 16px;
        }
        .rank-1 { background: linear-gradient(135deg, #ffd700, #ffaa00); color: #000; }
        .rank-2 { background: linear-gradient(135deg, #c0c0c0, #a0a0a0); color: #000; }
        .rank-3 { background: linear-gradient(135deg, #cd7f32, #b87333); color: #fff; }
        .rank-other { background: #30363d; color: #8b949e; }
        .ranking-info { flex: 1; }
        .ranking-name { font-weight: 600; color: #fff; font-size: 14px; }
        .ranking-value { font-size: 12px; color: #8b949e; margin-top: 2px; }
        .ranking-metric {
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 16px;
            font-weight: 600;
        }
        
        /* Charts Section */
        .chart-container {
            background: #161b22;
            border-radius: 12px;
            border: 1px solid #30363d;
            padding: 24px;
            margin-bottom: 40px;
        }
        .chart-container h3 {
            font-size: 14px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 20px;
        }
        .bar-chart {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .bar-row {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .bar-label {
            width: 200px;
            font-size: 13px;
            color: #c9d1d9;
            text-align: right;
        }
        .bar-track {
            flex: 1;
            height: 24px;
            background: #21262d;
            border-radius: 4px;
            overflow: hidden;
            position: relative;
        }
        .bar-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease;
        }
        .bar-positive { background: linear-gradient(90deg, #238636, #3fb950); }
        .bar-negative { background: linear-gradient(90deg, #da3633, #f85149); }
        .bar-value {
            position: absolute;
            right: 8px;
            top: 50%;
            transform: translateY(-50%);
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 12px;
            font-weight: 600;
            color: #fff;
        }
        
        /* Data Quality Legend */
        .legend {
            display: flex;
            gap: 24px;
            padding: 16px 24px;
            background: #1f242c;
            border-top: 1px solid #30363d;
            font-size: 12px;
            color: #8b949e;
        }
        .legend-item { display: flex; align-items: center; gap: 6px; }
        .legend-dot { width: 8px; height: 8px; border-radius: 50%; }
        .dot-validated { background: #3fb950; }
        .dot-real { background: #58a6ff; }
        .dot-synthetic { background: #d29922; }
        
        /* Responsive */
        @media (max-width: 1200px) {
            .container { padding: 20px; }
            th, td { padding: 12px 10px; font-size: 12px; }
            .bar-label { width: 150px; font-size: 11px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Performance Metrics Dashboard</h1>
        <div class="subtitle">Alpha Strategies - Backtest Results & Risk Analysis</div>
        <div class="timestamp">Last Updated: {{ timestamp }}</div>
    </div>
    
    <div class="container">
        <!-- Summary Cards -->
        <div class="summary-grid">
            <div class="summary-card">
                <h3>Total Strategies</h3>
                <div class="value" style="color: #58a6ff;">{{ summary.total_strategies }}</div>
                <div class="label">{{ summary.production_ready }} production ready</div>
            </div>
            <div class="summary-card">
                <h3>Best Performer</h3>
                <div class="value" style="color: #3fb950;">{{ summary.best_performer.return }}%</div>
                <div class="label">{{ summary.best_performer.name }}</div>
            </div>
            <div class="summary-card">
                <h3>Best Risk-Adj</h3>
                <div class="value" style="color: #3fb950;">{{ summary.best_sharpe.sharpe }}</div>
                <div class="label">Sharpe: {{ summary.best_sharpe.name }}</div>
            </div>
            <div class="summary-card">
                <h3>Avg Win Rate</h3>
                <div class="value" style="color: #d29922;">{{ summary.avg_win_rate }}%</div>
                <div class="label">Across all strategies</div>
            </div>
        </div>
        
        <!-- Main Performance Table -->
        <div class="table-container">
            <div class="table-header">
                <h2>Strategy Performance Comparison</h2>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Strategy</th>
                        <th>Status</th>
                        <th>Return</th>
                        <th>Win Rate</th>
                        <th>Profit Factor</th>
                        <th>Max DD</th>
                        <th>Sharpe</th>
                        <th>Return/DD</th>
                        <th>Confidence</th>
                    </tr>
                </thead>
                <tbody>
                    {% for strategy in strategies %}
                    <tr>
                        <td>
                            <div class="strategy-name">{{ strategy.name }}</div>
                            <div class="strategy-type">{{ strategy.type }} • {{ strategy.timeframe }}</div>
                        </td>
                        <td><span class="status status-{{ strategy.status|lower }}">{{ strategy.status }}</span></td>
                        <td class="metric-value {% if strategy.total_return > 0 %}metric-positive{% elif strategy.total_return < 0 %}metric-negative{% else %}metric-neutral{% endif %}">
                            {% if strategy.total_return > 0 %}+{% endif %}{{ strategy.total_return }}%
                        </td>
                        <td class="metric-value">{{ strategy.win_rate }}%</td>
                        <td class="metric-value">{{ strategy.profit_factor if strategy.profit_factor else 'N/A' }}</td>
                        <td class="metric-value metric-negative">{{ strategy.max_drawdown }}%</td>
                        <td class="metric-value {% if strategy.sharpe_ratio > 1 %}metric-positive{% elif strategy.sharpe_ratio < 0 %}metric-negative{% else %}metric-neutral{% endif %}">
                            {{ strategy.sharpe_ratio }}
                        </td>
                        <td class="metric-value">{{ strategy.return_dd_ratio }}:1</td>
                        <td>{{ strategy.confidence }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            <div class="legend">
                <div class="legend-item"><span class="legend-dot dot-validated"></span> Validated Data</div>
                <div class="legend-item"><span class="legend-dot dot-real"></span> Real Market Data</div>
                <div class="legend-item"><span class="legend-dot dot-synthetic"></span> Synthetic Data</div>
            </div>
        </div>
        
        <!-- Rankings -->
        <div class="rankings-grid">
            <div class="ranking-card">
                <h3>🏆 Top Performers by Return</h3>
                {% for strategy in rankings.by_return %}
                <div class="ranking-item">
                    <div class="rank-number rank-{{ loop.index if loop.index <= 3 else 'other' }}">{{ loop.index }}</div>
                    <div class="ranking-info">
                        <div class="ranking-name">{{ strategy.name }}</div>
                        <div class="ranking-value">{{ strategy.type }}</div>
                    </div>
                    <div class="ranking-metric {% if strategy.total_return > 0 %}metric-positive{% else %}metric-negative{% endif %}">
                        {% if strategy.total_return > 0 %}+{% endif %}{{ strategy.total_return }}%
                    </div>
                </div>
                {% endfor %}
            </div>
            
            <div class="ranking-card">
                <h3>🛡️ Best Risk-Adjusted (Sharpe)</h3>
                {% for strategy in rankings.by_sharpe %}
                <div class="ranking-item">
                    <div class="rank-number rank-{{ loop.index if loop.index <= 3 else 'other' }}">{{ loop.index }}</div>
                    <div class="ranking-info">
                        <div class="ranking-name">{{ strategy.name }}</div>
                        <div class="ranking-value">Return/DD: {{ strategy.return_dd_ratio }}:1</div>
                    </div>
                    <div class="ranking-metric {% if strategy.sharpe_ratio > 1 %}metric-positive{% elif strategy.sharpe_ratio < 0 %}metric-negative{% else %}metric-neutral{% endif %}">
                        {{ strategy.sharpe_ratio }}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <!-- Return Chart -->
        <div class="chart-container">
            <h3>📈 Total Return by Strategy</h3>
            <div class="bar-chart">
                {% for strategy in charts.returns %}
                <div class="bar-row">
                    <div class="bar-label">{{ strategy.name }}</div>
                    <div class="bar-track">
                        <div class="bar-fill {% if strategy.total_return >= 0 %}bar-positive{% else %}bar-negative{% endif %}" 
                             style="width: {{ strategy.bar_width }}%;"></div>
                        <span class="bar-value">{% if strategy.total_return > 0 %}+{% endif %}{{ strategy.total_return }}%</span>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
</body>
</html>
"""


def calculate_summary():
    """Calculate summary statistics."""
    strategies = list(STRATEGY_DATA.values())
    production_ready = [s for s in strategies if s['status'] in ['Validated', 'Ready', 'Implemented']]
    best_performer = max(strategies, key=lambda x: x['total_return'])
    best_sharpe = max(strategies, key=lambda x: x['sharpe_ratio'])
    avg_win_rate = sum(s['win_rate'] for s in strategies) / len(strategies)
    
    return {
        'total_strategies': len(strategies),
        'production_ready': len(production_ready),
        'best_performer': {
            'name': best_performer['name'],
            'return': best_performer['total_return']
        },
        'best_sharpe': {
            'name': best_sharpe['name'],
            'sharpe': best_sharpe['sharpe_ratio']
        },
        'avg_win_rate': round(avg_win_rate, 1)
    }


def calculate_rankings():
    """Calculate strategy rankings."""
    strategies = list(STRATEGY_DATA.values())
    
    by_return = sorted(strategies, key=lambda x: x['total_return'], reverse=True)
    by_sharpe = sorted(strategies, key=lambda x: x['sharpe_ratio'], reverse=True)
    
    return {
        'by_return': by_return,
        'by_sharpe': by_sharpe
    }


def calculate_charts():
    """Prepare chart data."""
    strategies = list(STRATEGY_DATA.values())
    
    # Sort by return for display
    sorted_by_return = sorted(strategies, key=lambda x: x['total_return'], reverse=True)
    
    # Calculate bar widths (normalize to max return)
    max_return = max(abs(s['total_return']) for s in strategies)
    
    returns_data = []
    for s in sorted_by_return:
        width = (abs(s['total_return']) / max_return) * 100
        returns_data.append({
            'name': s['name'],
            'total_return': s['total_return'],
            'bar_width': max(width, 5)  # Minimum 5% width for visibility
        })
    
    return {
        'returns': returns_data
    }


@app.route('/')
def index():
    """Render the performance dashboard."""
    return render_template_string(
        DASHBOARD_TEMPLATE,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        summary=calculate_summary(),
        strategies=list(STRATEGY_DATA.values()),
        rankings=calculate_rankings(),
        charts=calculate_charts()
    )


@app.route('/api/performance')
def api_performance():
    """API endpoint for performance data."""
    return jsonify({
        'strategies': STRATEGY_DATA,
        'summary': calculate_summary(),
        'rankings': calculate_rankings(),
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/strategy/<strategy_id>')
def api_strategy(strategy_id):
    """API endpoint for individual strategy data."""
    if strategy_id in STRATEGY_DATA:
        return jsonify(STRATEGY_DATA[strategy_id])
    return jsonify({'error': 'Strategy not found'}), 404


if __name__ == '__main__':
    print("🚀 Starting Performance Metrics Dashboard...")
    print("📊 URL: http://localhost:5001")
    print("📈 API: http://localhost:5001/api/performance")
    app.run(host='0.0.0.0', port=5001, debug=True)
