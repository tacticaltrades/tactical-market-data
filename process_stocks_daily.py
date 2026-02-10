"""
UPDATED: process_stocks_daily.py (FLEXIBLE + ADR/ATR + 2M)
Daily update script matching the flexible weekly script
Handles stocks with partial data (<252 days)
Includes ADR, ATR, and 2-month returns

FIXED: get_previous_trading_day() function to correctly handle weekends
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
    """Get the most recent completed trading day
    
    Logic:
    - Saturday: Get Friday (1 day back)
    - Sunday: Get Friday (2 days back)
    - Monday: Get Friday (3 days back) - previous trading day
    - Tuesday-Friday: Get yesterday (1 day back)
    """
    today = datetime.now()
    
    # If it's Saturday or Sunday, get Friday's data
    if today.weekday() == 5:  # Saturday
        previous_day = today - timedelta(days=1)
    elif today.weekday() == 6:  # Sunday
        previous_day = today - timedelta(days=2)
    # If it's Monday, get Friday's data (since we want the previous trading day)
    elif today.weekday() == 0:  # Monday
        previous_day = today - timedelta(days=3)
    # Any other weekday (Tue-Fri), get yesterday
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
        '2m': min(42, days_available),
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

def calculate_adr(stock_prices: List[Dict], period: int = 20) -> Optional[float]:
    """Calculate Average Daily Range (ADR) over specified period"""
    if len(stock_prices) < period:
        return None
    
    recent_prices = stock_prices[-period:]
    daily_ranges = []
    
    for bar in recent_prices:
        if 'h' in bar and 'l' in bar:
            daily_ranges.append(bar['h'] - bar['l'])
    
    if not daily_ranges:
        return None
    
    return np.mean(daily_ranges)

def calculate_atr(stock_prices: List[Dict], period: int = 14) -> Optional[float]:
    """Calculate Average True Range (ATR) over specified period"""
    if len(stock_prices) < period + 1:
        return None
    
    true_ranges = []
    
    for i in range(1, len(stock_prices)):
        current = stock_prices[i]
        previous = stock_prices[i - 1]
        
        if 'h' in current and 'l' in current and 'c' in previous:
            high = current['h']
            low = current['l']
            prev_close = previous['c']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            
            true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return None
    
    return np.mean(true_ranges[-period:])

def calculate_moving_averages(stock_prices: List[Dict]) -> Optional[Dict]:
    """Calculate moving averages and Stage 2 status"""
    if len(stock_prices) < 220:  # Need extra days to check 200dma trend
        return None
    
    closes = [bar['c'] for bar in stock_prices]
    current_price = closes[-1]
    
    ma_50 = np.mean(closes[-50:])
    ma_150 = np.mean(closes[-150:])
    ma_200 = np.mean(closes[-200:])
    
    # Calculate 200dma from 1 month ago (~20 trading days)
    ma_200_1month_ago = np.mean(closes[-220:-20])
    
    # TRUE Stage 2 criteria:
    # 1. MA alignment: 50 > 150 > 200
    # 2. Price above 150dma
    # 3. 200dma is rising (current 200dma > 200dma from 1 month ago)
    is_stage_2 = bool(
        (ma_50 > ma_150) and 
        (ma_150 > ma_200) and 
        (current_price > ma_150) and
        (ma_200 > ma_200_1month_ago)  # ← 200dma trending UP
    )
    
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
    print("Daily Stock Update (FLEXIBLE - ADR/ATR/2M)")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    if not API_KEY:
        print("ERROR: POLYGON_API_KEY not found!")
        return
    
    update_date = get_previous_trading_day()
    print(f"Updating data for: {update_date}")
    print(f"Day of week: {datetime.strptime(update_date, '%Y-%m-%d').strftime('%A')}\n")
    
    try:
        with open('historical_data.json', 'r') as f:
            historical_data = json.load(f)
    except FileNotFoundError:
        print("ERROR: historical_data.json not found!")
        print("Please run process_stocks.py first to create the initial dataset.")
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
    print("Recalculating RS scores (flexible formula + volatility)...")
    all_stock_data = []
    full_calc = 0
    partial_calc = 0
    stage_2_count = 0
    
    for stock_data in updated_stocks:
        # Full history with all OHLCV data
        full_history = stock_data['h']
        
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
            
            # Calculate ADR and ATR
            adr_20 = calculate_adr(full_history, period=20)
            atr_14 = calculate_atr(full_history, period=14)
            
            # Get current price (most recent closing price)
            current_price = round(full_history[-1]['c'], 2) if full_history else None
            
            all_stock_data.append({
                'symbol': stock_data['s'],
                'rs_score': rs_score,
                'avg_volume': int(avg_volume),
                'stock_return_2m': stock_returns.get('2m', 0),
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
                'is_stage_2': ma_data['is_stage_2'] if ma_data else False,
                'adr_20': round(adr_20, 2) if adr_20 is not None else None,
                'atr_14': round(atr_14, 2) if atr_14 is not None else None
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
                'stock_return_2m': format_return(stock['stock_return_2m']),
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
                'is_stage_2': stock.get('is_stage_2', False),
                'adr_20': stock.get('adr_20'),
                'atr_14': stock.get('atr_14')
            })
        
        # Save
        rankings_output = {
            'last_updated': datetime.now().isoformat(),
            'formula_used': 'Flexible: Adapts to available data',
            'stage_2_criteria': '50dma > 150dma > 200dma',
            'volatility_metrics': 'ADR (20-day), ATR (14-day)',
            'total_stocks': len(output_data),
            'full_calculations': full_calc,
            'partial_calculations': partial_calc,
            'stage_2_stocks': stage_2_count,
            'update_type': 'daily_update',
            'update_date': update_date,
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
        print("="*90)
        print("🏆 TOP 10")
        print("="*90)
        print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'Days':<6} {'Part':<5} {'ADR':<7} {'ATR':<7} {'2M':<8}")
        print("-" * 90)
        for i, s in enumerate(output_data[:10]):
            partial = "Y" if s['is_partial'] else "N"
            adr_str = f"${s['adr_20']}" if s['adr_20'] else "N/A"
            atr_str = f"${s['atr_14']}" if s['atr_14'] else "N/A"
            print(f"{i+1:<5} {s['symbol']:<8} {s['rs_rank']:<4} {s['days_of_data']:<6} {partial:^5} {adr_str:<7} {atr_str:<7} {s['stock_return_2m']:<8}")
        
        print(f"\n✅ Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
    else:
        print("❌ No data processed!")

if __name__ == "__main__":
    main()
