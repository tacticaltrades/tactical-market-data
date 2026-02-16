"""
UPDATED: process_stocks.py (FLEXIBLE RS CALCULATION + ADR/ATR)
Now includes stocks with <252 days of data (recent IPOs)
Calculates RS using whatever historical data is available
Includes ADR (Average Daily Range) and ATR (Average True Range)

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
        'type': 'CS, ADRC',
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

def calculate_adr(stock_prices: List[Dict], period: int = 20) -> Optional[float]:
    """Calculate Average Daily Range (ADR) over specified period
    
    ADR = Average of (High - Low) over last N days
    Useful for identifying volatility and setting position sizes
    """
    if len(stock_prices) < period:
        return None
    
    # Get the last N days
    recent_prices = stock_prices[-period:]
    
    # Calculate daily ranges
    daily_ranges = []
    for bar in recent_prices:
        if 'h' in bar and 'l' in bar:
            daily_range = bar['h'] - bar['l']
            daily_ranges.append(daily_range)
    
    if not daily_ranges:
        return None
    
    return np.mean(daily_ranges)

def calculate_atr(stock_prices: List[Dict], period: int = 14) -> Optional[float]:
    """Calculate Average True Range (ATR) over specified period
    
    ATR accounts for gaps by using True Range:
    TR = max(high - low, |high - prev_close|, |low - prev_close|)
    
    More accurate than ADR for stocks with gaps
    """
    if len(stock_prices) < period + 1:  # Need at least period+1 for prev_close
        return None
    
    true_ranges = []
    
    # Start from index 1 since we need previous close
    for i in range(1, len(stock_prices)):
        current = stock_prices[i]
        previous = stock_prices[i - 1]
        
        if 'h' in current and 'l' in current and 'c' in previous:
            high = current['h']
            low = current['l']
            prev_close = previous['c']
            
            # True Range = max of three values
            tr = max(
                high - low,                    # Current range
                abs(high - prev_close),        # Gap up
                abs(low - prev_close)          # Gap down
            )
            
            true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return None
    
    # Return average of last N true ranges
    return np.mean(true_ranges[-period:])

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
        '2m': min(42, days_available),
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
    print("IBD-Style RS Calculator (FLEXIBLE - Includes Recent IPOs + ADR/ATR)")
    print("="*80)
    print()
    print("Formula adapts to available data:")
    print("  252+ days: 0.4×3m + 0.2×6m + 0.2×9m + 0.2×12m")
    print("  189-251 days: 0.5×3m + 0.25×6m + 0.25×9m")
    print("  126-188 days: 0.6×3m + 0.4×6m")
    print("  63-125 days: 3m return only")
    print("  10-62 days: Total return since listing")
    print()
    print("Volatility Metrics:")
    print("  ADR (20-day): Average Daily Range")
    print("  ATR (14-day): Average True Range (accounts for gaps)")
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
            
            # Calculate ADR and ATR
            adr_20 = calculate_adr(stock_prices, period=20)
            atr_14 = calculate_atr(stock_prices, period=14)
            
            # Get IPO date
            ipo_date = get_ipo_date(ticker)
            
            # Get current price (most recent closing price)
            current_price = round(stock_prices[-1]['c'], 2) if stock_prices else None
            
            # Count Stage 2 stocks
            if ma_data and ma_data['is_stage_2']:
                stage_2_count += 1
            
            all_stock_data.append({
                'symbol': ticker,
                'rs_score': rs_score,
                'avg_volume': int(avg_volume),
                'stock_return_2m': stock_returns.get('2m', 0),
                'stock_return_3m': stock_returns.get('3m', 0),
                'stock_return_6m': stock_returns.get('6m', 0),
                'stock_return_9m': stock_returns.get('9m', 0),
                'stock_return_12m': stock_returns.get('12m', 0),
                'days_of_data': days_available,
                'is_partial': is_partial,
                'ipo_date': ipo_date,
                'current_price': current_price,
                'ma_50': ma_data['ma_50'] if ma_data else None,
                'ma_150': ma_data['ma_150'] if ma_data else None,
                'ma_200': ma_data['ma_200'] if ma_data else None,
                'is_stage_2': ma_data['is_stage_2'] if ma_data else False,
                'adr_20': round(adr_20, 2) if adr_20 is not None else None,
                'atr_14': round(atr_14, 2) if atr_14 is not None else None
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
                'adr_20': stock.get('adr_20'),  # Average Daily Range (20-day)
                'atr_14': stock.get('atr_14')   # Average True Range (14-day)
            })
        
        # Save rankings
        rankings_output = {
            'last_updated': datetime.now().isoformat(),
            'formula_used': 'Flexible: Adapts to available data (see documentation)',
            'stage_2_criteria': '50dma > 150dma > 200dma',
            'volatility_metrics': 'ADR (20-day), ATR (14-day)',
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
        print("="*110)
        print("🏆 TOP 20 RS RANKINGS")
        print("="*110)
        print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'Days':<6} {'Part':<5} {'S2':<4} {'ADR':<7} {'ATR':<7} {'3M Ret':<8} {'12M Ret':<9}")
        print("-" * 110)
        
        for i, stock in enumerate(output_data[:20]):
            partial_flag = "Y" if stock['is_partial'] else "N"
            stage2_flag = "✓" if stock['is_stage_2'] else " "
            adr_str = f"${stock['adr_20']}" if stock['adr_20'] else "N/A"
            atr_str = f"${stock['atr_14']}" if stock['atr_14'] else "N/A"
            print(f"{i+1:<5} {stock['symbol']:<8} {stock['rs_rank']:<4} {stock['days_of_data']:<6} {partial_flag:^5} {stage2_flag:^4} {adr_str:<7} {atr_str:<7} {stock['stock_return_3m']:<8} {stock['stock_return_12m']:<9}")
        
        print()
        
        # Show high volatility stocks (high ADR/ATR)
        stocks_with_adr = [s for s in output_data if s['adr_20'] is not None]
        if stocks_with_adr:
            high_volatility = sorted(stocks_with_adr, key=lambda x: x['adr_20'], reverse=True)[:20]
            print("="*100)
            print("🔥 TOP 20 HIGHEST VOLATILITY (ADR)")
            print("="*100)
            print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'ADR':<8} {'ATR':<8} {'Price':<8} {'Stage2':<7}")
            print("-" * 100)
            
            for i, stock in enumerate(high_volatility):
                stage2_flag = "✓" if stock['is_stage_2'] else " "
                price = f"${stock['current_price']}" if stock['current_price'] else "N/A"
                print(f"{i+1:<5} {stock['symbol']:<8} {stock['rs_rank']:<4} ${stock['adr_20']:<7} ${stock['atr_14']:<7} {price:<8} {stage2_flag:^7}")
            
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
        stocks_with_volatility = len([s for s in output_data if s['adr_20'] is not None])
        print(f"Stocks with ADR/ATR data: {stocks_with_volatility} ({stocks_with_volatility/len(output_data)*100:.1f}%)")
        print()
        
    else:
        print("❌ No stock data processed!")
    
    print("="*80)
    print(f"✅ COMPLETED at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

if __name__ == "__main__":
    main()
