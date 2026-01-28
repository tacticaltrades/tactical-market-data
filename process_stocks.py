"""
UPDATED: process_stocks.py (FLEXIBLE RS CALCULATION)
Now includes stocks with <252 days of data (recent IPOs)
Calculates RS using whatever historical data is available

Formula adapts based on data availability:
- 252+ days: Full formula (0.4×3m + 0.2×6m + 0.2×9m + 0.2×12m)
- 189-251 days: 3m, 6m, 9m only (reweighted)
- 126-188 days: 3m, 6m only (reweighted)
- 63-125 days: 3m only
- 10-62 days: Total return since listing
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
BASE_URL = 'https://api.polygon.io'

def get_all_tickers() -> List[str]:
    """Fetch all common stock tickers from Polygon, paginated"""
    print("Fetching all common stock tickers from Polygon...")
    all_tickers = []
    next_url = f"{BASE_URL}/v3/reference/tickers"
    
    params = {
        'market': 'stocks',
        'type': 'CS',
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
            
            next_url = data.get('next_url')
            if next_url:
                next_url = f"{next_url}&apiKey={API_KEY}"
            
            page += 1
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Error fetching tickers page {page}: {e}")
            break
    
    print(f"✅ Total tickers fetched: {len(all_tickers)}")
    return all_tickers

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
        return []

def calculate_return(prices: List[Dict], days_back: int) -> Optional[float]:
    """Calculate return over a specific period"""
    if len(prices) < days_back:
        return None
    
    end_price = prices[-1]['c']
    start_price = prices[-days_back]['c']
    
    return (end_price - start_price) / start_price

def calculate_total_return(prices: List[Dict]) -> float:
    """Calculate total return from first to last price"""
    if len(prices) < 2:
        return 0.0
    
    start_price = prices[0]['c']
    end_price = prices[-1]['c']
    
    return (end_price - start_price) / start_price

def calculate_moving_averages(stock_prices: List[Dict]) -> Optional[Dict]:
    """Calculate moving averages and Stage 2 status"""
    if len(stock_prices) < 200:
        return None
    
    closes = [bar['c'] for bar in stock_prices]
    
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

def calculate_stock_returns_flexible(stock_prices: List[Dict]) -> Tuple[Optional[Dict], float, int, bool]:
    """Calculate returns with whatever data is available (FLEXIBLE)
    
    Returns: (stock_returns, avg_volume, days_available, is_partial)
    """
    days_available = len(stock_prices)
    
    # Minimum threshold: at least 10 days
    if days_available < 10:
        return None, 0, days_available, False
    
    # Calculate periods based on available data
    periods = {
        '3m': min(63, days_available),
        '6m': min(126, days_available),
        '9m': min(189, days_available),
        '12m': min(252, days_available)
    }
    
    stock_returns = {}
    
    for period_name, days in periods.items():
        if days <= days_available and days >= 10:  # Need at least 10 days
            ret = calculate_return(stock_prices, days)
            stock_returns[period_name] = ret if ret is not None else 0
        else:
            stock_returns[period_name] = 0
    
    # For very new stocks, also calculate total return
    stock_returns['total'] = calculate_total_return(stock_prices)
    
    # Calculate average volume
    recent_prices = stock_prices[-50:] if len(stock_prices) >= 50 else stock_prices
    volumes = [p['v'] for p in recent_prices if 'v' in p]
    avg_volume = np.mean(volumes) if volumes else 0
    
    # Is this a partial calculation?
    is_partial = days_available < 252
    
    return stock_returns, avg_volume, days_available, is_partial

def calculate_ibd_rs_score_flexible(stock_returns: Dict, days_available: int) -> float:
    """Calculate RS score using FLEXIBLE formula based on data availability
    
    Adapts the weighting based on how much historical data is available
    """
    if not stock_returns:
        return 0
    
    # FULL FORMULA: 252+ days (12+ months)
    if days_available >= 252:
        rs_score = (
            0.4 * stock_returns.get('3m', 0) +
            0.2 * stock_returns.get('6m', 0) +
            0.2 * stock_returns.get('9m', 0) +
            0.2 * stock_returns.get('12m', 0)
        )
    
    # PARTIAL: 189-251 days (9-12 months) - Use 3m, 6m, 9m only
    elif days_available >= 189:
        rs_score = (
            0.5 * stock_returns.get('3m', 0) +   # Reweight: 40% → 50%
            0.25 * stock_returns.get('6m', 0) +  # Reweight: 20% → 25%
            0.25 * stock_returns.get('9m', 0)    # Reweight: 20% → 25%
        )
    
    # PARTIAL: 126-188 days (6-9 months) - Use 3m, 6m only
    elif days_available >= 126:
        rs_score = (
            0.6 * stock_returns.get('3m', 0) +   # Reweight: 40% → 60%
            0.4 * stock_returns.get('6m', 0)     # Reweight: 20% → 40%
        )
    
    # PARTIAL: 63-125 days (3-6 months) - Use 3m only
    elif days_available >= 63:
        rs_score = stock_returns.get('3m', 0)
    
    # VERY NEW: 10-62 days - Use total return since listing
    else:
        rs_score = stock_returns.get('total', 0)
    
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

def main():
    print("="*80)
    print("IBD-Style RS Calculator (FLEXIBLE - Includes Recent IPOs)")
    print("="*80)
    print()
    print("Formula adapts to available data:")
    print("  252+ days: 0.4×3m + 0.2×6m + 0.2×9m + 0.2×12m")
    print("  189-251 days: 0.5×3m + 0.25×6m + 0.25×9m")
    print("  126-188 days: 0.6×3m + 0.4×6m")
    print("  63-125 days: 3m return only")
    print("  10-62 days: Total return since listing")
    print()
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if not API_KEY:
        print("ERROR: POLYGON_API_KEY not found!")
        return
    
    # Date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=450)
    
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    
    print(f"Date range: {start_date_str} to {end_date_str}")
    print()
    
    # Get all tickers
    tickers = get_all_tickers()
    if not tickers:
        print("ERROR: Failed to get tickers!")
        return
    
    print(f"\nProcessing {len(tickers)} stocks (including recent IPOs)...")
    print()
    
    all_stock_data = []
    historical_stocks = []
    processed = 0
    failed = 0
    partial_calculations = 0
    full_calculations = 0
    stage_2_count = 0
    
    for i, ticker in enumerate(tickers):
        try:
            if i % 100 == 0 and i > 0:
                print(f"Progress: {i}/{len(tickers)} ({i/len(tickers)*100:.1f}%)")
                print(f"  Full data: {full_calculations}, Partial data: {partial_calculations}, Failed: {failed}, Stage 2: {stage_2_count}")
            
            # Get historical data
            stock_prices = get_stock_data(ticker, start_date_str, end_date_str)
            
            if not stock_prices:
                failed += 1
                continue
            
            # Calculate returns (FLEXIBLE - works with any amount of data)
            result = calculate_stock_returns_flexible(stock_prices)
            
            if result[0] is None:
                failed += 1
                continue
            
            stock_returns, avg_volume, days_available, is_partial = result
            rs_score = calculate_ibd_rs_score_flexible(stock_returns, days_available)
            
            # Track partial vs full calculations
            if is_partial:
                partial_calculations += 1
            else:
                full_calculations += 1
            
            # Calculate moving averages (if enough data)
            ma_data = calculate_moving_averages(stock_prices)
            
            # Get IPO date
            ipo_date = get_ipo_date(ticker)
            
            # Count Stage 2 stocks
            if ma_data and ma_data['is_stage_2']:
                stage_2_count += 1
            
            all_stock_data.append({
                'symbol': ticker,
                'rs_score': rs_score,
                'avg_volume': int(avg_volume),
                'stock_return_3m': stock_returns.get('3m', 0),
                'stock_return_6m': stock_returns.get('6m', 0),
                'stock_return_9m': stock_returns.get('9m', 0),
                'stock_return_12m': stock_returns.get('12m', 0),
                'days_of_data': days_available,
                'is_partial': is_partial,
                'ipo_date': ipo_date,
                'ma_50': ma_data['ma_50'] if ma_data else None,
                'ma_150': ma_data['ma_150'] if ma_data else None,
                'ma_200': ma_data['ma_200'] if ma_data else None,
                'is_stage_2': ma_data['is_stage_2'] if ma_data else False
            })
            
            # Store historical data (simplified)
            minimal_history = []
            
            if len(stock_prices) > 30:
                older_data = stock_prices[:-30:5]
            else:
                older_data = stock_prices[:-10:5] if len(stock_prices) > 10 else []
            
            for price in older_data:
                minimal_history.append({'t': price['t'], 'c': price['c']})
            
            recent_data = stock_prices[-30:] if len(stock_prices) >= 30 else stock_prices
            for price in recent_data:
                minimal_history.append({'t': price['t'], 'c': price['c'], 'v': price['v']})
            
            historical_stocks.append({
                's': ticker,
                'h': minimal_history,
                'u': datetime.now().isoformat(),
                'i': ipo_date,
                'd': days_available
            })
            
            processed += 1
            time.sleep(0.5)
            
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            failed += 1
            continue
    
    print()
    print("="*80)
    print("PROCESSING COMPLETE")
    print("="*80)
    print(f"Successfully processed: {processed} stocks")
    print(f"  Full calculations (252+ days): {full_calculations}")
    print(f"  Partial calculations (<252 days): {partial_calculations}")
    print(f"Failed (errors): {failed}")
    print(f"Stage 2 stocks: {stage_2_count} ({stage_2_count/processed*100:.1f}%)")
    print()
    
    # Calculate percentile rankings
    if all_stock_data:
        print("Calculating RS percentile rankings (1-99)...")
        
        all_stock_data.sort(key=lambda x: x['rs_score'], reverse=True)
        
        total_stocks = len(all_stock_data)
        print(f"Total stocks in ranking: {total_stocks}")
        print()
        
        for i, stock in enumerate(all_stock_data):
            percentile = int(((total_stocks - i) / total_stocks) * 99) + 1
            stock['rs_rank'] = min(percentile, 99)
        
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
                'ma_50': stock.get('ma_50'),
                'ma_150': stock.get('ma_150'),
                'ma_200': stock.get('ma_200'),
                'is_stage_2': stock.get('is_stage_2', False)
            })
        
        # Save rankings
        rankings_output = {
            'last_updated': datetime.now().isoformat(),
            'formula_used': 'Flexible: Adapts to available data (see documentation)',
            'stage_2_criteria': '50dma > 150dma > 200dma',
            'total_stocks': len(output_data),
            'full_calculations': full_calculations,
            'partial_calculations': partial_calculations,
            'stage_2_stocks': stage_2_count,
            'update_type': 'full_rebuild',
            'note': 'Includes stocks with <252 days. Check is_partial field.',
            'data': output_data
        }
        
        with open('rankings.json', 'w') as f:
            json.dump(rankings_output, f, indent=2)
        
        print(f"✅ Saved {len(output_data)} stocks to 'rankings.json'")
        
        # Save historical data
        historical_output = {
            'u': datetime.now().isoformat(),
            'n': len(historical_stocks),
            'd': historical_stocks
        }
        
        with open('historical_data.json', 'w') as f:
            json.dump(historical_output, f, indent=2)
        
        print(f"✅ Historical data saved ({len(historical_stocks)} stocks)")
        print()
        
        # Show top 20
        print("="*100)
        print("🏆 TOP 20 RS RANKINGS")
        print("="*100)
        print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'Days':<6} {'Partial':<8} {'Stage2':<7} {'3M Ret':<8} {'12M Ret':<9}")
        print("-" * 100)
        
        for i, stock in enumerate(output_data[:20]):
            partial_flag = "Yes" if stock['is_partial'] else "No"
            stage2_flag = "✓" if stock['is_stage_2'] else " "
            print(f"{i+1:<5} {stock['symbol']:<8} {stock['rs_rank']:<4} {stock['days_of_data']:<6} {partial_flag:<8} {stage2_flag:^7} {stock['stock_return_3m']:<8} {stock['stock_return_12m']:<9}")
        
        print()
        
        # Show recent IPOs
        recent_ipos = [s for s in output_data if s['is_partial']]
        if recent_ipos:
            print("="*90)
            print(f"🆕 RECENT IPOs (<252 days of data): {len(recent_ipos)} stocks")
            print("="*90)
            print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'Days':<6} {'IPO Date':<12} {'3M Ret':<8}")
            print("-" * 90)
            
            for i, stock in enumerate(recent_ipos[:20]):
                ipo = stock.get('ipo_date', 'N/A')[:10]
                print(f"{i+1:<5} {stock['symbol']:<8} {stock['rs_rank']:<4} {stock['days_of_data']:<6} {ipo:<12} {stock['stock_return_3m']:<8}")
            
            print()
        
        # Statistics
        print("="*80)
        print("📊 STATISTICS")
        print("="*80)
        print(f"Total stocks ranked: {len(output_data)}")
        print(f"Full calculations: {full_calculations} ({full_calculations/len(output_data)*100:.1f}%)")
        print(f"Partial calculations: {partial_calculations} ({partial_calculations/len(output_data)*100:.1f}%)")
        print(f"Stocks in Stage 2: {stage_2_count} ({stage_2_count/len(output_data)*100:.1f}%)")
        print()
        
    else:
        print("❌ No stock data processed!")
    
    print("="*80)
    print(f"✅ COMPLETED at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

if __name__ == "__main__":
    main()
