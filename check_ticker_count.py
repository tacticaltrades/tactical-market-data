"""
Quick Check: How many tickers does Massive.com actually have?
Uses the 'count' attribute from the API response
"""

import os
import requests

API_KEY = os.environ.get('POLYGON_API_KEY')
BASE_URL = 'https://api.polygon.io'

def check_total_ticker_count():
    """Check the total count of tickers available"""
    
    print("="*80)
    print("CHECKING TOTAL TICKER COUNT FROM MASSIVE.COM API")
    print("="*80)
    print()
    
    url = f"{BASE_URL}/v3/reference/tickers"
    
    # Test 1: Common Stocks only (what you're currently using)
    print("TEST 1: Common Stocks (type='CS') - Your current filter")
    print("-" * 80)
    params = {
        'market': 'stocks',
        'type': 'CS',  # Common Stock only
        'active': 'true',
        'limit': 1,  # Only need 1 result to see the count
        'apiKey': API_KEY
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        count = data.get('count')
        print(f"Total Common Stocks (CS) available: {count:,}")
        print()
        
        if count:
            if count < 6000:
                print(f"⚠️  WARNING: Only {count:,} common stocks available")
                print("   This is LESS than IBD's ~8,000 stock universe")
            elif count < 8000:
                print(f"✓ {count:,} stocks is close to IBD's universe")
            else:
                print(f"✓ {count:,} stocks is MORE than IBD's ~8,000")
        
    except Exception as e:
        print(f"ERROR: {e}")
    
    print()
    
    # Test 2: All stock types
    print("TEST 2: All stock types (no type filter)")
    print("-" * 80)
    params2 = {
        'market': 'stocks',
        # No type filter
        'active': 'true',
        'limit': 1,
        'apiKey': API_KEY
    }
    
    try:
        response = requests.get(url, params=params2)
        response.raise_for_status()
        data = response.json()
        
        count = data.get('count')
        print(f"Total stocks (all types) available: {count:,}")
        print()
        
    except Exception as e:
        print(f"ERROR: {e}")
    
    print()
    
    # Test 3: Check what types are available
    print("TEST 3: Breaking down by type")
    print("-" * 80)
    
    types = ['CS', 'ADR', 'ETF', 'ETN', 'REIT', 'PFD', 'FUND', 'RIGHT', 'WARRANT', 'UNIT']
    
    for stock_type in types:
        params3 = {
            'market': 'stocks',
            'type': stock_type,
            'active': 'true',
            'limit': 1,
            'apiKey': API_KEY
        }
        
        try:
            response = requests.get(url, params=params3)
            response.raise_for_status()
            data = response.json()
            
            count = data.get('count', 0)
            print(f"  {stock_type:10} : {count:,}")
            
        except Exception as e:
            print(f"  {stock_type:10} : ERROR")
    
    print()
    print("="*80)
    print("INTERPRETATION")
    print("="*80)
    print()
    print("If Common Stocks (CS) shows ~5,000:")
    print("  → This is the ACTUAL number of active common stocks in the market")
    print("  → IBD likely includes ADRs or other types to reach 8,000")
    print()
    print("If Common Stocks (CS) shows ~8,000+:")
    print("  → Your pagination might be broken (not fetching all pages)")
    print("  → Need to debug the pagination logic")
    print()

if __name__ == "__main__":
    check_total_ticker_count()
