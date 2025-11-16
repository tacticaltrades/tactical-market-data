"""
ARTIFACT 1 (UPDATED): process_stocks.py
Weekly Stock Data Collection Script + Recent IPO Tracking
Fetches 12 months of historical data for all common stocks to calculate RS scores
PLUS tracks stocks that IPOed in the last 90 days
Runs every Friday at 4:05 PM EST
"""

import os
import json
import requests
import time
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

# Configuration
API_KEY = os.environ.get('POLYGON_API_KEY')
BASE_URL = 'https://api.massive.com'

def get_all_tickers() -> List[str]:
    """Fetch all common stock tickers from Polygon, paginated"""
    print("Fetching all common stock tickers from Polygon...")
    all_tickers = []
    next_url = f"{BASE_URL}/v3/reference/tickers"
    
    params = {
        'market': 'stocks',
        'type': 'CS',  # Common Stock only
        'active': 'true',
        'limit': 1000,
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
            
            if 'results' in data:
                tickers = [t['ticker'] for t in data['results']]
                all_tickers.extend(tickers)
                print(f"  Page {page}: Got {len(tickers)} tickers (Total: {len(all_tickers)})")
            
            # Check for next page
            next_url = data.get('next_url')
            if next_url:
                next_url = f"{next_url}&apiKey={API_KEY}"
            
            page += 1
            time.sleep(0.1)  # Rate limiting
            
        except Exception as e:
            print(f"Error fetching tickers page {page}: {e}")
            break
    
    print(f"✅ Total tickers fetched: {len(all_tickers)}")
    return all_tickers

def get_recent_ipos() -> List[Dict]:
    """Fetch stocks that IPOed in the last 90 days using dedicated IPO endpoint"""
    print("\n=== Fetching Recent IPOs (Last 90 Days) ===")
    
    # Calculate date 90 days ago
    ninety_days_ago = datetime.now() - timedelta(days=90)
    date_filter = ninety_days_ago.strftime('%Y-%m-%d')
    
    recent_ipos = []
    next_url = f"https://api.massive.com/vX/reference/ipos"
    
    params = {
        'listing_date_gte': date_filter,
        'limit': 1000,
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
                for ipo_data in data['results']:
                    # Only include completed/priced IPOs, not just pending announcements
                    ipo_status = ipo_data.get('ipo_status', '')
                    if ipo_status in ['priced', 'new']:
                        # Use announced_date as the IPO date
                        announced = ipo_data.get('announced_date')
                        if announced:
                            recent_ipos.append({
                                'ticker': ipo_data.get('ticker'),
                                'name': ipo_data.get('issuer_name', 'N/A'),
                                'list_date': announced,  # Using announced_date as list_date
                                'ipo_price': ipo_data.get('final_issue_price'),
                                'ipo_status': ipo_status
                            })
                
                print(f"  Page {page}: Found {len(data['results'])} IPO records")
            
            next_url = data.get('next_url')
            if next_url and '?' in next_url:
                next_url = f"{next_url}&apiKey={API_KEY}"
            elif next_url:
                next_url = f"{next_url}?apiKey={API_KEY}"
            
            page += 1
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Error fetching recent IPOs page {page}: {e}")
            break
    
    print(f"✅ Found {len(recent_ipos)} completed/priced IPOs")
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

def get_ipo_date(ticker: str) -> Optional[str]:
    """Get IPO date from Polygon ticker details"""
    try:
        url = f"{BASE_URL}/v3/reference/tickers/{ticker}"
        params = {'apiKey': API_KEY}
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'results' in data and 'list_date' in data['results']:
            return data['results']['list_date']
        
        return None
    except:
        return None

def get_stock_data(ticker: str, start_date: str, end_date: str) -> List[Dict]:
    """Fetch historical daily bars for a ticker"""
    try:
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000,
            'apiKey': API_KEY
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get('results'):
            return data['results']
        
        return []
    except Exception as e:
        print(f"  Error fetching data for {ticker}: {e}")
        return []

def get_sp500_benchmark(start_date: str, end_date: str) -> List[Dict]:
    """Fetch S&P 500 (SPY) benchmark data"""
    print("Fetching S&P 500 benchmark data (SPY)...")
    return get_stock_data('SPY', start_date, end_date)

def calculate_return(prices: List[Dict], days_back: int) -> Optional[float]:
    """Calculate return over a specific period"""
    if len(prices) < days_back:
        return None
    
    end_price = prices[-1]['c']
    start_price = prices[-days_back]['c']
    
    return (end_price - start_price) / start_price

def calculate_aligned_returns(stock_prices: List[Dict], sp500_prices: List[Dict]) -> Tuple[Optional[Dict], Optional[Dict], float]:
    """Calculate returns aligned with S&P 500 benchmark"""
    if not stock_prices or not sp500_prices:
        return None, None, 0
    
    # Need at least 252 trading days (roughly 12 months)
    if len(stock_prices) < 252:
        return None, None, 0
    
    # Calculate periods (approximate trading days)
    periods = {
        '3m': 63,   # ~3 months
        '6m': 126,  # ~6 months
        '9m': 189,  # ~9 months
        '12m': 252  # ~12 months
    }
    
    stock_returns = {}
    sp500_returns = {}
    relative_returns = {}
    
    for period_name, days in periods.items():
        stock_ret = calculate_return(stock_prices, days)
        sp500_ret = calculate_return(sp500_prices, days)
        
        if stock_ret is not None and sp500_ret is not None:
            stock_returns[period_name] = stock_ret
            sp500_returns[period_name] = sp500_ret
            relative_returns[period_name] = stock_ret - sp500_ret
        else:
            stock_returns[period_name] = 0
            sp500_returns[period_name] = 0
            relative_returns[period_name] = 0
    
    # Calculate average volume over last 50 days
    recent_prices = stock_prices[-50:] if len(stock_prices) >= 50 else stock_prices
    volumes = [p['v'] for p in recent_prices if 'v' in p]
    avg_volume = np.mean(volumes) if volumes else 0
    
    return relative_returns, stock_returns, avg_volume

def calculate_ibd_rs_score(relative_returns: Dict) -> float:
    """Calculate IBD-style RS score using the discovered formula
    
    Formula: RS = 2×(3-month relative) + (6-month relative) + (9-month relative) + (12-month relative)
    Where relative = (stock return - S&P 500 return)
    """
    if not relative_returns:
        return 0
    
    rs_score = (
        2 * relative_returns.get('3m', 0) +
        1 * relative_returns.get('6m', 0) +
        1 * relative_returns.get('9m', 0) +
        1 * relative_returns.get('12m', 0)
    )
    
    return rs_score

def format_volume(volume: float) -> str:
    """Format volume as XXXk or XXXm"""
    if volume >= 1000000:
        return f"{volume/1000000:.1f}M"
    elif volume >= 1000:
        return f"{volume/1000:.0f}k"
    else:
        return str(int(volume))

def format_return(return_val: float) -> str:
    """Format return as percentage"""
    return f"{return_val*100:.1f}%"

def process_recent_ipos(recent_ipos: List[Dict]) -> List[Dict]:
    """Process recent IPO data to get current prices and stats"""
    print("\nProcessing recent IPO data...")
    
    processed_ipos = []
    
    for i, ipo in enumerate(recent_ipos):
        ticker = ipo['ticker']
        
        try:
            if i % 20 == 0:
                print(f"  Progress: {i}/{len(recent_ipos)}")
            
            # Skip if list_date is None or invalid
            if not ipo.get('list_date'):
                continue
            
            # Verify the date format
            try:
                ipo_date = datetime.strptime(ipo['list_date'], '%Y-%m-%d')
            except (ValueError, TypeError):
                continue
            
            days_since_ipo = (datetime.now() - ipo_date).days
            
            # Get current price and volume
            price_data = get_current_price_and_volume(ticker)
            
            if price_data and price_data['has_data']:
                
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

def main():
    print("=== IBD-Style Relative Strength Stock Processor (WEEKLY FULL REBUILD) ===")
    print("Formula: RS = 2×(3m relative) + 6m + 9m + 12m relative performance vs S&P 500")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not API_KEY:
        print("ERROR: POLYGON_API_KEY not found!")
        return
    
    # Date range for historical data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=450)  # Extra buffer for weekends/holidays
    
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    
    print(f"Date range: {start_date_str} to {end_date_str}")
    
    # Get S&P 500 benchmark first
    sp500_data = get_sp500_benchmark(start_date_str, end_date_str)
    if not sp500_data:
        print("ERROR: Failed to get S&P 500 benchmark data!")
        return
    
    print(f"✅ Got {len(sp500_data)} days of S&P 500 benchmark data")
    
    # Get all tickers
    tickers = get_all_tickers()
    if not tickers:
        print("ERROR: Failed to get tickers!")
        return
    
    print(f"\nProcessing {len(tickers)} stocks...")
    
    all_stock_data = []
    historical_stocks = []
    processed = 0
    failed = 0
    
    for i, ticker in enumerate(tickers):
        try:
            # Progress indicator every 100 stocks
            if i % 100 == 0:
                print(f"Progress: {i}/{len(tickers)} ({i/len(tickers)*100:.1f}%) - Processed: {processed}, Failed: {failed}")
            
            # Get historical data
            stock_prices = get_stock_data(ticker, start_date_str, end_date_str)
            
            if stock_prices:
                result = calculate_aligned_returns(stock_prices, sp500_data)
                if result[0] is not None:
                    relative_returns, stock_returns, avg_volume = result
                    rs_score = calculate_ibd_rs_score(relative_returns)
                    
                    # Get IPO date
                    ipo_date = get_ipo_date(ticker)
                    
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
                        'ipo_date': ipo_date
                    })
                    
                    # Store minimal historical data
                    minimal_history = []
                    
                    # Every 5th day for older data (excluding recent 30)
                    if len(stock_prices) > 30:
                        older_data = stock_prices[:-30:5]
                    else:
                        older_data = stock_prices[:-10:5] if len(stock_prices) > 10 else stock_prices[:-1:5] if len(stock_prices) > 1 else []
                    
                    for price in older_data:
                        minimal_history.append({
                            't': price['t'],
                            'c': price['c']
                        })
                    
                    # All recent 30 days with volume
                    recent_data = stock_prices[-30:] if len(stock_prices) >= 30 else stock_prices[-10:] if len(stock_prices) >= 10 else stock_prices
                    for price in recent_data:
                        minimal_history.append({
                            't': price['t'],
                            'c': price['c'],
                            'v': price['v']
                        })
                    
                    historical_stocks.append({
                        's': ticker,
                        'h': minimal_history,
                        'u': datetime.now().isoformat(),
                        'i': ipo_date
                    })
                    
                    processed += 1
                else:
                    failed += 1
            else:
                failed += 1
            
            # Rate limiting - 2 calls per second
            time.sleep(0.5)
            
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            failed += 1
            continue
    
    print(f"\n✅ Processing complete!")
    print(f"   Successfully processed: {processed} stocks")
    print(f"   Failed: {failed} stocks")
    
    # Calculate percentile rankings
    if all_stock_data:
        print("\nCalculating RS percentile rankings (1-99)...")
        
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
            'update_type': 'full_rebuild',
            'data': output_data
        }
        
        with open('rankings.json', 'w') as f:
            json.dump(rankings_output, f, indent=2)
        
        print(f"✅ Saved {len(output_data)} stocks to 'rankings.json'")
        
        # Save historical_data.json
        minimal_spy_data = []
        if len(sp500_data) > 30:
            older_spy = sp500_data[:-30:5]
            recent_spy = sp500_data[-30:]
        else:
            older_spy = sp500_data[:-10:5] if len(sp500_data) > 10 else sp500_data[:-1:5] if len(sp500_data) > 1 else []
            recent_spy = sp500_data[-10:] if len(sp500_data) >= 10 else sp500_data
        
        for bar in older_spy:
            minimal_spy_data.append({'t': bar['t'], 'c': bar['c']})
        for bar in recent_spy:
            minimal_spy_data.append({'t': bar['t'], 'c': bar['c'], 'v': bar['v']})
        
        historical_output = {
            'u': datetime.now().isoformat(),
            's': minimal_spy_data,
            'n': len(historical_stocks),
            'd': historical_stocks
        }
        
        with open('historical_data.json', 'w') as f:
            json.dump(historical_output, f, indent=2)
        
        print(f"✅ Historical data saved ({len(historical_stocks)} stocks)")
        
        # Show top 20 performers
        print(f"\n🏆 Top 20 RS Rankings:")
        print("Rank | Symbol | RS | 3M Rel | 12M Rel | Volume")
        print("-" * 60)
        for i, stock in enumerate(output_data[:20]):
            print(f"{i+1:2d}   | {stock['symbol']:6s} | {stock['rs_rank']:2d} | {stock['relative_3m']:7s} | {stock['relative_12m']:8s} | {stock['avg_volume']:>8s}")
        
        # Statistics
        rs_scores = [s['rs_score'] for s in all_stock_data]
        print(f"\n📊 RS Score Statistics:")
        print(f"   Highest: {max(rs_scores):.3f}")
        print(f"   Lowest: {min(rs_scores):.3f}")
        print(f"   Average: {np.mean(rs_scores):.3f}")
        print(f"   Median: {np.median(rs_scores):.3f}")
        
        high_rs_count = len([s for s in output_data if s['rs_rank'] >= 90])
        print(f"   Stocks with RS ≥ 90: {high_rs_count}")
    else:
        print("❌ No stock data was successfully processed!")
    
    # IPO SCANNING TEMPORARILY DISABLED
    # Massive.com IPO endpoint is currently experiencing issues
    # Will re-enable when their system is fixed
    # Check status: http://massive-status.com
    print("\n" + "="*60)
    print("ℹ️  IPO scanning temporarily disabled due to Massive API issues")
    print("   Check http://massive-status.com for status updates")
    
    print(f"\n✅ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
