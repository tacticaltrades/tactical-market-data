"""
ARTIFACT 2 (UPDATED): process_stocks_daily.py
Daily Stock Data Update Script + Recent IPO Scanning
Updates yesterday's OHLC data for all stocks in historical_data.json
PLUS scans for new IPOs daily and updates recent_ipos.json
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
            # Convert to same format as historical data
            return {
                't': int(datetime.strptime(date, '%Y-%m-%d').timestamp() * 1000),
                'o': data.get('open'),
                'h': data.get('high'),
                'l': data.get('low'),
                'c': data.get('close'),
                'v': data.get('volume', 0)
            }
        
        return None
    except Exception as e:
        return None

def get_recent_ipos() -> List[Dict]:
    """Fetch stocks that IPOed in the last 90 days"""
    print("\n=== Scanning for Recent IPOs (Last 90 Days) ===")
    
    # Calculate date 90 days ago
    ninety_days_ago = datetime.now() - timedelta(days=90)
    date_filter = ninety_days_ago.strftime('%Y-%m-%d')
    
    recent_ipos = []
    next_url = f"{BASE_URL}/v3/reference/tickers"
    
    params = {
        'market': 'stocks',
        'type': 'CS',
        'active': 'true',
        'limit': 1000,
        'list_date.gte': date_filter,  # IPO date >= 90 days ago
        'apiKey': API_KEY
    }
    
    page = 1
    while next_url:
        try:
            if page > 1:
                response = requests.get(next_url)
            else:
                response = requests.get(next_url, params=params)
            
            response.raise_for_status()
            data = response.json()
            
            if 'results' in data and data['results']:
                for ticker_data in data['results']:
                    recent_ipos.append({
                        'ticker': ticker_data['ticker'],
                        'name': ticker_data.get('name', 'N/A'),
                        'list_date': ticker_data.get('list_date'),
                        'locale': ticker_data.get('locale')
                    })
                
                print(f"  Page {page}: Found {len(data['results'])} IPOs")
            
            next_url = data.get('next_url')
            if next_url:
                next_url = f"{next_url}&apiKey={API_KEY}"
            
            page += 1
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Error fetching recent IPOs page {page}: {e}")
            break
    
    print(f"✅ Found {len(recent_ipos)} stocks that IPOed in last 90 days")
    return recent_ipos

def get_current_price_and_volume(ticker: str) -> Optional[Dict]:
    """Get current price and recent volume for a ticker"""
    try:
        # Get last 5 days of data to calculate average volume and current price
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
        params = {
            'adjusted': 'true',
            'sort': 'desc',
            'limit': 10,
            'apiKey': API_KEY
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get('results'):
            bars = data['results']
            current_price = bars[0]['c']  # Most recent close
            volumes = [bar['v'] for bar in bars]
            avg_volume = np.mean(volumes) if volumes else 0
            
            # Try to get IPO price (first day's open)
            ipo_price = bars[-1]['o'] if len(bars) > 0 else None
            
            return {
                'current_price': current_price,
                'avg_volume': int(avg_volume),
                'ipo_price': ipo_price,
                'has_data': True
            }
        
        return None
        
    except Exception as e:
        return None

def format_volume(volume: float) -> str:
    """Format volume as XXXk or XXXm"""
    if volume >= 1000000:
        return f"{volume/1000000:.1f}M"
    elif volume >= 1000:
        return f"{volume/1000:.0f}k"
    else:
        return str(int(volume))

def process_recent_ipos(recent_ipos: List[Dict]) -> List[Dict]:
    """Process recent IPO data to get current prices and stats"""
    print("\nProcessing recent IPO data...")
    
    processed_ipos = []
    
    for i, ipo in enumerate(recent_ipos):
        ticker = ipo['ticker']
        
        try:
            if i % 20 == 0:
                print(f"  Progress: {i}/{len(recent_ipos)}")
            
            # Get current price and volume
            price_data = get_current_price_and_volume(ticker)
            
            if price_data and price_data['has_data']:
                ipo_date = datetime.strptime(ipo['list_date'], '%Y-%m-%d')
                days_since_ipo = (datetime.now() - ipo_date).days
                
                # Calculate percent change from IPO if we have IPO price
                percent_from_ipo = None
                if price_data.get('ipo_price'):
                    percent_from_ipo = ((price_data['current_price'] - price_data['ipo_price']) / price_data['ipo_price']) * 100
                
                processed_ipos.append({
                    'symbol': ticker,
                    'company_name': ipo['name'],
                    'ipo_date': ipo['list_date'],
                    'days_since_ipo': days_since_ipo,
                    'current_price': round(price_data['current_price'], 2),
                    'ipo_price': round(price_data['ipo_price'], 2) if price_data.get('ipo_price') else None,
                    'percent_from_ipo': round(percent_from_ipo, 1) if percent_from_ipo is not None else None,
                    'avg_volume': format_volume(price_data['avg_volume']),
                    'raw_volume': price_data['avg_volume']
                })
            
            time.sleep(0.5)  # Rate limiting
            
        except Exception as e:
            print(f"  Error processing {ticker}: {e}")
            continue
    
    print(f"✅ Processed {len(processed_ipos)} recent IPOs with data")
    return processed_ipos

def calculate_return_from_history(history: List[Dict], days_back: int) -> Optional[float]:
    """Calculate return from historical data"""
    if len(history) < days_back:
        return None
    
    end_price = history[-1]['c']
    start_price = history[-days_back]['c']
    
    return (end_price - start_price) / start_price

def calculate_aligned_returns_from_history(stock_history: List[Dict], sp500_history: List[Dict]) -> tuple:
    """Calculate returns from historical data"""
    if not stock_history or not sp500_history:
        return None, None, 0
    
    if len(stock_history) < 252:
        return None, None, 0
    
    periods = {
        '3m': 63,
        '6m': 126,
        '9m': 189,
        '12m': 252
    }
    
    stock_returns = {}
    sp500_returns = {}
    relative_returns = {}
    
    for period_name, days in periods.items():
        stock_ret = calculate_return_from_history(stock_history, days)
        sp500_ret = calculate_return_from_history(sp500_history, days)
        
        if stock_ret is not None and sp500_ret is not None:
            stock_returns[period_name] = stock_ret
            sp500_returns[period_name] = sp500_ret
            relative_returns[period_name] = stock_ret - sp500_ret
        else:
            stock_returns[period_name] = 0
            sp500_returns[period_name] = 0
            relative_returns[period_name] = 0
    
    # Calculate average volume over last 50 days
    recent_with_volume = [p for p in stock_history if 'v' in p][-50:]
    volumes = [p['v'] for p in recent_with_volume]
    avg_volume = np.mean(volumes) if volumes else 0
    
    return relative_returns, stock_returns, avg_volume

def calculate_ibd_rs_score(relative_returns: Dict) -> float:
    """Calculate IBD-style RS score"""
    if not relative_returns:
        return 0
    
    rs_score = (
        2 * relative_returns.get('3m', 0) +
        1 * relative_returns.get('6m', 0) +
        1 * relative_returns.get('9m', 0) +
        1 * relative_returns.get('12m', 0)
    )
    
    return rs_score

def format_return(return_val: float) -> str:
    """Format return as percentage"""
    return f"{return_val*100:.1f}%"

def main():
    print("=== Daily Stock Data Update + IPO Scan ===")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not API_KEY:
        print("ERROR: POLYGON_API_KEY not found!")
        return
    
    # Get previous trading day
    update_date = get_previous_trading_day()
    print(f"Updating data for: {update_date}")
    
    # Load historical data
    try:
        with open('historical_data.json', 'r') as f:
            historical_data = json.load(f)
    except FileNotFoundError:
        print("ERROR: historical_data.json not found! Run weekly refresh first.")
        return
    
    print(f"Loaded historical data for {historical_data['n']} stocks")
    
    # Update S&P 500 benchmark first
    print("\nUpdating S&P 500 benchmark...")
    spy_bar = get_daily_bar('SPY', update_date)
    
    if not spy_bar:
        print("ERROR: Could not fetch S&P 500 data for update date!")
        return
    
    # Add new SPY bar and maintain rolling window
    sp500_data = historical_data['s']
    sp500_data.append(spy_bar)
    
    # Keep only last ~365 days of data
    if len(sp500_data) > 365:
        sp500_data = sp500_data[-365:]
    
    historical_data['s'] = sp500_data
    print(f"✅ Updated S&P 500 ({len(sp500_data)} days of data)")
    
    # Update all stocks
    print(f"\nUpdating {len(historical_data['d'])} stocks...")
    
    updated_stocks = []
    failed_updates = 0
    
    for i, stock_data in enumerate(historical_data['d']):
        ticker = stock_data['s']
        
        try:
            if i % 100 == 0:
                print(f"Progress: {i}/{len(historical_data['d'])} ({i/len(historical_data['d'])*100:.1f}%)")
            
            # Fetch new bar
            new_bar = get_daily_bar(ticker, update_date)
            
            if new_bar:
                # Add new bar to history
                stock_history = stock_data['h']
                stock_history.append(new_bar)
                
                # Keep rolling 365-day window
                if len(stock_history) > 365:
                    stock_history = stock_history[-365:]
                
                stock_data['h'] = stock_history
                stock_data['u'] = datetime.now().isoformat()
                
                updated_stocks.append(stock_data)
            else:
                # Keep existing data if update fails
                updated_stocks.append(stock_data)
                failed_updates += 1
            
            # Rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            print(f"Error updating {ticker}: {e}")
            updated_stocks.append(stock_data)
            failed_updates += 1
            continue
    
    historical_data['d'] = updated_stocks
    historical_data['u'] = datetime.now().isoformat()
    
    print(f"\n✅ Stock updates complete!")
    print(f"   Successfully updated: {len(updated_stocks) - failed_updates}")
    print(f"   Failed: {failed_updates}")
    
    # Recalculate RS scores for all stocks
    print("\nRecalculating RS scores...")
    
    all_stock_data = []
    
    for stock_data in updated_stocks:
        ticker = stock_data['s']
        stock_history = stock_data['h']
        
        # Reconstruct full history with close prices
        full_history = [{'c': bar['c'], 'v': bar.get('v', 0), 't': bar['t']} for bar in stock_history]
        sp500_full = [{'c': bar['c'], 'v': bar.get('v', 0), 't': bar['t']} for bar in sp500_data]
        
        result = calculate_aligned_returns_from_history(full_history, sp500_full)
        
        if result[0] is not None:
            relative_returns, stock_returns, avg_volume = result
            rs_score = calculate_ibd_rs_score(relative_returns)
            
            all_stock_data.append({
                'symbol': ticker,
                'rs_score': rs_score,
                'avg_volume': int(avg_volume),
                'relative_3m': relative_returns['3m'],
                'relative_6m': relative_returns['6m'],
                'relative_9m': relative_returns['9m'],
                'relative_12m': relative_returns['12m'],
                'stock_return_3m': stock_returns['3m'],
                'stock_return_12m': stock_returns['12m'],
                'ipo_date': stock_data.get('i')
            })
    
    # Calculate percentile rankings
    if all_stock_data:
        print("Calculating RS percentile rankings...")
        
        all_stock_data.sort(key=lambda x: x['rs_score'], reverse=True)
        
        total_stocks = len(all_stock_data)
        for i, stock in enumerate(all_stock_data):
            percentile = int(((total_stocks - i) / total_stocks) * 99) + 1
            stock['rs_rank'] = min(percentile, 99)
        
        # Format for output
        output_data = []
        for stock in all_stock_data:
            output_data.append({
                'symbol': stock['symbol'],
                'rs_rank': stock['rs_rank'],
                'rs_score': round(stock['rs_score'], 4),
                'avg_volume': format_volume(stock['avg_volume']),
                'raw_volume': stock['avg_volume'],
                'relative_3m': format_return(stock['relative_3m']),
                'relative_6m': format_return(stock['relative_6m']),
                'relative_9m': format_return(stock['relative_9m']),
                'relative_12m': format_return(stock['relative_12m']),
                'stock_return_3m': format_return(stock['stock_return_3m']),
                'stock_return_12m': format_return(stock['stock_return_12m']),
                'ipo_date': stock.get('ipo_date')
            })
        
        # Save rankings.json
        rankings_output = {
            'last_updated': datetime.now().isoformat(),
            'formula_used': 'RS = 2×(3m relative vs S&P500) + 6m + 9m + 12m relative performance',
            'total_stocks': len(output_data),
            'benchmark': 'S&P 500 (SPY)',
            'update_type': 'daily_update',
            'data': output_data
        }
        
        with open('rankings.json', 'w') as f:
            json.dump(rankings_output, f, indent=2)
        
        print(f"✅ Updated rankings.json with {len(output_data)} stocks")
        
        # Save historical_data.json
        with open('historical_data.json', 'w') as f:
            json.dump(historical_data, f, indent=2)
        
        print(f"✅ Updated historical_data.json")
        
        # Show top 10
        print(f"\n🏆 Top 10 RS Rankings:")
        print("Rank | Symbol | RS | 3M Rel | Volume")
        print("-" * 45)
        for i, stock in enumerate(output_data[:10]):
            print(f"{i+1:2d}   | {stock['symbol']:6s} | {stock['rs_rank']:2d} | {stock['relative_3m']:7s} | {stock['avg_volume']:>8s}")
    else:
        print("❌ No stock data was successfully processed!")
    
    # SCAN AND UPDATE RECENT IPOs
    print("\n" + "="*60)
    recent_ipos = get_recent_ipos()
    
    if recent_ipos:
        processed_ipos = process_recent_ipos(recent_ipos)
        
        # Sort by IPO date (newest first)
        processed_ipos.sort(key=lambda x: x['ipo_date'], reverse=True)
        
        # Save recent_ipos.json
        ipo_output = {
            'last_updated': datetime.now().isoformat(),
            'total_recent_ipos': len(processed_ipos),
            'lookback_days': 90,
            'note': 'Stocks that IPOed in the last 90 days. Updated daily. May not have RS scores due to insufficient history.',
            'data': processed_ipos
        }
        
        with open('recent_ipos.json', 'w') as f:
            json.dump(ipo_output, f, indent=2)
        
        print(f"\n✅ Updated recent_ipos.json with {len(processed_ipos)} IPOs")
        
        # Show most recent IPOs
        if processed_ipos:
            print(f"\n🆕 Most Recent IPOs:")
            print("Symbol | Company | IPO Date | Days | Price | Change")
            print("-" * 70)
            for ipo in processed_ipos[:10]:
                change_str = f"{ipo['percent_from_ipo']:+.1f}%" if ipo['percent_from_ipo'] is not None else "N/A"
                print(f"{ipo['symbol']:6s} | {ipo['company_name'][:20]:20s} | {ipo['ipo_date']} | {ipo['days_since_ipo']:3d}d | ${ipo['current_price']:6.2f} | {change_str}")
    
    print(f"\n✅ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
