#!/usr/bin/env python3
"""
Fetch IPO dates from FMP /stable/ipos-calendar and save to ipo_dates.json.
This file is consumed by process_stocks.py to populate ipo_date on stocks.
Also updates recent_ipos.json with stocks that IPO'd in the last 2 years.

Usage:
    python process_ipo.py

Requires:
    FMP_API_KEY environment variable
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


FMP_API_KEY = os.environ.get('FMP_API_KEY', '')
FMP_BASE = 'https://financialmodelingprep.com/stable'
RATE_DELAY = 0.25  # seconds between requests


def fmp_get(path: str, params: dict = None) -> list | dict | None:
    """Fetch from FMP API with rate limiting."""
    url = f"{FMP_BASE}{path}?apikey={FMP_API_KEY}"
    if params:
        for k, v in params.items():
            url += f"&{k}={v}"

    try:
        req = Request(url, headers={'User-Agent': 'TacticalTrades/1.0'})
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        time.sleep(RATE_DELAY)
        return data
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        print(f"  Error fetching {path}: {e}")
        time.sleep(RATE_DELAY)
        return None


def fetch_ipo_calendar(from_date: str, to_date: str) -> list:
    """Fetch IPO calendar for a date range."""
    print(f"  Fetching IPOs from {from_date} to {to_date}...")
    data = fmp_get('/ipos-calendar', {'from': from_date, 'to': to_date})
    if data and isinstance(data, list):
        print(f"    Got {len(data)} IPOs")
        return data
    return []


def main():
    if not FMP_API_KEY:
        print("ERROR: FMP_API_KEY environment variable not set")
        sys.exit(1)

    print("=== IPO Pipeline ===")
    print(f"Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Fetch IPOs for the last 3 years in 6-month chunks
    # FMP may limit date range per request
    all_ipos = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3 * 365)

    # Process in 6-month chunks
    chunk_start = start_date
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=180), end_date)
        from_str = chunk_start.strftime('%Y-%m-%d')
        to_str = chunk_end.strftime('%Y-%m-%d')

        ipos = fetch_ipo_calendar(from_str, to_str)
        all_ipos.extend(ipos)
        chunk_start = chunk_end + timedelta(days=1)

    print(f"\nTotal IPOs fetched: {len(all_ipos)}")

    # Build IPO date lookup: symbol -> ipo_date
    ipo_lookup = {}
    for ipo in all_ipos:
        symbol = ipo.get('symbol', '').strip().upper()
        date = ipo.get('date', '') or ipo.get('ipoDate', '') or ipo.get('effectivenessDate', '')
        if symbol and date:
            # Keep the earliest date if duplicates
            if symbol not in ipo_lookup or date < ipo_lookup[symbol]:
                ipo_lookup[symbol] = date

    print(f"Unique symbols with IPO dates: {len(ipo_lookup)}")

    # Also try /stable/ipos-prospectus for additional data
    print("\nFetching IPO prospectus data...")
    prospectus_ipos = []
    chunk_start = start_date
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=180), end_date)
        from_str = chunk_start.strftime('%Y-%m-%d')
        to_str = chunk_end.strftime('%Y-%m-%d')

        data = fmp_get('/ipos-prospectus', {'from': from_str, 'to': to_str})
        if data and isinstance(data, list):
            prospectus_ipos.extend(data)
            print(f"    {from_str} to {to_str}: {len(data)} prospectus entries")
        chunk_start = chunk_end + timedelta(days=1)

    # Merge prospectus dates (fill gaps)
    added_from_prospectus = 0
    for ipo in prospectus_ipos:
        symbol = (ipo.get('symbol') or '').strip().upper()
        date = ipo.get('ipoDate', '') or ipo.get('filedDate', '') or ipo.get('effectivenessDate', '')
        if symbol and date and symbol not in ipo_lookup:
            ipo_lookup[symbol] = date
            added_from_prospectus += 1

    print(f"Added {added_from_prospectus} new symbols from prospectus data")
    print(f"Final IPO date count: {len(ipo_lookup)}")

    # Load existing ipo_dates.json and merge (preserve older data)
    existing_lookup = {}
    if os.path.exists('ipo_dates.json'):
        try:
            with open('ipo_dates.json', 'r') as f:
                existing = json.load(f)
            existing_lookup = existing.get('data', {})
            print(f"\nLoaded {len(existing_lookup)} existing IPO dates")
        except Exception as e:
            print(f"Warning: Could not load existing ipo_dates.json: {e}")

    # Merge: new data takes priority
    merged = {**existing_lookup, **ipo_lookup}
    print(f"Merged total: {len(merged)} IPO dates")

    # Save ipo_dates.json (consumed by process_stocks.py)
    output = {
        'last_updated': datetime.now().isoformat(),
        'count': len(merged),
        'data': merged
    }
    with open('ipo_dates.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Saved {len(merged)} IPO dates to ipo_dates.json")

    # Now build recent_ipos.json by cross-referencing with rankings.json
    # This gives us the full stock data for IPOs that are in our screener
    if os.path.exists('rankings.json'):
        try:
            with open('rankings.json', 'r') as f:
                rankings = json.load(f)
            stocks = rankings.get('data', [])

            two_years_ago = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
            recent_ipo_stocks = []

            for stock in stocks:
                sym = stock.get('symbol', '')
                ipo_date = merged.get(sym, stock.get('ipo_date'))

                if ipo_date and ipo_date >= two_years_ago:
                    stock_entry = dict(stock)  # copy
                    stock_entry['ipo_date'] = ipo_date
                    recent_ipo_stocks.append(stock_entry)

            # Sort by IPO date, newest first
            recent_ipo_stocks.sort(key=lambda x: x.get('ipo_date', ''), reverse=True)

            ipo_output = {
                'last_updated': datetime.now().isoformat(),
                'total_stocks': len(recent_ipo_stocks),
                'update_type': 'ipo_pipeline',
                'data': recent_ipo_stocks
            }
            with open('recent_ipos.json', 'w') as f:
                json.dump(ipo_output, f)
            print(f"\nSaved {len(recent_ipo_stocks)} recent IPO stocks to recent_ipos.json")

        except Exception as e:
            print(f"Warning: Could not process rankings.json: {e}")
    else:
        print("\nrankings.json not found — skipping recent_ipos.json generation")

    print(f"\nCompleted at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    main()
