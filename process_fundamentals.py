"""
FUNDAMENTALS PIPELINE: process_fundamentals.py
Fetches fundamental financial data from FMP for all stocks in rankings.json.
Generates per-symbol JSON files in fundamentals/ directory.
Includes pre-computed analysis scoring (0-100) with green/yellow/red flags.

Uses /stable/ endpoints only (v3/v4 return 403 on Premium plan).
Data is quarterly — only needs to run weekly (or on-demand).
"""

import os
import json
import requests
import time
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any

# Configuration
API_KEY = os.environ.get('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com'
RATE_DELAY = 0.25  # seconds between API calls
QUARTERS_TO_FETCH = 8  # 2 years of quarterly data
ANNUAL_LIMIT = 4  # 4 years of annual data


# ---------------------------------------------------------------------------
# API helpers (same pattern as process_stocks.py)
# ---------------------------------------------------------------------------

def fmp_get(path: str, params: Optional[Dict] = None, timeout: int = 30) -> Optional[Any]:
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
        # Check for error responses
        if isinstance(data, dict) and data.get('Error Message'):
            return None
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and data[0].get('Error Message'):
            return None
        return data
    except Exception as e:
        print(f"    Error fetching {path}: {e}")
        return None


def safe_float(val, default=None):
    """Safely convert to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_pct(val, default=None):
    """Convert ratio to percentage, handling None."""
    f = safe_float(val)
    if f is None:
        return default
    return round(f * 100, 2)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_fundamentals(symbol: str) -> Dict[str, Any]:
    """Fetch all fundamental data for a symbol from FMP."""
    data = {'symbol': symbol}

    endpoints = [
        # Financial Statements (quarterly)
        ('income_statement', '/stable/income-statement', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),
        ('balance_sheet', '/stable/balance-sheet-statement', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),
        ('cash_flow', '/stable/cash-flow-statement', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),

        # Financial Statements (annual for longer-term trends)
        ('income_statement_annual', '/stable/income-statement', {'symbol': symbol, 'period': 'annual', 'limit': ANNUAL_LIMIT}),
        ('balance_sheet_annual', '/stable/balance-sheet-statement', {'symbol': symbol, 'period': 'annual', 'limit': ANNUAL_LIMIT}),
        ('cash_flow_annual', '/stable/cash-flow-statement', {'symbol': symbol, 'period': 'annual', 'limit': ANNUAL_LIMIT}),

        # TTM
        ('income_statement_ttm', '/stable/income-statement-ttm', {'symbol': symbol}),
        ('balance_sheet_ttm', '/stable/balance-sheet-statement-ttm', {'symbol': symbol}),
        ('cash_flow_ttm', '/stable/cash-flow-statement-ttm', {'symbol': symbol}),

        # Ratios & Metrics
        ('key_metrics', '/stable/key-metrics', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),
        ('ratios', '/stable/ratios', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),
        ('key_metrics_ttm', '/stable/key-metrics-ttm', {'symbol': symbol}),
        ('ratios_ttm', '/stable/ratios-ttm', {'symbol': symbol}),

        # Analysis & Scores
        ('financial_scores', '/stable/financial-scores', {'symbol': symbol}),
        ('owner_earnings', '/stable/owner-earnings', {'symbol': symbol, 'limit': QUARTERS_TO_FETCH}),
        ('enterprise_values', '/stable/enterprise-values', {'symbol': symbol, 'limit': ANNUAL_LIMIT}),

        # Growth
        ('income_growth', '/stable/income-statement-growth', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),
        ('financial_growth', '/stable/financial-growth', {'symbol': symbol, 'limit': ANNUAL_LIMIT}),

        # Segmentation
        ('revenue_product_segments', '/stable/revenue-product-segmentation', {'symbol': symbol}),
        ('revenue_geo_segments', '/stable/revenue-geographic-segmentation', {'symbol': symbol}),
    ]

    for key, path, params in endpoints:
        result = fmp_get(path, params)
        time.sleep(RATE_DELAY)

        # Normalize: TTM endpoints often return single-item arrays
        if key.endswith('_ttm') and isinstance(result, list) and len(result) == 1:
            result = result[0]
        elif key == 'financial_scores' and isinstance(result, list) and len(result) == 1:
            result = result[0]

        data[key] = result if result else None

    return data


# ---------------------------------------------------------------------------
# Analysis scoring
# ---------------------------------------------------------------------------

def compute_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute analysis score (0-100) and flags from fundamental data."""
    flags = []
    scores = {
        'profitability': 0,
        'growth': 0,
        'balance_sheet': 0,
        'quant_scores': 0,
    }

    income = data.get('income_statement') or []
    balance = data.get('balance_sheet') or []
    cash_flow = data.get('cash_flow') or []
    ratios = data.get('ratios') or []
    metrics = data.get('key_metrics') or []
    fin_scores = data.get('financial_scores')
    income_growth = data.get('income_growth') or []

    # Reverse to chronological order (oldest first) for trend analysis
    income = list(reversed(income)) if income else []
    balance = list(reversed(balance)) if balance else []
    cash_flow = list(reversed(cash_flow)) if cash_flow else []
    ratios = list(reversed(ratios)) if ratios else []
    metrics = list(reversed(metrics)) if metrics else []
    income_growth = list(reversed(income_growth)) if income_growth else []

    # ── Profitability (25 pts) ──────────────────────────────────
    if len(income) >= 2:
        # Revenue trend
        revenues = [safe_float(q.get('revenue')) for q in income if safe_float(q.get('revenue')) is not None]
        if len(revenues) >= 4:
            recent = revenues[-1]
            year_ago = revenues[-4] if len(revenues) >= 4 else revenues[0]
            if year_ago and year_ago > 0:
                rev_growth = ((recent - year_ago) / year_ago) * 100
                if rev_growth > 20:
                    scores['profitability'] += 8
                    flags.append({'type': 'green', 'category': 'profitability', 'message': f'Revenue growing {rev_growth:.0f}% YoY'})
                elif rev_growth > 5:
                    scores['profitability'] += 5
                    flags.append({'type': 'green', 'category': 'profitability', 'message': f'Revenue growing {rev_growth:.0f}% YoY'})
                elif rev_growth > 0:
                    scores['profitability'] += 2
                elif rev_growth > -10:
                    scores['profitability'] += 1
                    flags.append({'type': 'yellow', 'category': 'profitability', 'message': f'Revenue declining {rev_growth:.0f}% YoY'})
                else:
                    flags.append({'type': 'red', 'category': 'profitability', 'message': f'Revenue declining {rev_growth:.0f}% YoY'})

        # Margin trend
        margins = [safe_float(q.get('netIncomeRatio')) for q in income if safe_float(q.get('netIncomeRatio')) is not None]
        if len(margins) >= 4:
            recent_margin = margins[-1] * 100
            old_margin = margins[-4] * 100 if len(margins) >= 4 else margins[0] * 100
            if recent_margin > 15:
                scores['profitability'] += 5
                flags.append({'type': 'green', 'category': 'profitability', 'message': f'Net margin strong at {recent_margin:.1f}%'})
            elif recent_margin > 5:
                scores['profitability'] += 3
            elif recent_margin > 0:
                scores['profitability'] += 1
            else:
                flags.append({'type': 'red', 'category': 'profitability', 'message': f'Company is unprofitable (net margin {recent_margin:.1f}%)'})

            if recent_margin > old_margin + 2:
                scores['profitability'] += 4
                flags.append({'type': 'green', 'category': 'profitability', 'message': 'Margins expanding'})
            elif recent_margin < old_margin - 2:
                scores['profitability'] += 1
                flags.append({'type': 'yellow', 'category': 'profitability', 'message': 'Margins contracting'})
            else:
                scores['profitability'] += 2

        # ROE
        if ratios:
            roe = safe_float(ratios[-1].get('returnOnEquity'))
            if roe is not None:
                roe_pct = roe * 100
                if roe_pct > 20:
                    scores['profitability'] += 8
                    flags.append({'type': 'green', 'category': 'profitability', 'message': f'ROE excellent at {roe_pct:.1f}%'})
                elif roe_pct > 10:
                    scores['profitability'] += 5
                elif roe_pct > 0:
                    scores['profitability'] += 2
                else:
                    flags.append({'type': 'red', 'category': 'profitability', 'message': f'Negative ROE ({roe_pct:.1f}%)'})

    # ── Growth (25 pts) ─────────────────────────────────────────
    if len(income) >= 5:
        # EPS acceleration (last 4 quarters)
        eps_vals = [safe_float(q.get('eps')) for q in income[-5:] if safe_float(q.get('eps')) is not None]
        if len(eps_vals) >= 4:
            # Check for consecutive QoQ growth
            consecutive = 0
            for i in range(1, len(eps_vals)):
                if eps_vals[i] > eps_vals[i - 1]:
                    consecutive += 1
                else:
                    consecutive = 0
            if consecutive >= 3:
                scores['growth'] += 10
                flags.append({'type': 'green', 'category': 'growth', 'message': f'EPS accelerating {consecutive} consecutive quarters'})
            elif consecutive >= 2:
                scores['growth'] += 6
            elif consecutive >= 1:
                scores['growth'] += 3

        # YoY EPS growth
        if len(eps_vals) >= 4:
            recent_eps = eps_vals[-1]
            year_ago_eps = eps_vals[-4] if len(eps_vals) >= 4 else eps_vals[0]
            if year_ago_eps and year_ago_eps > 0 and recent_eps is not None:
                eps_growth = ((recent_eps - year_ago_eps) / abs(year_ago_eps)) * 100
                if eps_growth > 25:
                    scores['growth'] += 8
                    flags.append({'type': 'green', 'category': 'growth', 'message': f'EPS growing {eps_growth:.0f}% YoY'})
                elif eps_growth > 10:
                    scores['growth'] += 5
                elif eps_growth > 0:
                    scores['growth'] += 2
                elif eps_growth > -15:
                    flags.append({'type': 'yellow', 'category': 'growth', 'message': f'EPS declining {eps_growth:.0f}% YoY'})
                else:
                    flags.append({'type': 'red', 'category': 'growth', 'message': f'EPS declining {eps_growth:.0f}% YoY'})

    # Revenue growth acceleration
    if income_growth and len(income_growth) >= 2:
        rev_growths = [safe_float(q.get('growthRevenue')) for q in income_growth if safe_float(q.get('growthRevenue')) is not None]
        if len(rev_growths) >= 2 and rev_growths[-1] is not None and rev_growths[-2] is not None:
            if rev_growths[-1] > rev_growths[-2]:
                scores['growth'] += 7
                flags.append({'type': 'green', 'category': 'growth', 'message': 'Revenue growth accelerating'})
            else:
                scores['growth'] += 3

    # ── Balance Sheet Health (25 pts) ───────────────────────────
    if balance:
        latest_bs = balance[-1]

        # Debt-to-equity
        total_debt = safe_float(latest_bs.get('totalDebt', latest_bs.get('longTermDebt', 0)))
        total_equity = safe_float(latest_bs.get('totalStockholdersEquity'))
        if total_equity and total_equity > 0 and total_debt is not None:
            de_ratio = total_debt / total_equity
            if de_ratio < 0.5:
                scores['balance_sheet'] += 8
                flags.append({'type': 'green', 'category': 'balance_sheet', 'message': f'Low debt-to-equity ({de_ratio:.2f})'})
            elif de_ratio < 1.0:
                scores['balance_sheet'] += 5
            elif de_ratio < 2.0:
                scores['balance_sheet'] += 2
                flags.append({'type': 'yellow', 'category': 'balance_sheet', 'message': f'Moderate debt-to-equity ({de_ratio:.2f})'})
            else:
                flags.append({'type': 'red', 'category': 'balance_sheet', 'message': f'High debt-to-equity ({de_ratio:.2f})'})

            # D/E trend
            if len(balance) >= 4:
                old_equity = safe_float(balance[-4].get('totalStockholdersEquity'))
                old_debt = safe_float(balance[-4].get('totalDebt', balance[-4].get('longTermDebt', 0)))
                if old_equity and old_equity > 0 and old_debt is not None:
                    old_de = old_debt / old_equity
                    if de_ratio > old_de + 0.3:
                        flags.append({'type': 'yellow', 'category': 'balance_sheet', 'message': f'Debt-to-equity rising ({old_de:.2f} → {de_ratio:.2f})'})

        # Current ratio
        current_assets = safe_float(latest_bs.get('totalCurrentAssets'))
        current_liabilities = safe_float(latest_bs.get('totalCurrentLiabilities'))
        if current_assets and current_liabilities and current_liabilities > 0:
            current_ratio = current_assets / current_liabilities
            if current_ratio > 2.0:
                scores['balance_sheet'] += 6
                flags.append({'type': 'green', 'category': 'balance_sheet', 'message': f'Strong current ratio ({current_ratio:.2f})'})
            elif current_ratio > 1.5:
                scores['balance_sheet'] += 4
            elif current_ratio > 1.0:
                scores['balance_sheet'] += 2
            else:
                flags.append({'type': 'red', 'category': 'balance_sheet', 'message': f'Current ratio below 1 ({current_ratio:.2f})'})

    # Free cash flow trend
    if cash_flow and len(cash_flow) >= 2:
        fcf_vals = [safe_float(q.get('freeCashFlow')) for q in cash_flow if safe_float(q.get('freeCashFlow')) is not None]
        if len(fcf_vals) >= 2:
            if fcf_vals[-1] and fcf_vals[-1] > 0:
                scores['balance_sheet'] += 5
                if len(fcf_vals) >= 4 and all(f and f > 0 for f in fcf_vals[-4:]):
                    scores['balance_sheet'] += 6
                    flags.append({'type': 'green', 'category': 'balance_sheet', 'message': 'Positive free cash flow for 4+ quarters'})
            else:
                flags.append({'type': 'red', 'category': 'balance_sheet', 'message': 'Negative free cash flow'})

    # ── Quantitative Scores (25 pts) ───────────────────────────
    if fin_scores and isinstance(fin_scores, dict):
        # Piotroski F-Score (0-9)
        piotroski = safe_float(fin_scores.get('piotroskiScore'))
        if piotroski is not None:
            if piotroski >= 7:
                scores['quant_scores'] += 10
                flags.append({'type': 'green', 'category': 'quant_scores', 'message': f'Piotroski F-Score: {int(piotroski)}/9 (strong)'})
            elif piotroski >= 5:
                scores['quant_scores'] += 6
            elif piotroski >= 3:
                scores['quant_scores'] += 3
                flags.append({'type': 'yellow', 'category': 'quant_scores', 'message': f'Piotroski F-Score: {int(piotroski)}/9 (weak)'})
            else:
                flags.append({'type': 'red', 'category': 'quant_scores', 'message': f'Piotroski F-Score: {int(piotroski)}/9 (poor)'})

        # Altman Z-Score
        altman = safe_float(fin_scores.get('altmanZScore'))
        if altman is not None:
            if altman > 3.0:
                scores['quant_scores'] += 10
                flags.append({'type': 'green', 'category': 'quant_scores', 'message': f'Altman Z-Score: {altman:.1f} (safe zone)'})
            elif altman > 1.8:
                scores['quant_scores'] += 5
                flags.append({'type': 'yellow', 'category': 'quant_scores', 'message': f'Altman Z-Score: {altman:.1f} (grey zone)'})
            else:
                flags.append({'type': 'red', 'category': 'quant_scores', 'message': f'Altman Z-Score: {altman:.1f} (distress zone)'})

    # Owner earnings trend
    owner = data.get('owner_earnings') or []
    if isinstance(owner, list) and len(owner) >= 2:
        oe_vals = [safe_float(q.get('ownerEarnings')) for q in reversed(owner) if safe_float(q.get('ownerEarnings')) is not None]
        if len(oe_vals) >= 2 and oe_vals[-1] and oe_vals[0]:
            if oe_vals[-1] > oe_vals[0]:
                scores['quant_scores'] += 5
                flags.append({'type': 'green', 'category': 'quant_scores', 'message': 'Owner earnings trending up'})

    # ── Compute overall ─────────────────────────────────────────
    # Cap each category at 25
    for k in scores:
        scores[k] = min(scores[k], 25)

    overall = sum(scores.values())

    if overall >= 86:
        rating = 'excellent'
    elif overall >= 71:
        rating = 'strong'
    elif overall >= 51:
        rating = 'average'
    elif overall >= 31:
        rating = 'below_average'
    else:
        rating = 'weak'

    return {
        'overall_score': overall,
        'rating': rating,
        'category_scores': scores,
        'flags': flags,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not API_KEY:
        print("ERROR: FMP_API_KEY not set")
        sys.exit(1)

    print("=" * 80)
    print("FUNDAMENTALS PIPELINE")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Load symbols from rankings.json
    if not os.path.exists('rankings.json'):
        print("ERROR: rankings.json not found. Run process_stocks.py first.")
        sys.exit(1)

    with open('rankings.json', 'r') as f:
        rankings = json.load(f)

    all_symbols = [s['symbol'] for s in rankings.get('data', [])]
    print(f"Found {len(all_symbols)} symbols in rankings.json")

    # Optional: limit to subset via env var (for testing)
    limit = os.environ.get('FUNDAMENTALS_LIMIT')
    if limit:
        all_symbols = all_symbols[:int(limit)]
        print(f"Limited to {len(all_symbols)} symbols (FUNDAMENTALS_LIMIT={limit})")

    # Create output directory
    os.makedirs('fundamentals', exist_ok=True)

    success = 0
    errors = 0

    for i, symbol in enumerate(all_symbols):
        print(f"\n[{i+1}/{len(all_symbols)}] {symbol}")

        try:
            # Fetch all fundamental data
            fund_data = fetch_fundamentals(symbol)

            # Skip if no income statement data (probably not a real company)
            if not fund_data.get('income_statement'):
                print(f"  Skipping {symbol} — no income statement data")
                errors += 1
                continue

            # Compute analysis
            fund_data['analysis'] = compute_analysis(fund_data)
            fund_data['last_updated'] = datetime.now().isoformat()

            # Save per-symbol JSON
            output_path = f"fundamentals/{symbol}.json"
            with open(output_path, 'w') as f:
                json.dump(fund_data, f, separators=(',', ':'))  # compact JSON

            score = fund_data['analysis']['overall_score']
            rating = fund_data['analysis']['rating']
            n_flags = len(fund_data['analysis']['flags'])
            print(f"  Score: {score}/100 ({rating}) — {n_flags} flags")
            success += 1

        except Exception as e:
            print(f"  ERROR processing {symbol}: {e}")
            errors += 1

    # Summary
    print()
    print("=" * 80)
    print(f"COMPLETE: {success} succeeded, {errors} failed")
    print(f"Output: fundamentals/ ({success} JSON files)")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
