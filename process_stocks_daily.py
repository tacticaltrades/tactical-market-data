"""
UPDATED: process_stocks_daily.py (FLEXIBLE)
Daily update script matching the flexible weekly script
Handles stocks with partial data (<252 days)
"""

import os
import json
import requests
import time
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional

API_KEY = os.environ.get('POLYGON_API_KEY')
BASE_URL = 'https://api.polygon.io'

def get_previous_trading_day() -> str:
    """Get the previous trading day (skip weekends)"""
    today = datetime.now()
    
    if today.weekday() == 0:  # Monday
        previous_day = today - timedelta(days=3)
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

def calculate_total_return(history: List[Dict]) -> float:
    """Calculate total return from first to last"""
    if len(history) < 2:
        return 0.0
    
    start_price = history[0]['c']
    end_price = history[-1]['c']
    
    return (end_price - start_price) / start_price

def calculate_stock_returns_from_history(stock_history: List[Dict]) -> tuple:
    """Calculate returns with flexible formula (matches weekly script)"""
    days_available = len(stock_history)
    
    if days_available < 10:
        return None, 0, days_available, False
    
    periods = {
        '3m': min(63, days_available),
        '6m': min(126, days_available),
        '9m': min(189, days_available),
        '12m': min(252, days_available)
    }
    
    stock_returns = {}
    
    for period_name, days in periods.items():
        if days <= days_available and days >= 10:
            ret = calculate_return_from_history(stock_history, days)
            stock_returns[period_name] = ret if ret is not None else 0
        else:
            stock_returns[period_name] = 0
    
    stock_returns['total'] = calculate_total_return(stock_history)
    
    # Calculate volume
    recent_with_volume = [p for p in stock_history if 'v' in p][-50:]
    volumes = [p['v'] for p in recent_with_volume]
    avg_volume = np.mean(volumes) if volumes else 0
    
    is_partial = days_available < 252
    
    return stock_returns, avg_volume, days_available, is_partial

def calculate_ibd_rs_score_flexible(stock_returns: Dict, days_available: int) -> float:
    """Flexible RS calculation (matches weekly script)"""
    if not stock_returns:
        return 0
    
    if days_available >= 252:
        return (
            0.4 * stock_returns.get('3m', 0) +
            0.2 * stock_returns.get('6m', 0) +
            0.2 * stock_returns.get('9m', 0) +
            0.2 * stock_returns.get('12m', 0)
        )
    elif days_available >= 189:
        return (
            0.5 * stock_returns.get('3m', 0) +
            0.25 * stock_returns.get('6m', 0) +
            0.25 * stock_returns.get('9m', 0)
        )
    elif days_available >= 126:
        return (
            0.6 * stock_returns.get('3m', 0) +
            0.4 * stock_returns.get('6m', 0)
        )
    elif days_available >= 63:
        return stock_returns.get('3m', 0)
    else:
        return stock_returns.get('total', 0)

def calculate_moving_averages(stock_history: List[Dict]) -> Optional[Dict]:
    """Calculate MAs and Stage 2 status"""
    if len(stock_history) < 200:
        return None
    
    closes = [bar['c'] for bar in stock_history]
    
    ma_50 = np.mean(closes[-50:])
    ma_150 = np.mean(closes[-150:])
    ma_200 = np.mean(closes[-200:])
    
    is_stage_2 = bool((ma_50 > ma_150) and (ma_150 > ma_200))
    
    return {
        'ma_50': round(ma_50, 2),
        'ma_150': round(ma_150, 2),
        'ma_200': round(ma_200, 2),
        'is_stage_2': is_stage_2
    }

def format_volume(volume: float) -> str:
    if volume >= 1000000:
        return f"{volume/1000000:.1f}M"
    elif volume >= 1000:
        return f"{volume/1000:.0f}k"
    return str(int(volume))

def format_return(return_val: float) -> str:
    return f"{return_val*100:.1f}%"

def main():
    print("="*80)
    print("Daily Stock Update (FLEXIBLE - Supports Partial Data)")
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
            # Update days count
            stock_data['d'] = len(stock_data['h'])
            success += 1
        else:
            failed += 1
        
        updated_stocks.append(stock_data)
        time.sleep(0.5)
    
    historical_data['d'] = updated_stocks
    historical_data['u'] = datetime.now().isoformat()
    
    print(f"\n✅ Updates: {success} success, {failed} failed\n")
    
    # Recalculate RS
    print("Recalculating RS scores (flexible formula)...")
    all_stock_data = []
    full_calc = 0
    partial_calc = 0
    stage_2_count = 0
    
    for stock_data in updated_stocks:
        full_history = [{'c': bar['c'], 'v': bar.get('v', 0)} for bar in stock_data['h']]
        result = calculate_stock_returns_from_history(full_history)
        
        if result[0] is not None:
            stock_returns, avg_volume, days_available, is_partial = result
            rs_score = calculate_ibd_rs_score_flexible(stock_returns, days_available)
            
            if is_partial:
                partial_calc += 1
            else:
                full_calc += 1
            
            # Calculate MAs
            ma_data = calculate_moving_averages(full_history)
            if ma_data and ma_data['is_stage_2']:
                stage_2_count += 1
            
            # Get current price (most recent closing price)
            current_price = round(full_history[-1]['c'], 2) if full_history else None
            
            all_stock_data.append({
                'symbol': stock_data['s'],
                'rs_score': rs_score,
                'avg_volume': int(avg_volume),
                'stock_return_3m': stock_returns.get('3m', 0),
                'stock_return_6m': stock_returns.get('6m', 0),
                'stock_return_9m': stock_returns.get('9m', 0),
                'stock_return_12m': stock_returns.get('12m', 0),
                'days_of_data': days_available,
                'is_partial': is_partial,
                'ipo_date': stock_data.get('i'),
                'current_price': current_price,
                'ma_50': ma_data['ma_50'] if ma_data else None,
                'ma_150': ma_data['ma_150'] if ma_data else None,
                'ma_200': ma_data['ma_200'] if ma_data else None,
                'is_stage_2': ma_data['is_stage_2'] if ma_data else False
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
                'days_of_data': stock['days_of_data'],
                'is_partial': stock['is_partial'],
                'ipo_date': stock.get('ipo_date'),
                'current_price': stock.get('current_price'),
                'ma_50': stock.get('ma_50'),
                'ma_150': stock.get('ma_150'),
                'ma_200': stock.get('ma_200'),
                'is_stage_2': stock.get('is_stage_2', False)
            })
        
        # Save
        rankings_output = {
            'last_updated': datetime.now().isoformat(),
            'formula_used': 'Flexible: Adapts to available data',
            'stage_2_criteria': '50dma > 150dma > 200dma',
            'total_stocks': len(output_data),
            'full_calculations': full_calc,
            'partial_calculations': partial_calc,
            'stage_2_stocks': stage_2_count,
            'update_type': 'daily_update',
            'note': 'Includes stocks with <252 days',
            'data': output_data
        }
        
        with open('rankings.json', 'w') as f:
            json.dump(rankings_output, f, indent=2)
        
        with open('historical_data.json', 'w') as f:
            json.dump(historical_data, f, indent=2)
        
        print(f"✅ Saved {len(output_data)} stocks")
        print(f"   Full data: {full_calc}, Partial data: {partial_calc}")
        print(f"   Stage 2: {stage_2_count}\n")
        
        # Top 10
        print("🏆 TOP 10")
        print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'Days':<6} {'Partial':<8} {'3M':<10}")
        print("-" * 50)
        for i, s in enumerate(output_data[:10]):
            partial = "Yes" if s['is_partial'] else "No"
            print(f"{i+1:<5} {s['symbol']:<8} {s['rs_rank']:<4} {s['days_of_data']:<6} {partial:<8} {s['stock_return_3m']:<10}")
        
        print(f"\n✅ Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("❌ No data processed!")

if __name__ == "__main__":
    main()
