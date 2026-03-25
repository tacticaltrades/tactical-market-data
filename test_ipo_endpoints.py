"""
Temporary script to test which FMP IPO endpoints return data.
Tests each endpoint with a sample request and prints the response.
Delete after testing.
"""

import os
import json
import requests
import time

API_KEY = os.environ.get('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com'

ENDPOINTS_TO_TEST = [
    # IPO Calendar variants
    '/stable/ipo-calendar',
    '/stable/ipos-calendar',
    '/stable/ipo_calendar',
    '/stable/ipo-calendar-confirmed',
    '/stable/ipos-confirmed',
    # IPO Prospectus / Disclosure
    '/stable/ipo-prospectus',
    '/stable/ipo_prospectus',
    '/stable/ipo-disclosure',
    '/stable/ipo_disclosure',
    '/stable/ipos-prospectus',
    '/stable/ipos-disclosure',
    # v3/v4 fallbacks
    '/api/v3/ipo_calendar',
    '/api/v3/ipo-calendar',
    '/api/v4/ipo-calendar-prospectus',
    '/api/v4/ipo-calendar-confirmation',
    # Stock list / profile (check if ipoDate exists)
    '/stable/stock-list',
    '/stable/profile',
]

def test_endpoint(path, params=None):
    if params is None:
        params = {}
    params['apikey'] = API_KEY
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=15)
        print(f"  Status: {resp.status_code}")
        if not resp.ok:
            print(f"  Error: {resp.text[:200]}")
            return None
        data = resp.json()
        if isinstance(data, dict) and 'Error Message' in data:
            print(f"  Error: {data['Error Message'][:200]}")
            return None
        return data
    except Exception as e:
        print(f"  Exception: {e}")
        return None


def main():
    print("=" * 70)
    print("FMP IPO ENDPOINT TESTER")
    print("=" * 70)
    print(f"API key present: {bool(API_KEY)}")
    print()

    if not API_KEY:
        print("ERROR: FMP_API_KEY not set")
        return

    for endpoint in ENDPOINTS_TO_TEST:
        print(f"\n{'='*70}")
        print(f"TESTING: {endpoint}")
        print(f"{'='*70}")

        # Choose params based on endpoint type
        if 'stock-list' in endpoint:
            print("  Params: none (checking first 5 entries for ipoDate field)")
            data = test_endpoint(endpoint)
            if isinstance(data, list) and data:
                print(f"  Returned: {len(data)} entries")
                # Check first 5 for ipoDate
                has_ipo = 0
                for entry in data[:20]:
                    ipo = entry.get('ipoDate') or entry.get('ipo_date')
                    if ipo:
                        has_ipo += 1
                print(f"  ipoDate present in first 20: {has_ipo}/20")
                # Show a sample with ipoDate
                for entry in data[:200]:
                    ipo = entry.get('ipoDate') or entry.get('ipo_date')
                    if ipo:
                        print(f"  Sample: {entry.get('symbol')} -> ipoDate={ipo}")
                        print(f"  Fields: {list(entry.keys())}")
                        break
            elif isinstance(data, list):
                print("  Returned: empty list")
            else:
                print(f"  Returned: {type(data)}")

        elif 'profile' in endpoint:
            print("  Params: symbol=AAPL (checking for ipoDate)")
            data = test_endpoint(endpoint, {'symbol': 'AAPL'})
            if isinstance(data, list) and data:
                entry = data[0]
                ipo = entry.get('ipoDate') or entry.get('ipo_date')
                print(f"  AAPL ipoDate: {ipo}")
                print(f"  Fields: {list(entry.keys())}")
            else:
                print(f"  Returned: {type(data)} (empty or error)")

        else:
            # IPO calendar/prospectus/disclosure endpoints
            print("  Params: from=2024-01-01, to=2026-03-25")
            data = test_endpoint(endpoint, {'from': '2024-01-01', 'to': '2026-03-25'})
            if isinstance(data, list) and data:
                print(f"  Returned: {len(data)} entries")
                sample = data[0]
                print(f"  Fields: {list(sample.keys())}")
                print(f"  Sample: {json.dumps(sample, indent=2)[:500]}")
                # Check how far back data goes
                dates = [e.get('date') or e.get('ipoDate') or '' for e in data if e.get('date') or e.get('ipoDate')]
                if dates:
                    print(f"  Date range: {min(dates)} to {max(dates)}")
                    print(f"  Unique symbols: {len(set(e.get('symbol','') for e in data))}")
            elif isinstance(data, list):
                print("  Returned: empty list")
            else:
                print(f"  Returned: {type(data)}")

        time.sleep(0.3)

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == '__main__':
    main()
