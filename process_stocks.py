"""
CORRECTED: process_stocks.py
Weekly Stock Data Collection Script + Recent IPO Tracking + Stage 2 Calculation
Fetches 12 months of historical data for all common stocks to calculate RS scores

CRITICAL FIX: Now uses CORRECT IBD formula (absolute returns, NOT relative to S&P 500)
Formula: RS = 0.4 × ROC(63) + 0.2 × ROC(126) + 0.2 × ROC(189) + 0.2 × ROC(252)
Where ROC = (Current Price - Past Price) / Past Price (ABSOLUTE RETURN)

Stage 2: 50dma > 150dma > 200dma
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
BASE_URL = 'https://api.polygon.io'

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
    """Fetch stocks that IPOed in the last 2 years using Massive IPO endpoint"""
    print("\n=== Fetching Recent IPOs (Last 2 Years) ===")
    
    # Calculate date 2 years ago
    two_years_ago = datetime.now() - timedelta(days=730)
    date_filter = two_years_ago.strftime('%Y-%m-%d')
    
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
                print(f"  Page {page}: Found {len(data['results'])} IPO records")
                
                for ipo_data in data['results']:
                    announced = ipo_data.get('announced_date')
                    if announced:
                        try:
                            ipo_date = datetime.strptime(announced, '%Y-%m-%d')
                            days_ago = (datetime.now() - ipo_date).days
                            
                            if 0 <= days_ago <= 730:
                                recent_ipos.append({
                                    'ticker': ipo_data.get('ticker'),
                                    'name': ipo_data.get('issuer_name', 'N/A'),
                                    'list_date': announced,
                                    'ipo_price': ipo_data.get('final_issue_price'),
                                    'ipo_status': ipo_data.get('ipo_status', 'unknown')
                                })
                        except (ValueError, TypeError):
                            continue
            
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
    
    print(f"✅ Found {len(recent_ipos)} IPOs in last 2 years")
    return recent_ipos

def get_current_price_and_volume(ticker: str) -> Optional[Dict]:
    """Get current price and recent volume for a ticker"""
    try:
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
            current_price = bars[0]['c']
            volumes = [bar['v'] for bar in bars]
            avg_volume = np.mean(volumes) if volumes else 0
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

def process_recent_ipos(recent_ipos: List[Dict]) -> List[Dict]:
    """Process recent IPO data to get current prices and stats"""
    print("\nProcessing recent IPO data...")
    
    processed_ipos = []
    
    for i, ipo in enumerate(recent_ipos):
        ticker = ipo['ticker']
        
        try:
            if i % 20 == 0:
                print(f"  Progress: {i}/{len(recent_ipos)}")
            
            if not ipo.get('list_date'):
                continue
            
            try:
                ipo_date = datetime.strptime(ipo['list_date'], '%Y-%m-%d')
            except (ValueError, TypeError):
                continue
            
            days_since_ipo = (datetime.now() - ipo_date).days
            
            price_data = get_current_price_and_volume(ticker)
            
            if price_data and price_data['has_data']:
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
            
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  Error processing {ticker}: {e}")
            continue
    
    print(f"✅ Processed {len(processed_ipos)} recent IPOs with data")
    return processed_ipos

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

def calculate_moving_averages(stock_prices: List[Dict]) -> Optional[Dict]:
    """Calculate 50-day, 150-day, and 200-day moving averages and Stage 2 status"""
    if len(stock_prices) < 200:
        return None
    
    closes = [bar['c'] for bar in stock_prices]
    
    ma_50 = np.mean(closes[-50:])
    ma_150 = np.mean(closes[-150:])
    ma_200 = np.mean(closes[-200:])
    
    # Stage 2: 50dma > 150dma > 200dma
    is_stage_2 = bool((ma_50 > ma_150) and (ma_150 > ma_200))
    
    return {
        'ma_50': round(ma_50, 2),
        'ma_150': round(ma_150, 2),
        'ma_200': round(ma_200, 2),
        'is_stage_2': is_stage_2
    }

def calculate_stock_returns(stock_prices: List[Dict]) -> Tuple[Optional[Dict], float]:
    """Calculate absolute returns for stock (NO BENCHMARK COMPARISON)
    
    This is the CORRECT method - IBD ranks stocks by absolute performance,
    NOT performance relative to S&P 500
    """
    if not stock_prices or len(stock_prices) < 252:
        return None, 0
    
    # Calculate periods (approximate trading days)
    periods = {
        '3m': 63,   # ~3 months (most recent quarter)
        '6m': 126,  # ~6 months
        '9m': 189,  # ~9 months
        '12m': 252  # ~12 months
    }
    
    stock_returns = {}
    
    for period_name, days in periods.items():
        ret = calculate_return(stock_prices, days)
        stock_returns[period_name] = ret if ret is not None else 0
    
    # Calculate average volume over last 50 days
    recent_prices = stock_prices[-50:] if len(stock_prices) >= 50 else stock_prices
    volumes = [p['v'] for p in recent_prices if 'v' in p]
    avg_volume = np.mean(volumes) if volumes else 0
    
    return stock_returns, avg_volume

def calculate_ibd_rs_score(stock_returns: Dict) -> float:
    """Calculate IBD-style RS score using CORRECTED formula
    
    CORRECT Formula: RS = 0.4 × ROC(63) + 0.2 × ROC(126) + 0.2 × ROC(189) + 0.2 × ROC(252)
    
    Where:
    - ROC = Rate of Change = (Current Price - Past Price) / Past Price
    - This is ABSOLUTE stock performance, NOT relative to any benchmark
    - 63 days = ~3 months (weighted 40% - most important)
    - 126 days = ~6 months (weighted 20%)
    - 189 days = ~9 months (weighted 20%)
    - 252 days = ~12 months (weighted 20%)
    
    Note: The old formula that compared to S&P 500 was WRONG and caused 10-15 point errors!
    """
    if not stock_returns:
        return 0
    
    rs_score = (
        0.4 * stock_returns.get('3m', 0) +   # 40% weight on recent quarter
        0.2 * stock_returns.get('6m', 0) +   # 20% weight
        0.2 * stock_returns.get('9m', 0) +   # 20% weight
        0.2 * stock_returns.get('12m', 0)    # 20% weight
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

def main():
    print("="*80)
    print("IBD-Style Relative Strength Stock Processor with Stage 2 Analysis")
    print("CORRECTED FORMULA (No S&P 500 comparison)")
    print("="*80)
    print()
    print("Formula: RS = 0.4×ROC(63) + 0.2×ROC(126) + 0.2×ROC(189) + 0.2×ROC(252)")
    print("Where ROC = Absolute stock return (NOT relative to benchmark)")
    print("Stage 2: 50dma > 150dma > 200dma")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if not API_KEY:
        print("ERROR: POLYGON_API_KEY not found!")
        return
    
    # Date range for historical data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=450)  # Extra buffer for weekends/holidays
    
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    
    print(f"Date range: {start_date_str} to {end_date_str}")
    print()
    
    # Get all tickers
    tickers = get_all_tickers()
    if not tickers:
        print("ERROR: Failed to get tickers!")
        return
    
    print(f"\nProcessing {len(tickers)} stocks...")
    print("Note: Stocks with <252 days of history will be skipped")
    print()
    
    all_stock_data = []
    historical_stocks = []
    processed = 0
    failed = 0
    insufficient_data = 0
    stage_2_count = 0
    
    for i, ticker in enumerate(tickers):
        try:
            # Progress indicator every 100 stocks
            if i % 100 == 0 and i > 0:
                print(f"Progress: {i}/{len(tickers)} ({i/len(tickers)*100:.1f}%)")
                print(f"  Processed: {processed}, Failed: {failed}, Insufficient data: {insufficient_data}, Stage 2: {stage_2_count}")
            
            # Get historical data
            stock_prices = get_stock_data(ticker, start_date_str, end_date_str)
            
            if not stock_prices:
                failed += 1
                continue
            
            # Calculate returns (no benchmark needed!)
            result = calculate_stock_returns(stock_prices)
            
            if result[0] is None:
                insufficient_data += 1
                continue
            
            stock_returns, avg_volume = result
            rs_score = calculate_ibd_rs_score(stock_returns)
            
            # Calculate moving averages and Stage 2 status
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
                'stock_return_3m': stock_returns['3m'],
                'stock_return_6m': stock_returns['6m'],
                'stock_return_9m': stock_returns['9m'],
                'stock_return_12m': stock_returns['12m'],
                'ipo_date': ipo_date,
                'ma_50': ma_data['ma_50'] if ma_data else None,
                'ma_150': ma_data['ma_150'] if ma_data else None,
                'ma_200': ma_data['ma_200'] if ma_data else None,
                'is_stage_2': ma_data['is_stage_2'] if ma_data else False
            })
            
            # Store minimal historical data
            minimal_history = []
            
            if len(stock_prices) > 30:
                older_data = stock_prices[:-30:5]
            else:
                older_data = stock_prices[:-10:5] if len(stock_prices) > 10 else stock_prices[:-1:5] if len(stock_prices) > 1 else []
            
            for price in older_data:
                minimal_history.append({
                    't': price['t'],
                    'c': price['c']
                })
            
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
            
            # Rate limiting - 2 calls per second
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
    print(f"Insufficient data (<252 days): {insufficient_data} stocks")
    print(f"Failed (errors): {failed} stocks")
    print(f"Stage 2 stocks: {stage_2_count} ({stage_2_count/processed*100:.1f}% of processed)")
    print()
    
    # Calculate percentile rankings
    if all_stock_data:
        print("Calculating RS percentile rankings (1-99)...")
        
        # Sort by RS score (highest first)
        all_stock_data.sort(key=lambda x: x['rs_score'], reverse=True)
        
        total_stocks = len(all_stock_data)
        print(f"Total stocks in ranking: {total_stocks}")
        
        if total_stocks < 6000:
            print(f"⚠️  WARNING: Only {total_stocks} stocks processed. IBD uses ~8,000 stocks.")
            print(f"   This may cause percentile rankings to differ from IBD by several points.")
            print(f"   Consider investigating why {len(tickers) - total_stocks} stocks failed to process.")
        
        print()
        
        # Assign percentile ranks
        for i, stock in enumerate(all_stock_data):
            # Percentile formula: (number of stocks below this one / total stocks) * 99 + 1
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
                'stock_return_3m': format_return(stock['stock_return_3m']),
                'stock_return_6m': format_return(stock['stock_return_6m']),
                'stock_return_9m': format_return(stock['stock_return_9m']),
                'stock_return_12m': format_return(stock['stock_return_12m']),
                'ipo_date': stock.get('ipo_date'),
                'ma_50': stock.get('ma_50'),
                'ma_150': stock.get('ma_150'),
                'ma_200': stock.get('ma_200'),
                'is_stage_2': stock.get('is_stage_2', False)
            })
        
        # Save rankings.json
        rankings_output = {
            'last_updated': datetime.now().isoformat(),
            'formula_used': 'RS = 0.4×ROC(63) + 0.2×ROC(126) + 0.2×ROC(189) + 0.2×ROC(252) [CORRECTED - No S&P 500 comparison]',
            'stage_2_criteria': '50dma > 150dma > 200dma',
            'total_stocks': len(output_data),
            'stage_2_stocks': stage_2_count,
            'update_type': 'full_rebuild',
            'note': 'This version uses ABSOLUTE stock returns, not relative to S&P 500. Should match IBD much better.',
            'data': output_data
        }
        
        with open('rankings.json', 'w') as f:
            json.dump(rankings_output, f, indent=2)
        
        print(f"✅ Saved {len(output_data)} stocks to 'rankings.json'")
        
        # Save historical_data.json
        historical_output = {
            'u': datetime.now().isoformat(),
            'n': len(historical_stocks),
            'd': historical_stocks,
            'note': 'No S&P 500 data needed - using absolute returns only'
        }
        
        with open('historical_data.json', 'w') as f:
            json.dump(historical_output, f, indent=2)
        
        print(f"✅ Historical data saved ({len(historical_stocks)} stocks)")
        print()
        
        # Show top 20 performers
        print("="*100)
        print("🏆 TOP 20 RS RANKINGS")
        print("="*100)
        print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'Stage2':<7} {'50MA':<10} {'150MA':<10} {'200MA':<10} {'3M Ret':<8} {'12M Ret':<9} {'Volume':<10}")
        print("-" * 100)
        
        for i, stock in enumerate(output_data[:20]):
            stage2_symbol = "✓" if stock['is_stage_2'] else " "
            ma50 = f"${stock['ma_50']:.2f}" if stock['ma_50'] else "N/A"
            ma150 = f"${stock['ma_150']:.2f}" if stock['ma_150'] else "N/A"
            ma200 = f"${stock['ma_200']:.2f}" if stock['ma_200'] else "N/A"
            print(f"{i+1:<5} {stock['symbol']:<8} {stock['rs_rank']:<4} {stage2_symbol:^7} {ma50:<10} {ma150:<10} {ma200:<10} {stock['stock_return_3m']:<8} {stock['stock_return_12m']:<9} {stock['avg_volume']:<10}")
        
        print()
        
        # Show top Stage 2 stocks
        stage_2_stocks = [s for s in output_data if s['is_stage_2']]
        if stage_2_stocks:
            print("="*90)
            print("📈 TOP 20 STAGE 2 STOCKS")
            print("="*90)
            print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'50MA':<10} {'150MA':<10} {'200MA':<10} {'Volume':<10}")
            print("-" * 90)
            
            for i, stock in enumerate(stage_2_stocks[:20]):
                ma50 = f"${stock['ma_50']:.2f}" if stock['ma_50'] else "N/A"
                ma150 = f"${stock['ma_150']:.2f}" if stock['ma_150'] else "N/A"
                ma200 = f"${stock['ma_200']:.2f}" if stock['ma_200'] else "N/A"
                print(f"{i+1:<5} {stock['symbol']:<8} {stock['rs_rank']:<4} {ma50:<10} {ma150:<10} {ma200:<10} {stock['avg_volume']:<10}")
            
            print()
        
        # Statistics
        rs_scores = [s['rs_score'] for s in all_stock_data]
        print("="*60)
        print("📊 RS SCORE STATISTICS")
        print("="*60)
        print(f"Highest RS Score:        {max(rs_scores):.3f}")
        print(f"Lowest RS Score:         {min(rs_scores):.3f}")
        print(f"Average RS Score:        {np.mean(rs_scores):.3f}")
        print(f"Median RS Score:         {np.median(rs_scores):.3f}")
        print()
        
        high_rs_count = len([s for s in output_data if s['rs_rank'] >= 90])
        print(f"Stocks with RS ≥ 90:     {high_rs_count} ({high_rs_count/len(output_data)*100:.1f}%)")
        print(f"Stocks in Stage 2:       {stage_2_count} ({stage_2_count/len(output_data)*100:.1f}%)")
        print()
        
    else:
        print("❌ No stock data was successfully processed!")
        return
    
    # PROCESS RECENT IPOs
    print("="*80)
    print("PROCESSING RECENT IPOs")
    print("="*80)
    
    recent_ipos = get_recent_ipos()
    
    if recent_ipos:
        processed_ipos = process_recent_ipos(recent_ipos)
        
        # Sort by IPO date (newest first)
        processed_ipos.sort(key=lambda x: x['ipo_date'], reverse=True)
        
        # Save recent_ipos.json
        ipo_output = {
            'last_updated': datetime.now().isoformat(),
            'total_recent_ipos': len(processed_ipos),
            'lookback_days': 730,
            'note': 'Stocks that completed IPO in the last 2 years. May not have RS scores due to insufficient history.',
            'data': processed_ipos
        }
        
        with open('recent_ipos.json', 'w') as f:
            json.dump(ipo_output, f, indent=2)
        
        print(f"✅ Saved {len(processed_ipos)} recent IPOs to 'recent_ipos.json'")
        print()
        
        # Show most recent IPOs
        if processed_ipos:
            print("🆕 MOST RECENT IPOs")
            print("-" * 80)
            print(f"{'Symbol':<8} {'Company':<25} {'IPO Date':<12} {'Days':<6} {'Price':<8} {'Change':<8}")
            print("-" * 80)
            
            for ipo in processed_ipos[:10]:
                change_str = f"{ipo['percent_from_ipo']:+.1f}%" if ipo['percent_from_ipo'] is not None else "N/A"
                company_name = ipo['company_name'][:24]  # Truncate long names
                print(f"{ipo['symbol']:<8} {company_name:<25} {ipo['ipo_date']:<12} {ipo['days_since_ipo']:>4}d  ${ipo['current_price']:>6.2f}  {change_str:>7}")
            
            print()
    else:
        print("⚠️  No IPOs found in the last 2 years")
        print()
    
    print("="*80)
    print(f"✅ COMPLETED at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

if __name__ == "__main__":
    main()
