"""
CORRECTED: process_stocks_daily.py
Daily Stock Data Update Script
Updates yesterday's OHLC data for all stocks in historical_data.json
Uses CORRECTED formula (no S&P 500 comparison)
Runs Monday-Thursday at 4:05 PM EST
"""

import os
import json
import requests
import time
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Configuration
API_KEY = os.environ.get('POLYGON_API_KEY')
BASE_URL = 'https://api.polygon.io'

def get_previous_trading_day() -> str:
    """Get the previous trading day (skip weekends)"""
    today = datetime.now()
    
    # If today is Monday, go back to Friday
    if today.weekday() == 0:  # Monday
        previous_day = today - timedelta(days=3)
    # If today is Sunday, go back to Friday
    elif today.weekday() == 6:  # Sunday
        previous_day = today - timedelta(days=2)
    else:
        previous_day = today - timedelta(days=1)
    
    return previous_day.strftime('%Y-%m-%d')

def get_daily_bar(ticker: str, date: str) -> Optional[Dict]:
    """Fetch single day's OHLC data"""
    try:
        url = f"{BASE_URL}/v1/open-close/{ticker}/{date}"
        params = {'adjusted': 'true', 'apiKey': API_KEY}
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get('status') == 'OK':
            return {
                't': int(datetime.strptime(date, '%Y-%m-%d').timestamp() * 1000),
                'o': data.get('open'),
                'h': data.get('high'),
                'l': data.get('low'),
                'c': data.get('close'),
                'v': data.get('volume', 0)
            }
        return None
    except:
        return None

def calculate_return_from_history(history: List[Dict], days_back: int) -> Optional[float]:
    """Calculate return from historical data"""
    if len(history) < days_back:
        return None
    
    end_price = history[-1]['c']
    start_price = history[-days_back]['c']
    
    return (end_price - start_price) / start_price

def calculate_stock_returns_from_history(stock_history: List[Dict]) -> tuple:
    """Calculate absolute returns (NO S&P 500 COMPARISON)"""
    if not stock_history or len(stock_history) < 252:
        return None, 0
    
    periods = {'3m': 63, '6m': 126, '9m': 189, '12m': 252}
    
    stock_returns = {}
    for period_name, days in periods.items():
        ret = calculate_return_from_history(stock_history, days)
        stock_returns[period_name] = ret if ret is not None else 0
    
    # Calculate average volume
    recent_with_volume = [p for p in stock_history if 'v' in p][-50:]
    volumes = [p['v'] for p in recent_with_volume]
    avg_volume = np.mean(volumes) if volumes else 0
    
    return stock_returns, avg_volume

def calculate_ibd_rs_score(stock_returns: Dict) -> float:
    """Calculate RS using CORRECTED formula (no S&P 500)"""
    if not stock_returns:
        return 0
    
    return (
        0.4 * stock_returns.get('3m', 0) +
        0.2 * stock_returns.get('6m', 0) +
        0.2 * stock_returns.get('9m', 0) +
        0.2 * stock_returns.get('12m', 0)
    )

def format_volume(volume: float) -> str:
    """Format volume"""
    if volume >= 1000000:
        return f"{volume/1000000:.1f}M"
    elif volume >= 1000:
        return f"{volume/1000:.0f}k"
    return str(int(volume))

def format_return(return_val: float) -> str:
    """Format return"""
    return f"{return_val*100:.1f}%"

def main():
    print("="*80)
    print("Daily Stock Update (CORRECTED FORMULA)")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    if not API_KEY:
        print("ERROR: POLYGON_API_KEY not found!")
        return
    
    update_date = get_previous_trading_day()
    print(f"Updating data for: {update_date}\n")
    
    try:
        with open('historical_data.json', 'r') as f:
            historical_data = json.load(f)
    except FileNotFoundError:
        print("ERROR: historical_data.json not found!")
        return
    
    print(f"Loaded {historical_data['n']} stocks\n")
    
    # Update stocks
    print("Updating stocks...")
    updated_stocks = []
    success = 0
    failed = 0
    
    for i, stock_data in enumerate(historical_data['d']):
        if i % 100 == 0 and i > 0:
            print(f"  {i}/{len(historical_data['d'])} - Success: {success}, Failed: {failed}")
        
        ticker = stock_data['s']
        new_bar = get_daily_bar(ticker, update_date)
        
        if new_bar:
            stock_data['h'].append(new_bar)
            if len(stock_data['h']) > 365:
                stock_data['h'] = stock_data['h'][-365:]
            stock_data['u'] = datetime.now().isoformat()
            success += 1
        else:
            failed += 1
        
        updated_stocks.append(stock_data)
        time.sleep(0.5)
    
    historical_data['d'] = updated_stocks
    historical_data['u'] = datetime.now().isoformat()
    
    print(f"\n✅ Updates: {success} success, {failed} failed\n")
    
    # Recalculate RS
    print("Recalculating RS scores...")
    all_stock_data = []
    
    for stock_data in updated_stocks:
        full_history = [{'c': bar['c'], 'v': bar.get('v', 0)} for bar in stock_data['h']]
        result = calculate_stock_returns_from_history(full_history)
        
        if result[0] is not None:
            stock_returns, avg_volume = result
            rs_score = calculate_ibd_rs_score(stock_returns)
            
            all_stock_data.append({
                'symbol': stock_data['s'],
                'rs_score': rs_score,
                'avg_volume': int(avg_volume),
                'stock_return_3m': stock_returns['3m'],
                'stock_return_6m': stock_returns['6m'],
                'stock_return_9m': stock_returns['9m'],
                'stock_return_12m': stock_returns['12m'],
                'ipo_date': stock_data.get('i')
            })
    
    # Rank
    if all_stock_data:
        all_stock_data.sort(key=lambda x: x['rs_score'], reverse=True)
        total = len(all_stock_data)
        
        for i, stock in enumerate(all_stock_data):
            stock['rs_rank'] = min(int(((total - i) / total) * 99) + 1, 99)
        
        # Format output
        output_data = []
        for stock in all_stock_data:
            output_data.append({
                'symbol': stock['symbol'],
                'rs_rank': stock['rs_rank'],
                'rs_score': round(stock['rs_score'], 4),
                'avg_volume': format_volume(stock['avg_volume']),
                'raw_volume': stock['avg_volume'],
                'stock_return_3m': format_return(stock['stock_return_3m']),
                'stock_return_6m': format_return(stock['stock_return_6m']),
                'stock_return_9m': format_return(stock['stock_return_9m']),
                'stock_return_12m': format_return(stock['stock_return_12m']),
                'ipo_date': stock.get('ipo_date')
            })
        
        # Save
        rankings_output = {
            'last_updated': datetime.now().isoformat(),
            'formula_used': 'RS = 0.4×ROC(63) + 0.2×ROC(126) + 0.2×ROC(189) + 0.2×ROC(252) [CORRECTED]',
            'total_stocks': len(output_data),
            'update_type': 'daily_update',
            'note': 'Absolute returns only, no S&P 500 comparison',
            'data': output_data
        }
        
        with open('rankings.json', 'w') as f:
            json.dump(rankings_output, f, indent=2)
        
        with open('historical_data.json', 'w') as f:
            json.dump(historical_data, f, indent=2)
        
        print(f"✅ Saved {len(output_data)} stocks\n")
        
        # Top 10
        print("🏆 TOP 10 RS RANKINGS")
        print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'3M':<10} {'12M':<10}")
        print("-" * 50)
        for i, s in enumerate(output_data[:10]):
            print(f"{i+1:<5} {s['symbol']:<8} {s['rs_rank']:<4} {s['stock_return_3m']:<10} {s['stock_return_12m']:<10}")
        
        print(f"\n✅ Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("❌ No data processed!")

if __name__ == "__main__":
    main()
