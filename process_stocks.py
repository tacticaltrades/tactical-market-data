"""
FULL REBUILD: process_stocks.py (FMP Edition)
Fetches all active US stocks from Financial Modeling Prep API.
Calculates RS scores, moving averages, ADR, ATR, Stage 2 status.
Includes market cap, industry/sector, IPO date.

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
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

# Configuration
API_KEY = os.environ.get('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com/api'
RATE_DELAY = 0.25  # seconds between API calls (240/min, under 300/min limit)


# ---------------------------------------------------------------------------
# API functions
# ---------------------------------------------------------------------------

def get_all_tickers() -> Tuple[List[str], Dict[str, Dict]]:
    """Fetch all active US stocks from FMP.
    Tries multiple endpoints in order of preference.
    Returns (symbol_list, profiles_dict)."""
    print("Fetching all tickers from FMP...")

    all_stocks = []
    profiles = {}

    # Strategy: try available-traded/list, then quotes/{exchange}
    endpoints_to_try = [
        ('available-traded/list', f"{BASE_URL}/v3/available-traded/list", {'apikey': API_KEY}),
        ('symbol/available-stocks', f"{BASE_URL}/v3/symbol/available-stock-list", {'apikey': API_KEY}),
    ]

    stock_data = None
    for name, url, params in endpoints_to_try:
        print(f"  Trying {name}...")
        try:
            response = requests.get(url, params=params)
            print(f"    Status: {response.status_code}")
            if response.ok:
                stock_data = response.json()
                print(f"    Got {len(stock_data)} entries")
                break
        except Exception as e:
            print(f"    Error: {e}")

    if not stock_data:
        # Fallback: get stocks from quotes endpoint (per exchange)
        print("  Trying quotes per exchange...")
        stock_data = []
        for exchange in ['NYSE', 'NASDAQ', 'AMEX']:
            print(f"    Fetching {exchange}...")
            try:
                url = f"{BASE_URL}/v3/quotes/{exchange}"
                resp = requests.get(url, params={'apikey': API_KEY})
                print(f"      Status: {resp.status_code}")
                if resp.ok:
                    data = resp.json()
                    # quotes endpoint returns: symbol, name, price, marketCap, etc.
                    for s in data:
                        s['exchangeShortName'] = exchange
                    stock_data.extend(data)
                    print(f"      Got {len(data)} stocks")
            except Exception as e:
                print(f"      Error: {e}")
            time.sleep(RATE_DELAY)

    if not stock_data:
        print("  ERROR: All endpoints failed!")
        return [], {}

    # Filter to US exchanges and clean symbols
    us_exchanges = {'NYSE', 'NASDAQ', 'AMEX', 'New York Stock Exchange', 'NasdaqGS', 'NasdaqGM', 'NasdaqCM'}
    for s in stock_data:
        sym = s.get('symbol', '')
        if not sym or '.' in sym or '-' in sym or len(sym) > 5:
            continue

        exchange = s.get('exchangeShortName', s.get('exchange', ''))
        if exchange and exchange not in us_exchanges:
            continue

        if sym not in profiles:  # deduplicate
            all_stocks.append(sym)
            profiles[sym] = {
                'market_cap': s.get('marketCap', s.get('mktCap')),
                'industry': s.get('industry'),
                'sector': s.get('sector'),
                'exchange': exchange,
                'ticker_type': 'stock',
                'ipo_date': s.get('ipoDate'),
            }

    print(f"  Total unique US stocks: {len(all_stocks)}")

    # Fill in missing profile data (IPO dates, industry, etc.) via batch profile calls
    missing_profile = [sym for sym in all_stocks if not profiles[sym].get('industry')]
    if missing_profile:
        print(f"  Fetching profiles for {len(missing_profile)} stocks missing details...")
        for i in range(0, len(missing_profile), 50):
            batch = missing_profile[i:i + 50]
            symbols_str = ','.join(batch)
            try:
                url = f"{BASE_URL}/v3/profile/{symbols_str}"
                resp = requests.get(url, params={'apikey': API_KEY})
                if resp.ok:
                    for p in resp.json():
                        sym = p.get('symbol')
                        if sym and sym in profiles:
                            if p.get('ipoDate'):
                                profiles[sym]['ipo_date'] = p['ipoDate']
                            if p.get('industry'):
                                profiles[sym]['industry'] = p['industry']
                            if p.get('sector'):
                                profiles[sym]['sector'] = p['sector']
                            if p.get('mktCap'):
                                profiles[sym]['market_cap'] = p['mktCap']
            except Exception:
                pass

            if i % 500 == 0 and i > 0:
                print(f"    Profiles: {i}/{len(missing_profile)}")
            time.sleep(RATE_DELAY)

    print(f"  Done. {len(all_stocks)} stocks ready to process.")
    return all_stocks, profiles


def get_stock_data(ticker: str, start_date: str, end_date: str) -> List[Dict]:
    """Fetch historical daily OHLCV bars from FMP"""
    try:
        url = f"{BASE_URL}/v3/historical-price-full/{ticker}"
        params = {
            'from': start_date,
            'to': end_date,
            'apikey': API_KEY,
        }

        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get('historical'):
            return []

        # FMP returns newest-first; reverse for oldest-first
        bars = data['historical'][::-1]
        return [
            {
                't': int(datetime.strptime(bar['date'], '%Y-%m-%d').timestamp() * 1000),
                'o': bar['open'],
                'h': bar['high'],
                'l': bar['low'],
                'c': bar['close'],
                'v': bar.get('volume', 0),
            }
            for bar in bars
            if bar.get('open') and bar.get('close')
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Calculation functions (unchanged logic)
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

    end_date = datetime.now()
    start_date = end_date - timedelta(days=450)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    print(f"Date range: {start_str} to {end_str}\n")

    # 1. Get all US stock tickers + profiles (screener gives both)
    symbols, profiles = get_all_tickers()
    if not symbols:
        print("ERROR: Failed to get tickers!")
        return

    print(f"Processing {len(symbols)} stocks...\n")

    # 2. Process each stock
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

            stock_prices = get_stock_data(ticker, start_str, end_str)
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
            })

            # Compressed historical data (same format as before)
            minimal_history = []
            if len(stock_prices) > 30:
                for price in stock_prices[:-30:5]:
                    minimal_history.append({'t': price['t'], 'c': price['c']})
            else:
                for price in stock_prices[:-10:5] if len(stock_prices) > 10 else []:
                    minimal_history.append({'t': price['t'], 'c': price['c']})

            recent = stock_prices[-30:] if len(stock_prices) >= 30 else stock_prices
            for price in recent:
                minimal_history.append({
                    't': price['t'],
                    'c': price['c'],
                    'v': price['v'],
                    'o': price['o'],
                    'h': price['h'],
                    'l': price['l'],
                })

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


if __name__ == "__main__":
    main()
