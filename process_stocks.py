"""
FULL REBUILD: process_stocks.py (FMP Edition)
Fetches all active US common stocks from Financial Modeling Prep API.
Calculates RS scores, moving averages, ADR, ATR, Stage 2 status.
Includes market cap, industry/sector, IPO date.

Uses /stable/ endpoints (v3/v4 deprecated Aug 2025).
Fetches last 5 years of historical data.

Formula adapts based on data availability:
- 252+ days: Full formula (0.4x3m + 0.2x6m + 0.2x9m + 0.2x12m)
- 189-251 days: 3m, 6m, 9m only (reweighted)
- 126-188 days: 3m, 6m only (reweighted)
- 63-125 days: 3m only
- 10-62 days: Total return since listing
"""

import os
import json
import requests
import time
import sys
import argparse
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Configuration
API_KEY = os.environ.get('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com'
RATE_DELAY = 0.15  # seconds between API calls (FMP Premium: 300 req/min = 5/sec)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fmp_get(path: str, params: Optional[Dict] = None, timeout: int = 30) -> Optional[any]:
    """Make a GET request to FMP. Returns parsed JSON or None."""
    if params is None:
        params = {}
    params['apikey'] = API_KEY

    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if not resp.ok:
            return None
        return resp.json()
    except Exception:
        return None


def test_api_connection() -> bool:
    """Test the API key works by fetching AAPL data. Prints verbose output."""
    print("=" * 60)
    print("API CONNECTION TEST")
    print("=" * 60)
    print(f"  API key present: {bool(API_KEY)}")
    print(f"  API key length: {len(API_KEY) if API_KEY else 0}")
    print()

    # Test 1: /stable/profile
    print("  Test 1: /stable/profile?symbol=AAPL")
    try:
        resp = requests.get(f"{BASE_URL}/stable/profile",
                            params={'symbol': 'AAPL', 'apikey': API_KEY}, timeout=15)
        print(f"    Status: {resp.status_code}")
        if resp.ok:
            data = resp.json()
            if isinstance(data, list) and data:
                print(f"    Result: {data[0].get('companyName', 'N/A')} (OK)")
            else:
                print(f"    Result type: {type(data)}, len: {len(data) if hasattr(data, '__len__') else 'N/A'}")
        else:
            print(f"    Response: {resp.text[:300]}")
    except Exception as e:
        print(f"    Error: {e}")

    print()

    # Test 2: /stable/historical-price-eod/full (correct stable endpoint)
    print("  Test 2: /stable/historical-price-eod/full?symbol=AAPL")
    try:
        resp = requests.get(f"{BASE_URL}/stable/historical-price-eod/full",
                            params={'symbol': 'AAPL', 'from': '2025-01-01',
                                    'to': '2025-03-01', 'apikey': API_KEY}, timeout=15)
        print(f"    Status: {resp.status_code}")
        if resp.ok:
            data = resp.json()
            if isinstance(data, list):
                print(f"    Result: list with {len(data)} items")
                if data:
                    print(f"    First item keys: {list(data[0].keys())[:8]}")
                    print(f"    First item: {data[0]}")
            elif isinstance(data, dict):
                print(f"    Result: dict with keys {list(data.keys())[:8]}")
            else:
                print(f"    Result type: {type(data)}")
        else:
            print(f"    Response: {resp.text[:300]}")
    except Exception as e:
        print(f"    Error: {e}")

    print()

    # Test 5: company screener
    print("  Test 5: /stable/company-screener (NYSE, limit=5)")
    try:
        resp = requests.get(f"{BASE_URL}/stable/company-screener",
                            params={'exchange': 'NYSE', 'isActivelyTrading': 'true',
                                    'isEtf': 'false', 'isFund': 'false',
                                    'limit': 5, 'apikey': API_KEY}, timeout=15)
        print(f"    Status: {resp.status_code}")
        if resp.ok:
            data = resp.json()
            if isinstance(data, list):
                print(f"    Got {len(data)} results")
                for item in data[:3]:
                    print(f"    {item.get('symbol', '?')} - {item.get('companyName', '?')} - exchange: {item.get('exchangeShortName', '?')}")
        else:
            print(f"    Response: {resp.text[:300]}")
    except Exception as e:
        print(f"    Error: {e}")

    print()
    print("=" * 60)
    print()
    return True


# ---------------------------------------------------------------------------
# Stock list
# ---------------------------------------------------------------------------

def is_common_stock(s: Dict) -> bool:
    """Filter to common stocks only. Exclude ETFs, funds, warrants, preferred, etc."""
    sym = s.get('symbol', '')
    if not sym or len(sym) > 5:
        return False

    # Dots indicate foreign shares (BRK.B exception handled by exchange filter)
    if '.' in sym:
        return False

    # Hyphens indicate preferred shares, warrants, units (e.g. AAPL-W, XYZ-PA)
    if '-' in sym:
        return False

    # NOTE: We do NOT filter by single-letter suffix (W/R/U) because it
    # incorrectly excludes real stocks like PLTR, SNOW, NKTR, FOUR, MANU, GURU.
    # The hyphen check above already catches actual warrants/rights/units on
    # major US exchanges (formatted as AAPL-W, XYZ-R, ABC-U).

    # Check type field if available
    stock_type = (s.get('type') or '').lower()
    for excluded in ('etf', 'fund', 'trust', 'warrant', 'right', 'preferred', 'unit'):
        if excluded in stock_type:
            return False

    return True


def get_all_tickers() -> Tuple[List[str], Dict[str, Dict]]:
    """Fetch all active US common stocks from FMP.
    Returns (symbol_list, profiles_dict)."""
    print("Fetching US common stocks from FMP...")

    all_stocks = []
    profiles = {}
    stock_data = []

    us_exchanges = {'NYSE', 'NASDAQ', 'AMEX', 'New York Stock Exchange',
                    'NasdaqGS', 'NasdaqGM', 'NasdaqCM', 'NYSEArca'}


    # Strategy 1: company-screener per exchange with high limit
    print("  Using /stable/company-screener...")
    for exchange in ['NYSE', 'NASDAQ', 'AMEX']:
        print(f"    {exchange}...", end=' ', flush=True)
        data = fmp_get('/stable/company-screener', {
            'exchange': exchange,
            'isActivelyTrading': 'true',
            'isEtf': 'false',
            'isFund': 'false',
            'limit': 10000,
        }, timeout=60)

        if isinstance(data, list) and data:
            for s in data:
                s['exchangeShortName'] = exchange
            stock_data.extend(data)
            print(f"{len(data)} stocks")
        else:
            print(f"failed or empty")
        time.sleep(RATE_DELAY)

    if not stock_data:
        print("  ERROR: No stock data from any endpoint!")
        return [], {}

    # Filter to US common stocks
    for s in stock_data:
        if not is_common_stock(s):
            continue

        sym = s.get('symbol', '')
        exchange = s.get('exchangeShortName', s.get('exchange', ''))

        # Require a known US exchange
        if not exchange or exchange not in us_exchanges:
            continue

        if sym not in profiles:
            all_stocks.append(sym)
            profiles[sym] = {
                'market_cap': s.get('marketCap', s.get('mktCap')),
                'industry': s.get('industry'),
                'sector': s.get('sector'),
                'exchange': exchange,
                'ticker_type': 'stock',
                'ipo_date': s.get('ipoDate'),
            }

    print(f"  Total US common stocks: {len(all_stocks)}")

    # Load IPO dates from dedicated IPO pipeline (process_ipo.py output)
    ipo_lookup = {}
    if os.path.exists('ipo_dates.json'):
        try:
            with open('ipo_dates.json', 'r') as f:
                ipo_data_file = json.load(f)
            ipo_lookup = ipo_data_file.get('data', {})
            print(f"  Loaded {len(ipo_lookup)} IPO dates from ipo_dates.json")
        except Exception as e:
            print(f"  Warning: Could not load ipo_dates.json: {e}")

    ipo_filled = 0
    for sym in all_stocks:
        if not profiles[sym].get('ipo_date') and sym in ipo_lookup:
            profiles[sym]['ipo_date'] = ipo_lookup[sym]
            ipo_filled += 1
    if ipo_filled:
        print(f"  Filled {ipo_filled} IPO dates from ipo_dates.json")

    return all_stocks, profiles


# ---------------------------------------------------------------------------
# Historical data
# ---------------------------------------------------------------------------

def get_stock_history(ticker: str, start_date: str, end_date: str,
                      verbose: bool = False) -> List[Dict]:
    """Fetch historical daily OHLCV bars for a single stock.
    Tries multiple endpoint formats to find one that works."""

    endpoints = [
        # /stable/ correct endpoint (historical-price-eod/full)
        ('/stable/historical-price-eod/full', {'symbol': ticker, 'from': start_date, 'to': end_date}),
    ]

    for path, params in endpoints:
        try:
            params['apikey'] = API_KEY
            url = f"{BASE_URL}{path}"
            resp = requests.get(url, params=params, timeout=30)

            if verbose:
                print(f"    {path}: status={resp.status_code}")

            if not resp.ok:
                if verbose:
                    print(f"      Response: {resp.text[:200]}")
                continue

            data = resp.json()

            # /stable/historical-price-eod/full returns a flat list of bars
            historical = []
            if isinstance(data, list) and data:
                historical = data
            elif isinstance(data, dict):
                historical = data.get('historical', data.get('data', []))

            if verbose:
                print(f"      Got {len(historical)} bars")

            if not historical:
                continue

            # FMP returns newest-first; reverse for oldest-first
            bars = historical[::-1]
            result = []
            for bar in bars:
                if bar.get('open') and bar.get('close'):
                    result.append({
                        't': int(datetime.strptime(bar['date'], '%Y-%m-%d').timestamp() * 1000),
                        'o': bar['open'],
                        'h': bar['high'],
                        'l': bar['low'],
                        'c': bar['close'],
                        'v': bar.get('volume', 0),
                    })

            if result:
                return result

        except Exception as e:
            if verbose:
                print(f"      Error: {e}")

    return []


# ---------------------------------------------------------------------------
# Earnings & fundamentals
# ---------------------------------------------------------------------------


def get_earnings_data(ticker: str) -> Optional[Dict]:
    """Fetch last 4 quarters of earnings (EPS + revenue actual vs estimated).
    Margin data available via fundamentals pipeline — removed income-statement
    call here to save ~5,000 API calls per rebuild."""

    earnings_raw = fmp_get('/stable/earnings', {'symbol': ticker, 'limit': 8})

    quarters = []

    if isinstance(earnings_raw, list) and earnings_raw:
        for q in earnings_raw:
            eps_actual = q.get('epsActual')
            eps_est = q.get('epsEstimated')
            rev_actual = q.get('revenueActual')
            rev_est = q.get('revenueEstimated')

            eps_surprise = None
            if eps_actual is not None and eps_est is not None and eps_est != 0:
                eps_surprise = round(((eps_actual - eps_est) / abs(eps_est)) * 100, 1)

            rev_surprise = None
            if rev_actual is not None and rev_est is not None and rev_est != 0:
                rev_surprise = round(((rev_actual - rev_est) / abs(rev_est)) * 100, 1)

            quarters.append({
                'date': q.get('date') or q.get('fiscalDateEnding'),
                'eps_actual': eps_actual,
                'eps_estimated': eps_est,
                'eps_surprise_pct': eps_surprise,
                'revenue_actual': rev_actual,
                'revenue_estimated': rev_est,
                'revenue_surprise_pct': rev_surprise,
            })

    if not quarters:
        return None

    # Filter to only reported quarters (have actual EPS or revenue) and take most recent 4
    quarters = [q for q in quarters if q.get('eps_actual') is not None or q.get('revenue_actual') is not None]
    quarters = quarters[:4]  # already sorted newest-first from FMP

    # Calculate overall summary numbers
    eps_surprises = [q['eps_surprise_pct'] for q in quarters if q.get('eps_surprise_pct') is not None]
    rev_surprises = [q['revenue_surprise_pct'] for q in quarters if q.get('revenue_surprise_pct') is not None]

    # Count beats
    eps_beats = len([s for s in eps_surprises if s > 0])
    rev_beats = len([s for s in rev_surprises if s > 0])

    return {
        'quarters': quarters,
        'avg_eps_surprise': round(np.mean(eps_surprises), 1) if eps_surprises else None,
        'avg_revenue_surprise': round(np.mean(rev_surprises), 1) if rev_surprises else None,
        'eps_beats': f"{eps_beats}/{len(eps_surprises)}" if eps_surprises else None,
        'revenue_beats': f"{rev_beats}/{len(rev_surprises)}" if rev_surprises else None,
    }



# ---------------------------------------------------------------------------
# Calculation functions
# ---------------------------------------------------------------------------

def calculate_return(prices: List[Dict], days_back: int) -> Optional[float]:
    if len(prices) < days_back:
        return None
    end_price = prices[-1]['c']
    start_price = prices[-days_back]['c']
    if start_price == 0:
        return None
    return (end_price - start_price) / start_price


def calculate_total_return(prices: List[Dict]) -> float:
    if len(prices) < 2:
        return 0.0
    start_price = prices[0]['c']
    end_price = prices[-1]['c']
    if start_price == 0:
        return 0.0
    return (end_price - start_price) / start_price


def calculate_moving_averages(stock_prices: List[Dict]) -> Optional[Dict]:
    if len(stock_prices) < 220:
        return None

    closes = [bar['c'] for bar in stock_prices]
    current_price = closes[-1]

    ma_50 = np.mean(closes[-50:])
    ma_150 = np.mean(closes[-150:])
    ma_200 = np.mean(closes[-200:])
    ma_200_1month_ago = np.mean(closes[-220:-20])

    is_stage_2 = bool(
        (ma_50 > ma_150)
        and (ma_150 > ma_200)
        and (current_price > ma_150)
        and (ma_200 > ma_200_1month_ago)
    )

    return {
        'ma_50': round(ma_50, 2),
        'ma_150': round(ma_150, 2),
        'ma_200': round(ma_200, 2),
        'is_stage_2': is_stage_2,
    }


def calculate_adr(stock_prices: List[Dict], period: int = 20) -> Optional[float]:
    if len(stock_prices) < period:
        return None
    recent = stock_prices[-period:]
    ranges = [bar['h'] - bar['l'] for bar in recent if 'h' in bar and 'l' in bar]
    return np.mean(ranges) if ranges else None


def calculate_atr(stock_prices: List[Dict], period: int = 14) -> Optional[float]:
    if len(stock_prices) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(stock_prices)):
        cur = stock_prices[i]
        prev = stock_prices[i - 1]
        if 'h' in cur and 'l' in cur and 'c' in prev:
            tr = max(
                cur['h'] - cur['l'],
                abs(cur['h'] - prev['c']),
                abs(cur['l'] - prev['c']),
            )
            true_ranges.append(tr)

    if len(true_ranges) < period:
        return None
    return np.mean(true_ranges[-period:])


def calculate_stock_returns_flexible(
    stock_prices: List[Dict],
) -> Tuple[Optional[Dict], float, int, bool]:
    days_available = len(stock_prices)
    if days_available < 10:
        return None, 0, days_available, False

    periods = {
        '2m': min(42, days_available),
        '3m': min(63, days_available),
        '6m': min(126, days_available),
        '9m': min(189, days_available),
        '12m': min(252, days_available),
    }

    stock_returns = {}
    for name, days in periods.items():
        if days <= days_available and days >= 10:
            ret = calculate_return(stock_prices, days)
            stock_returns[name] = ret if ret is not None else 0
        else:
            stock_returns[name] = 0

    stock_returns['total'] = calculate_total_return(stock_prices)

    recent = stock_prices[-50:] if len(stock_prices) >= 50 else stock_prices
    volumes = [p['v'] for p in recent if 'v' in p]
    avg_volume = np.mean(volumes) if volumes else 0

    is_partial = days_available < 252
    return stock_returns, avg_volume, days_available, is_partial


def calculate_ibd_rs_score_flexible(stock_returns: Dict, days_available: int) -> float:
    if not stock_returns:
        return 0

    if days_available >= 252:
        return (
            0.4 * stock_returns.get('3m', 0)
            + 0.2 * stock_returns.get('6m', 0)
            + 0.2 * stock_returns.get('9m', 0)
            + 0.2 * stock_returns.get('12m', 0)
        )
    elif days_available >= 189:
        return (
            0.5 * stock_returns.get('3m', 0)
            + 0.25 * stock_returns.get('6m', 0)
            + 0.25 * stock_returns.get('9m', 0)
        )
    elif days_available >= 126:
        return (
            0.6 * stock_returns.get('3m', 0)
            + 0.4 * stock_returns.get('6m', 0)
        )
    elif days_available >= 63:
        return stock_returns.get('3m', 0)
    else:
        return stock_returns.get('total', 0)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def get_market_cap_category(mc: Optional[float]) -> str:
    if mc is None:
        return 'Unknown'
    if mc >= 10_000_000_000:
        return 'Large Cap'
    elif mc >= 2_000_000_000:
        return 'Mid Cap'
    elif mc >= 300_000_000:
        return 'Small Cap'
    return 'Micro Cap'


def format_market_cap(mc: Optional[float]) -> str:
    if mc is None:
        return 'N/A'
    if mc >= 1e12:
        return f"${mc / 1e12:.2f}T"
    elif mc >= 1e9:
        return f"${mc / 1e9:.2f}B"
    elif mc >= 1e6:
        return f"${mc / 1e6:.2f}M"
    return f"${mc:,.0f}"


def format_volume(v: float) -> str:
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    elif v >= 1e3:
        return f"{v / 1e3:.0f}k"
    return str(int(v))


def format_return(val: float) -> str:
    return f"{val * 100:.1f}%"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("IBD-Style RS Calculator (FMP Edition)")
    print("=" * 80)
    print()
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    if not API_KEY:
        print("ERROR: FMP_API_KEY not found!")
        return

    # ---- Phase 0: Test API connection ----
    test_api_connection()

    # ---- Phase 1: Test with a single stock (AAPL) ----
    print("PHASE 1: Testing with AAPL...")
    test_bars = get_stock_history('AAPL', '2025-01-01', '2025-03-01', verbose=True)
    if not test_bars:
        print("FATAL: Cannot fetch historical data for AAPL!")
        print("The API key may not have access to historical data.")
        print("Aborting.")
        return
    print(f"  AAPL test passed: {len(test_bars)} bars")
    print()

    # ---- Phase 2: Get stock list ----
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * 5)  # 5 years
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    print(f"Date range: {start_str} to {end_str}\n")

    symbols, profiles = get_all_tickers()
    if not symbols:
        print("ERROR: Failed to get tickers!")
        return

    # ---- Phase 3: Small batch test (first 10 stocks) ----
    print(f"\nPHASE 3: Testing first 10 stocks...")
    test_success = 0
    for ticker in symbols[:10]:
        bars = get_stock_history(ticker, start_str, end_str)
        status = f"{len(bars)} bars" if bars else "NO DATA"
        print(f"  {ticker}: {status}")
        if bars:
            test_success += 1
        time.sleep(RATE_DELAY)

    print(f"\n  Test result: {test_success}/10 succeeded")
    if test_success == 0:
        print("FATAL: No stocks returned data in test batch!")
        print("Aborting.")
        return
    print()

    # ---- Phase 4: Full processing ----
    print(f"Processing {len(symbols)} stocks...\n")

    all_stock_data = []
    historical_stocks = []
    processed = 0
    failed = 0
    partial_calculations = 0
    full_calculations = 0
    stage_2_count = 0
    cap_counts = {'Large Cap': 0, 'Mid Cap': 0, 'Small Cap': 0, 'Micro Cap': 0, 'Unknown': 0}

    for i, ticker in enumerate(symbols):
        try:
            if i % 200 == 0 and i > 0:
                print(
                    f"Progress: {i}/{len(symbols)} ({i / len(symbols) * 100:.1f}%) "
                    f"| OK: {processed} | Fail: {failed} | Stage2: {stage_2_count}"
                )

            stock_prices = get_stock_history(ticker, start_str, end_str)
            if not stock_prices:
                failed += 1
                continue

            result = calculate_stock_returns_flexible(stock_prices)
            if result[0] is None:
                failed += 1
                continue

            stock_returns, avg_volume, days_available, is_partial = result
            rs_score = calculate_ibd_rs_score_flexible(stock_returns, days_available)

            if is_partial:
                partial_calculations += 1
            else:
                full_calculations += 1

            ma_data = calculate_moving_averages(stock_prices)
            adr_20 = calculate_adr(stock_prices, period=20)
            atr_14 = calculate_atr(stock_prices, period=14)
            current_price = round(stock_prices[-1]['c'], 2)

            if ma_data and ma_data['is_stage_2']:
                stage_2_count += 1

            profile = profiles.get(ticker, {})
            market_cap = profile.get('market_cap')
            market_cap_category = get_market_cap_category(market_cap)
            cap_counts[market_cap_category] = cap_counts.get(market_cap_category, 0) + 1

            stock_entry = {
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
                'ipo_date': profile.get('ipo_date'),
                'current_price': current_price,
                'ma_50': ma_data['ma_50'] if ma_data else None,
                'ma_150': ma_data['ma_150'] if ma_data else None,
                'ma_200': ma_data['ma_200'] if ma_data else None,
                'is_stage_2': ma_data['is_stage_2'] if ma_data else False,
                'adr_20': round(adr_20, 2) if adr_20 is not None else None,
                'atr_14': round(atr_14, 2) if atr_14 is not None else None,
                'market_cap': market_cap,
                'market_cap_category': market_cap_category,
                'industry': profile.get('industry'),
                'exchange': profile.get('exchange'),
                'ticker_type': profile.get('ticker_type'),
            }

            all_stock_data.append(stock_entry)

            # Compressed historical data: close-only for older, full OHLCV for recent 30
            minimal_history = []
            older = stock_prices[:-30] if len(stock_prices) > 30 else []
            recent = stock_prices[-30:] if len(stock_prices) >= 30 else stock_prices
            for p in older[::5]:  # every 5th bar for older data
                minimal_history.append({'t': p['t'], 'c': p['c']})
            for p in recent:
                minimal_history.append({'t': p['t'], 'o': p['o'], 'h': p['h'],
                                        'l': p['l'], 'c': p['c'], 'v': p['v']})
            historical_stocks.append({
                's': ticker,
                'h': minimal_history,
                'u': datetime.now().isoformat(),
                'i': profile.get('ipo_date'),
                'd': days_available,
            })

            processed += 1
            time.sleep(RATE_DELAY)

        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            failed += 1

    print()
    print("=" * 80)
    print("PROCESSING COMPLETE")
    print("=" * 80)
    print(f"Processed: {processed} | Failed: {failed}")
    print(f"Full (252+ days): {full_calculations} | Partial: {partial_calculations}")
    print(f"Stage 2: {stage_2_count}")
    for cat, cnt in cap_counts.items():
        if cnt > 0:
            print(f"  {cat}: {cnt}")
    print()

    if not all_stock_data:
        print("ERROR: No stock data processed!")
        return

    # Percentile rankings (1-99)
    all_stock_data.sort(key=lambda x: x['rs_score'], reverse=True)
    total_stocks = len(all_stock_data)

    for i, stock in enumerate(all_stock_data):
        stock['rs_rank'] = min(int(((total_stocks - i) / total_stocks) * 99) + 1, 99)

    # Second pass: fetch earnings only for RS >= 50 stocks (saves ~2,500 API calls)
    earnings_eligible = [s for s in all_stock_data if s['rs_rank'] >= 50]
    print(f"\nFetching earnings for {len(earnings_eligible)} stocks (RS >= 50)...")
    earnings_fetched = 0
    for i, stock in enumerate(earnings_eligible):
        if i % 200 == 0 and i > 0:
            print(f"  Earnings progress: {i}/{len(earnings_eligible)}")
        earnings = get_earnings_data(stock['symbol'])
        if earnings:
            stock['earnings'] = earnings
            earnings_fetched += 1
        time.sleep(RATE_DELAY)
    print(f"  Fetched earnings for {earnings_fetched} stocks")

    # Format output
    output_data = []
    ipo_data = []
    two_years_ago = datetime.now() - timedelta(days=730)

    for stock in all_stock_data:
        entry = {
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
            'adr_20': stock.get('adr_20'),
            'atr_14': stock.get('atr_14'),
            'market_cap': stock.get('market_cap'),
            'market_cap_formatted': format_market_cap(stock.get('market_cap')),
            'market_cap_category': stock.get('market_cap_category'),
            'industry': stock.get('industry'),
            'exchange': stock.get('exchange'),
            'ticker_type': stock.get('ticker_type'),
        }

        # Add earnings data if present
        if stock.get('earnings'):
            entry['earnings'] = stock['earnings']

        output_data.append(entry)

        # Collect recent IPOs
        ipo_str = stock.get('ipo_date')
        if ipo_str:
            try:
                ipo_dt = datetime.strptime(ipo_str, '%Y-%m-%d')
                if ipo_dt >= two_years_ago:
                    ipo_data.append(entry)
            except ValueError:
                pass

    # Save rankings.json
    rankings_output = {
        'last_updated': datetime.now().isoformat(),
        'formula_used': 'Flexible: Adapts to available data',
        'stage_2_criteria': '50dma > 150dma > 200dma',
        'volatility_metrics': 'ADR (20-day), ATR (14-day)',
        'includes_market_data': True,
        'total_stocks': len(output_data),
        'full_calculations': full_calculations,
        'partial_calculations': partial_calculations,
        'stage_2_stocks': stage_2_count,
        'market_cap_distribution': {k: v for k, v in cap_counts.items() if v > 0},
        'update_type': 'full_rebuild',
        'data_source': 'Financial Modeling Prep',
        'data': output_data,
    }

    with open('rankings.json', 'w') as f:
        json.dump(rankings_output, f, indent=2)
    print(f"Saved {len(output_data)} stocks to rankings.json")

    # Save recent_ipos.json
    ipo_output = {
        'last_updated': datetime.now().isoformat(),
        'total_stocks': len(ipo_data),
        'update_type': 'full_rebuild',
        'data': sorted(ipo_data, key=lambda x: x.get('ipo_date', ''), reverse=True),
    }
    with open('recent_ipos.json', 'w') as f:
        json.dump(ipo_output, f, indent=2)
    print(f"Saved {len(ipo_data)} recent IPOs to recent_ipos.json")

    # Save historical_data.json
    historical_output = {
        'u': datetime.now().isoformat(),
        'n': len(historical_stocks),
        'd': historical_stocks,
    }
    with open('historical_data.json', 'w') as f:
        json.dump(historical_output, f, indent=2)
    print(f"Saved historical data for {len(historical_stocks)} stocks")

    # Top 20
    print()
    print("=" * 120)
    print("TOP 20 RS RANKINGS")
    print("=" * 120)
    print(f"{'Rank':<5} {'Symbol':<8} {'RS':<4} {'Cap':<12} {'Industry':<30} {'Price':<8} {'3M Ret':<8}")
    print("-" * 120)
    for i, s in enumerate(output_data[:20]):
        ind = (s.get('industry') or 'N/A')[:28]
        price = f"${s['current_price']}" if s['current_price'] else 'N/A'
        print(f"{i+1:<5} {s['symbol']:<8} {s['rs_rank']:<4} {s.get('market_cap_category',''):<12} {ind:<30} {price:<8} {s['stock_return_3m']:<8}")

    print()
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


def daily_update():
    """Incremental daily update: reload previous rankings, re-fetch prices only,
    recompute MAs/RS/ATR/ADR. Keeps existing profiles, earnings, industry data."""
    print("=" * 80)
    print("DAILY INCREMENTAL UPDATE")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    if not API_KEY:
        print("ERROR: FMP_API_KEY not found!")
        return

    # Load previous rankings as baseline
    if not os.path.exists('rankings.json'):
        print("ERROR: rankings.json not found. Run a full rebuild first.")
        return

    with open('rankings.json', 'r') as f:
        prev = json.load(f)

    prev_data = prev.get('data', [])
    if not prev_data:
        print("ERROR: Previous rankings.json has no data. Run a full rebuild.")
        return

    print(f"Loaded {len(prev_data)} stocks from previous rankings.json")

    # Also check for new tickers not in previous run
    symbols_prev = {s['symbol'] for s in prev_data}
    prev_profiles = {s['symbol']: s for s in prev_data}

    # Fetch current ticker list to detect new additions
    new_symbols, new_profiles = get_all_tickers()
    new_set = set(new_symbols)
    added = new_set - symbols_prev
    removed = symbols_prev - new_set
    if added:
        print(f"  New tickers since last run: {len(added)} (will do full fetch for these)")
    if removed:
        print(f"  Removed tickers: {len(removed)}")

    # All symbols to process = previous + new
    all_symbols = list(symbols_prev | new_set)
    print(f"  Total symbols to update: {len(all_symbols)}")

    # Date range for price history
    # 400 calendar days guarantees ~280 trading days, which covers the longest
    # math window (200dma-1m = 220 trading days, 12m return = 252 trading days).
    # historical_data.json is owned by the Friday full rebuild and not refreshed here.
    end_date = datetime.now()
    start_date = end_date - timedelta(days=400)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    all_stock_data = []
    processed = 0
    failed = 0
    stage_2_count = 0
    cap_counts = {'Large Cap': 0, 'Mid Cap': 0, 'Small Cap': 0, 'Micro Cap': 0, 'Unknown': 0}

    for i, ticker in enumerate(all_symbols):
        try:
            if i % 200 == 0 and i > 0:
                print(f"Progress: {i}/{len(all_symbols)} ({i / len(all_symbols) * 100:.1f}%) | OK: {processed} | Fail: {failed}")

            # Fetch fresh price history
            stock_prices = get_stock_history(ticker, start_str, end_str)
            if not stock_prices:
                failed += 1
                continue

            result = calculate_stock_returns_flexible(stock_prices)
            if result[0] is None:
                failed += 1
                continue

            stock_returns, avg_volume, days_available, is_partial = result
            rs_score = calculate_ibd_rs_score_flexible(stock_returns, days_available)
            ma_data = calculate_moving_averages(stock_prices)
            adr_20 = calculate_adr(stock_prices, period=20)
            atr_14 = calculate_atr(stock_prices, period=14)
            current_price = round(stock_prices[-1]['c'], 2)

            if ma_data and ma_data['is_stage_2']:
                stage_2_count += 1

            # For existing stocks, reuse profile/earnings from previous run
            # For new stocks, use fresh profile data
            if ticker in prev_profiles:
                prev = prev_profiles[ticker]
                profile = {
                    'market_cap': prev.get('market_cap'),
                    'industry': prev.get('industry'),
                    'exchange': prev.get('exchange'),
                    'ticker_type': prev.get('ticker_type'),
                    'ipo_date': prev.get('ipo_date'),
                }
                earnings = prev.get('earnings')
            else:
                profile = new_profiles.get(ticker, {})
                earnings = get_earnings_data(ticker)
                time.sleep(RATE_DELAY)

            market_cap = profile.get('market_cap')
            market_cap_category = get_market_cap_category(market_cap)
            cap_counts[market_cap_category] = cap_counts.get(market_cap_category, 0) + 1

            stock_entry = {
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
                'ipo_date': profile.get('ipo_date'),
                'current_price': current_price,
                'ma_50': ma_data['ma_50'] if ma_data else None,
                'ma_150': ma_data['ma_150'] if ma_data else None,
                'ma_200': ma_data['ma_200'] if ma_data else None,
                'is_stage_2': ma_data['is_stage_2'] if ma_data else False,
                'adr_20': round(adr_20, 2) if adr_20 is not None else None,
                'atr_14': round(atr_14, 2) if atr_14 is not None else None,
                'market_cap': market_cap,
                'market_cap_category': market_cap_category,
                'industry': profile.get('industry'),
                'exchange': profile.get('exchange'),
                'ticker_type': profile.get('ticker_type'),
            }

            if earnings:
                stock_entry['earnings'] = earnings

            all_stock_data.append(stock_entry)

            processed += 1
            time.sleep(RATE_DELAY)

        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            failed += 1

    print()
    print("=" * 80)
    print("DAILY UPDATE COMPLETE")
    print(f"Processed: {processed} | Failed: {failed} | Stage 2: {stage_2_count}")
    print("=" * 80)

    if not all_stock_data:
        print("ERROR: No stock data processed!")
        return

    # Percentile rankings (1-99)
    all_stock_data.sort(key=lambda x: x['rs_score'], reverse=True)
    total_stocks = len(all_stock_data)
    for i, stock in enumerate(all_stock_data):
        stock['rs_rank'] = min(int(((total_stocks - i) / total_stocks) * 99) + 1, 99)

    # Format and save (same format as full rebuild)
    output_data = []
    ipo_data = []
    two_years_ago = datetime.now() - timedelta(days=730)

    for stock in all_stock_data:
        entry = {
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
            'adr_20': stock.get('adr_20'),
            'atr_14': stock.get('atr_14'),
            'market_cap': stock.get('market_cap'),
            'market_cap_formatted': format_market_cap(stock.get('market_cap')),
            'market_cap_category': stock.get('market_cap_category'),
            'industry': stock.get('industry'),
            'exchange': stock.get('exchange'),
            'ticker_type': stock.get('ticker_type'),
        }
        if stock.get('earnings'):
            entry['earnings'] = stock['earnings']
        output_data.append(entry)

        ipo_str = stock.get('ipo_date')
        if ipo_str:
            try:
                ipo_dt = datetime.strptime(ipo_str, '%Y-%m-%d')
                if ipo_dt >= two_years_ago:
                    ipo_data.append(entry)
            except ValueError:
                pass

    rankings_output = {
        'last_updated': datetime.now().isoformat(),
        'formula_used': 'Flexible: Adapts to available data',
        'stage_2_criteria': '50dma > 150dma > 200dma',
        'volatility_metrics': 'ADR (20-day), ATR (14-day)',
        'includes_market_data': True,
        'total_stocks': len(output_data),
        'stage_2_stocks': stage_2_count,
        'market_cap_distribution': {k: v for k, v in cap_counts.items() if v > 0},
        'update_type': 'daily_incremental',
        'data_source': 'Financial Modeling Prep',
        'data': output_data,
    }

    with open('rankings.json', 'w') as f:
        json.dump(rankings_output, f, indent=2)
    print(f"Saved {len(output_data)} stocks to rankings.json")

    with open('recent_ipos.json', 'w') as f:
        json.dump({
            'last_updated': datetime.now().isoformat(),
            'total_stocks': len(ipo_data),
            'update_type': 'daily_incremental',
            'data': sorted(ipo_data, key=lambda x: x.get('ipo_date', ''), reverse=True),
        }, f, indent=2)
    print(f"Saved {len(ipo_data)} recent IPOs to recent_ipos.json")

    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='IBD-Style RS Calculator')
    parser.add_argument('--mode', choices=['full', 'daily'], default='full',
                        help='full = rebuild everything, daily = incremental price update')
    args = parser.parse_args()

    if args.mode == 'daily':
        daily_update()
    else:
        main()
