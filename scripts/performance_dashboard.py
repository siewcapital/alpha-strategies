import os
import glob
import re

def parse_markdown_results(file_path):
    metrics = {}
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Defaults
    metrics['Strategy'] = os.path.basename(os.path.dirname(file_path))
    metrics['Return'] = 'N/A'
    metrics['Sharpe'] = 'N/A'
    metrics['Final Capital'] = 'N/A'

    if "polymarket-hft" in file_path:
        metrics['Strategy'] = "Polymarket HFT"
        match_return = re.search(r'Mean Return\s*\|\s*([^\|\n]+)', content)
        if match_return: metrics['Return'] = match_return.group(1).strip()
        
        match_cap = re.search(r'Median Final Capital\s*\|\s*([^\|\n]+)', content)
        if match_cap: metrics['Final Capital'] = match_cap.group(1).strip()
        
    elif "sol-rsi-mean-reversion" in file_path:
        metrics['Strategy'] = "SOL/USDT RSI Mean Reversion"
        match_ret = re.search(r'\*\*Total Return\*\*:\s*([^\n]+)', content)
        if match_ret: metrics['Return'] = match_ret.group(1).strip()
        
        match_sharpe = re.search(r'\*\*Sharpe Ratio\*\*:\s*([\d\.]+)', content)
        if match_sharpe: metrics['Sharpe'] = match_sharpe.group(1).strip()
        
    return metrics

def generate_dashboard():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    strat_dir = os.path.join(root_dir, "strategies")
    
    results_files = glob.glob(os.path.join(strat_dir, "*", "results.md"))
    
    all_metrics = []
    for rf in results_files:
        all_metrics.append(parse_markdown_results(rf))
            
    dashboard = "# Alpha Strategies Performance Dashboard\n\n"
    dashboard += "Auto-generated dashboard of backtest results across all strategies.\n\n"
    dashboard += "| Strategy | Return | Sharpe | Final Capital |\n"
    dashboard += "|---|---|---|---|\n"
    
    for m in all_metrics:
        dashboard += f"| {m['Strategy']} | {m['Return']} | {m['Sharpe']} | {m['Final Capital']} |\n"
        
    dashboard += "\n*Note: Run `python scripts/performance_dashboard.py` to update this file.*\n"
    
    dash_path = os.path.join(root_dir, "PERFORMANCE.md")
    with open(dash_path, 'w') as f:
        f.write(dashboard)
        
    print(f"Dashboard generated at {dash_path}")

if __name__ == "__main__":
    generate_dashboard()
