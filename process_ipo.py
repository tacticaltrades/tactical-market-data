"""
IPO Date Pipeline: process_ipo.py
Fetches IPO dates from FMP's IPO calendar endpoint.
Saves ipo_dates.json — a symbol-to-date lookup consumed by process_stocks.py.

Uses /stable/ endpoints (Premium plan). Falls back to /api/v3/ if needed.
Fetches last 2 years of IPOs in 90-day windows. Merges with existing data.

Usage:
    python process_ipo.py
    python process_ipo.py --lookback-days 365
    python process_ipo.py --window-days 60
"""

import os
import json
import re
import requests
import time
import argparse
from datetime import datetime, timedelta
from typing import Dict, Optional

# Configuration
API_KEY = os.environ.get('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com'
RATE_DELAY = 0.25  # seconds between API calls

# Symbol filter: 1-5 uppercase letters, no dots/hyphens (common stocks only)
VALID_SYMBOL_RE = re.compile(r'^[A-Z]{1,5}$')

# Endpoints to try (FMP naming is inconsistent)
IPO_ENDPOINTS = [
    '/stable/ipo-calendar',
    '/stable/ipos-calendar',
    '/stable/ipo_calendar',
    '/stable/ipo-calendar-confirmed',
    '/api/v3/ipo_calendar',
]


def fmp_get(path: str, params: Optional[Dict] = None, timeout: int = 30):
    """Make a GET request to FMP. Returns parsed JSON or None."""
    if params is None:
        params = {}
    params['apikey'] = API_KEY

    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if not resp.ok:
            return None
        data = resp.json()
        # FMP sometimes returns error objects instead of arrays
        if isinstance(data, dict) and 'Error Message' in data:
            return None
        return data
    except Exception:
        return None


def discover_endpoint() -> Optional[str]:
    """Try each endpoint variant with a small test request. Return the first that works."""
    today = datetime.now()
    test_from = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    test_to = today.strftime('%Y-%m-%d')

    print("Discovering working IPO endpoint...")
    for endpoint in IPO_ENDPOINTS:
        data = fmp_get(endpoint, {'from': test_from, 'to': test_to})
        if isinstance(data, list):
            # Check if it looks like IPO data (has symbol and date fields)
            if len(data) == 0:
                # Empty list could be valid (no IPOs in test window) — try with wider range
                wider_from = (today - timedelta(days=180)).strftime('%Y-%m-%d')
                data = fmp_get(endpoint, {'from': wider_from, 'to': test_to})
                time.sleep(RATE_DELAY)

            if isinstance(data, list) and len(data) > 0:
                sample = data[0]
                if 'symbol' in sample and ('date' in sample or 'ipoDate' in sample):
                    print(f"  Found working endpoint: {endpoint} ({len(data)} results in test)")
                    return endpoint
            elif isinstance(data, list) and len(data) == 0:
                # Endpoint responded with empty list — might work, keep trying others first
                print(f"  {endpoint}: responded but empty (will use as fallback)")
                continue
        else:
            print(f"  {endpoint}: not available")
        time.sleep(RATE_DELAY)

    # Second pass: accept endpoints that returned empty lists
    for endpoint in IPO_ENDPOINTS:
        data = fmp_get(endpoint, {'from': test_from, 'to': test_to})
        if isinstance(data, list):
            print(f"  Using fallback endpoint: {endpoint}")
            return endpoint
        time.sleep(RATE_DELAY)

    return None


def is_us_common_stock(symbol: str) -> bool:
    """Filter for US common stocks only (same rules as process_stocks.py)."""
    if not symbol:
        return False
    sym = symbol.strip().upper()
    return bool(VALID_SYMBOL_RE.match(sym))


def fetch_ipo_calendar(endpoint: str, lookback_days: int, window_days: int) -> Dict[str, str]:
    """Fetch IPO calendar in windows over the lookback period.
    Returns {symbol: ipo_date_str} dict."""
    all_ipos: Dict[str, str] = {}
    today = datetime.now()
    start = today - timedelta(days=lookback_days)

    windows_total = 0
    windows_ok = 0
    windows_empty = 0
    windows_failed = 0

    window_start = start
    while window_start < today:
        window_end = min(window_start + timedelta(days=window_days - 1), today)
        from_str = window_start.strftime('%Y-%m-%d')
        to_str = window_end.strftime('%Y-%m-%d')
        windows_total += 1

        data = fmp_get(endpoint, {'from': from_str, 'to': to_str})
        if isinstance(data, list):
            count = 0
            for entry in data:
                sym = (entry.get('symbol') or '').strip().upper()
                # FMP may use 'date' or 'ipoDate'
                date_str = entry.get('date') or entry.get('ipoDate') or ''
                if sym and date_str and is_us_common_stock(sym):
                    # Keep earliest IPO date if symbol appears multiple times
                    if sym not in all_ipos or date_str < all_ipos[sym]:
                        all_ipos[sym] = date_str
                        count += 1
            if count > 0:
                windows_ok += 1
            else:
                windows_empty += 1
        else:
            windows_failed += 1

        window_start = window_end + timedelta(days=1)
        time.sleep(RATE_DELAY)

    print(f"  Fetched {windows_total} windows: {windows_ok} with data, {windows_empty} empty, {windows_failed} failed")
    return all_ipos


def load_existing_lookup() -> Dict[str, str]:
    """Load previous ipo_dates.json if it exists."""
    if not os.path.exists('ipo_dates.json'):
        return {}
    try:
        with open('ipo_dates.json', 'r') as f:
            data = json.load(f)
        existing = data.get('data', {})
        print(f"  Loaded {len(existing)} existing IPO dates from ipo_dates.json")
        return existing
    except Exception as e:
        print(f"  Warning: Could not load existing ipo_dates.json: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description='Fetch IPO dates from FMP')
    parser.add_argument('--lookback-days', type=int, default=730, help='Days to look back (default: 730 = ~2 years)')
    parser.add_argument('--window-days', type=int, default=90, help='Size of each fetch window in days (default: 90)')
    args = parser.parse_args()

    print("=" * 60)
    print("IPO DATE PIPELINE")
    print("=" * 60)
    print(f"  API key present: {bool(API_KEY)}")
    print(f"  Lookback: {args.lookback_days} days")
    print(f"  Window size: {args.window_days} days")
    print()

    if not API_KEY:
        print("ERROR: FMP_API_KEY environment variable not set.")
        return

    # Step 1: Find a working endpoint
    endpoint = discover_endpoint()
    if not endpoint:
        print()
        print("ERROR: No working IPO endpoint found. Tried:")
        for ep in IPO_ENDPOINTS:
            print(f"  - {ep}")
        print()
        print("The FMP Premium plan may not include IPO calendar endpoints.")
        print("Exiting without error (ipo_dates.json unchanged).")
        return

    print()

    # Step 2: Fetch IPO data in windows
    print(f"Fetching IPO dates ({args.lookback_days} days, {args.window_days}-day windows)...")
    fresh_ipos = fetch_ipo_calendar(endpoint, args.lookback_days, args.window_days)
    print(f"  Found {len(fresh_ipos)} US common stock IPOs from API")
    print()

    # Step 3: Merge with existing data
    print("Merging with existing data...")
    existing = load_existing_lookup()
    # Fresh data wins for overlapping symbols
    merged = {**existing, **fresh_ipos}

    # Step 4: Prune entries older than lookback period
    cutoff = (datetime.now() - timedelta(days=args.lookback_days)).strftime('%Y-%m-%d')
    before_prune = len(merged)
    merged = {sym: date for sym, date in merged.items() if date >= cutoff}
    pruned = before_prune - len(merged)
    if pruned:
        print(f"  Pruned {pruned} entries older than {cutoff}")
    print(f"  Final count: {len(merged)} IPO dates")
    print()

    # Step 5: Save
    output = {
        'last_updated': datetime.now().isoformat(),
        'total_symbols': len(merged),
        'data': dict(sorted(merged.items(), key=lambda x: x[1], reverse=True)),  # newest first
    }

    with open('ipo_dates.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Saved {len(merged)} IPO dates to ipo_dates.json")

    # Print a sample
    if merged:
        sample = list(merged.items())[:10]
        print()
        print("Sample (newest first):")
        for sym, date in sample:
            print(f"  {sym}: {date}")


if __name__ == '__main__':
    main()
