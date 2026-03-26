#!/usr/bin/env python3
"""
process_backfill.py — Backfill extended price history for ranked stocks.

Fetches full OHLCV history from FMP back to FROM_DATE and saves individual
history/{SYMBOL}.json files committed to the repo. The fmp-history edge
function then serves these files as the base, topping up with recent FMP
data so charts go back years without slowing down the daily pipeline.

Does NOT modify: rankings.json, historical_data.json, recent_ipos.json

Usage:
  python process_backfill.py                          # All stocks in rankings.json
  python process_backfill.py --symbols AAPL MSFT NVDA # Specific symbols only
  python process_backfill.py --from-date 2005-01-01   # Override start date
  python process_backfill.py --force                  # Re-fetch all (ignore skip logic)
  python process_backfill.py --limit 500              # Process first N symbols (test run)

Output: history/{SYMBOL}.json per stock
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL        = 'https://financialmodelingprep.com'
API_KEY         = os.environ.get('FMP_API_KEY', '')
RATE_DELAY      = 0.15          # seconds between FMP calls (Premium: ~300 req/min)
HISTORY_DIR     = Path('history')
DEFAULT_FROM    = '2010-01-01'  # ~15 years of history
SKIP_NEWER_DAYS = 30            # Skip stocks whose file was updated within this many days


# ── FMP fetch ─────────────────────────────────────────────────────────────────
def fetch_history(symbol: str, from_date: str, to_date: str) -> list:
    """Fetch full OHLCV bars from FMP. Returns oldest-first list, empty on failure."""
    url = f"{BASE_URL}/stable/historical-price-eod/full"
    params = {'symbol': symbol, 'from': from_date, 'to': to_date, 'apikey': API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # /stable/ returns a flat list; /api/v3/ returns {historical: [...]}
        raw = data if isinstance(data, list) else data.get('historical', [])
        if not raw:
            return []

        bars = []
        for bar in reversed(raw):          # FMP is newest-first → reverse to oldest-first
            if not (bar.get('open') and bar.get('close')):
                continue
            bars.append({
                'time':   bar['date'],                        # YYYY-MM-DD
                'open':   round(float(bar['open']),   4),
                'high':   round(float(bar['high']),   4),
                'low':    round(float(bar['low']),    4),
                'close':  round(float(bar['close']),  4),
                'volume': int(bar.get('volume') or 0),
            })
        return bars

    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return []


# ── Skip logic ────────────────────────────────────────────────────────────────
def should_skip(symbol: str, force: bool) -> bool:
    """Return True if a fresh file already exists and --force was not passed."""
    if force:
        return False
    path = HISTORY_DIR / f"{symbol}.json"
    if not path.exists():
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        updated = data.get('updated', '')
        if updated:
            age_days = (datetime.now() - datetime.fromisoformat(updated)).days
            return age_days < SKIP_NEWER_DAYS
    except Exception:
        pass
    return False


# ── Write ─────────────────────────────────────────────────────────────────────
def save(symbol: str, bars: list):
    HISTORY_DIR.mkdir(exist_ok=True)
    path = HISTORY_DIR / f"{symbol}.json"
    payload = {
        'symbol':  symbol,
        'updated': datetime.now().isoformat(),
        'bars':    bars,
    }
    with open(path, 'w') as f:
        json.dump(payload, f, separators=(',', ':'))


# ── Symbol list ───────────────────────────────────────────────────────────────
def load_symbols() -> list:
    path = Path('rankings.json')
    if not path.exists():
        print("ERROR: rankings.json not found. Run process_stocks.py first.")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    symbols = [s['symbol'] for s in data.get('data', [])]
    if not symbols:
        print("ERROR: No stocks found in rankings.json")
        sys.exit(1)
    return symbols


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Backfill extended price history')
    parser.add_argument('--symbols',   nargs='+', help='Symbols to backfill (default: all in rankings.json)')
    parser.add_argument('--from-date', default=DEFAULT_FROM, help=f'History start date (default: {DEFAULT_FROM})')
    parser.add_argument('--force',     action='store_true', help='Re-fetch even if file is recent')
    parser.add_argument('--limit',     type=int, help='Cap number of symbols processed (useful for test runs)')
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: FMP_API_KEY environment variable not set")
        sys.exit(1)

    to_date = datetime.now().strftime('%Y-%m-%d')
    symbols = args.symbols if args.symbols else load_symbols()
    if args.limit:
        symbols = symbols[:args.limit]

    total = len(symbols)
    print(f"Backfilling {total} stocks  |  {args.from_date} → {to_date}")
    print(f"Output: {HISTORY_DIR.resolve()}")
    print(f"Skip files newer than {SKIP_NEWER_DAYS} days (use --force to override)")
    print()

    done = skipped = 0
    failed = []

    for i, symbol in enumerate(symbols, 1):
        if should_skip(symbol, args.force):
            skipped += 1
            continue

        print(f"[{i}/{total}] {symbol:<8}", end=' ', flush=True)
        bars = fetch_history(symbol, args.from_date, to_date)

        if bars:
            save(symbol, bars)
            print(f"{len(bars)} bars  ({bars[0]['time']} → {bars[-1]['time']})")
            done += 1
        else:
            print("no data")
            failed.append(symbol)

        time.sleep(RATE_DELAY)

    print()
    print(f"Done.  {done} fetched  |  {skipped} skipped (recent)  |  {len(failed)} failed")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed[:30])}{'...' if len(failed) > 30 else ''}")


if __name__ == '__main__':
    main()
