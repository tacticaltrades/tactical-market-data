"""
FUNDAMENTALS PIPELINE: process_fundamentals.py
Fetches fundamental financial data from FMP for all stocks in rankings.json.
Generates per-symbol JSON files in fundamentals/ directory.

Scoring based on O'Neil's CAN SLIM and Minervini's SEPA methodology:
- C Score: Current Quarterly Earnings (25 pts)
- A Score: Annual Earnings Growth (25 pts)
- N Score: New/Catalyst (15 pts)
- S Score: Supply & Demand (15 pts)
- SEPA Score: Minervini Overlay (20 pts)
- Trend Template: 8-criteria pass/fail checklist

Uses /stable/ endpoints only (v3/v4 return 403 on Premium plan).
"""

import os
import json
import requests
import time
import sys
from datetime import datetime, date
from typing import Dict, List, Optional, Any

# Configuration
API_KEY = os.environ.get('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com'
RATE_DELAY = 0.15
MAX_RUNTIME_SECONDS = 5 * 60 * 60  # 5 hours — save and exit if exceeded
QUARTERS_TO_FETCH = 8
ANNUAL_LIMIT = 5


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fmp_get(path: str, params: Optional[Dict] = None, timeout: int = 30) -> Optional[Any]:
    if params is None:
        params = {}
    params['apikey'] = API_KEY
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if not resp.ok:
            return None
        data = resp.json()
        if isinstance(data, dict) and data.get('Error Message'):
            return None
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and data[0].get('Error Message'):
            return None
        return data
    except Exception as e:
        print(f"    Error fetching {path}: {e}")
        return None


def safe_float(val, default=None):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_fundamentals(symbol: str) -> Dict[str, Any]:
    data = {'symbol': symbol}

    endpoints = [
        # Financial Statements (quarterly)
        ('income_statement', '/stable/income-statement', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),
        ('balance_sheet', '/stable/balance-sheet-statement', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),
        ('cash_flow', '/stable/cash-flow-statement', {'symbol': symbol, 'period': 'quarter', 'limit': QUARTERS_TO_FETCH}),

        # Financial Statements (annual)
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

        # NEW: Quote (for yearHigh/yearLow, price, sharesOutstanding)
        ('quote', '/stable/quote', {'symbol': symbol}),

        # NEW: Company info (for IPO date)
        ('company_info', '/stable/company-core-information', {'symbol': symbol}),

        # NEW: Institutional sponsorship (I in CAN SLIM)
        ('institutional_holders', '/stable/institutional-holder', {'symbol': symbol}),
        ('mutual_fund_holders', '/stable/mutual-fund-holder', {'symbol': symbol}),
        ('shares_float', '/stable/shares-float', {'symbol': symbol}),
    ]

    for key, path, params in endpoints:
        result = fmp_get(path, params)
        time.sleep(RATE_DELAY)

        # Normalize single-item arrays
        if key.endswith('_ttm') and isinstance(result, list) and len(result) == 1:
            result = result[0]
        elif key == 'financial_scores' and isinstance(result, list) and len(result) == 1:
            result = result[0]
        elif key == 'quote' and isinstance(result, list) and len(result) == 1:
            result = result[0]
        elif key == 'company_info' and isinstance(result, list) and len(result) == 1:
            result = result[0]
        elif key == 'shares_float' and isinstance(result, list) and len(result) == 1:
            result = result[0]

        data[key] = result if result else None

    # Compute margin ratios if missing (FMP /stable/ endpoints omit these)
    for stmt_key in ['income_statement', 'income_statement_annual']:
        stmts = data.get(stmt_key)
        if isinstance(stmts, list):
            for q in stmts:
                rev = safe_float(q.get('revenue'))
                if rev and rev != 0:
                    if q.get('grossProfitRatio') is None and q.get('grossProfit') is not None:
                        q['grossProfitRatio'] = safe_float(q['grossProfit']) / rev
                    if q.get('operatingIncomeRatio') is None and q.get('operatingIncome') is not None:
                        q['operatingIncomeRatio'] = safe_float(q['operatingIncome']) / rev
                    if q.get('netIncomeRatio') is None and q.get('netIncome') is not None:
                        q['netIncomeRatio'] = safe_float(q['netIncome']) / rev

    return data


# ---------------------------------------------------------------------------
# Helper: compute YoY growth between two quarterly values
# ---------------------------------------------------------------------------

def yoy_growth(current, year_ago):
    """Compute YoY % growth. Returns None if either value missing or year_ago is 0."""
    c = safe_float(current)
    y = safe_float(year_ago)
    if c is None or y is None or y == 0:
        return None
    return ((c - y) / abs(y)) * 100


def qoq_growth(current, previous):
    """Compute QoQ % growth."""
    return yoy_growth(current, previous)


def make_check(id: str, label: str, value, threshold: str, status: str, detail: str, source: str) -> Dict:
    return {
        'id': id,
        'label': label,
        'value': value,
        'threshold': threshold,
        'status': status,
        'detail': detail,
        'source': source,
    }


# ---------------------------------------------------------------------------
# C Score: Current Quarterly Earnings (25 pts)
# ---------------------------------------------------------------------------

def compute_c_score(income: List[Dict]) -> Dict:
    """income = list sorted oldest→newest (chronological)."""
    checks = []
    score = 0

    if len(income) < 5:
        checks.append(make_check('c_data', 'Sufficient Data', None, '5+ quarters', 'fail',
                                 f'Only {len(income)} quarters available', ''))
        return {'score': 0, 'max': 20, 'checks': checks}

    latest = income[-1]
    prev = income[-2]
    # Find same quarter last year (4 quarters back)
    yoy_q = income[-5] if len(income) >= 5 else None
    prev_yoy_q = income[-6] if len(income) >= 6 else None

    # --- Check 1: Latest Q EPS YoY growth (6 pts) ---
    eps_yoy = yoy_growth(latest.get('epsDiluted'), yoy_q.get('epsDiluted') if yoy_q else None)
    if eps_yoy is not None:
        if eps_yoy >= 25:
            pts = 6
            status = 'pass'
        elif eps_yoy >= 18:
            pts = 4
            status = 'pass'
        elif eps_yoy >= 10:
            pts = 2
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('c_eps_growth', 'Current Q EPS YoY Growth', round(eps_yoy, 1),
                                 '≥25% (6pts), ≥18% (4pts)', status,
                                 f'{eps_yoy:+.1f}%', "O'Neil Ch.2"))
    else:
        checks.append(make_check('c_eps_growth', 'Current Q EPS YoY Growth', None,
                                 '≥25%', 'info', 'Insufficient data', "O'Neil Ch.2"))

    # --- Check 2: EPS acceleration (4 pts) ---
    prev_eps_yoy = yoy_growth(prev.get('epsDiluted'), prev_yoy_q.get('epsDiluted') if prev_yoy_q else None)
    if eps_yoy is not None and prev_eps_yoy is not None:
        if eps_yoy > prev_eps_yoy:
            pts = 4
            status = 'pass'
            detail = f'Accelerating: {prev_eps_yoy:+.1f}% → {eps_yoy:+.1f}%'
        elif abs(eps_yoy - prev_eps_yoy) < 2:
            pts = 2
            status = 'warn'
            detail = f'Flat: {prev_eps_yoy:+.1f}% → {eps_yoy:+.1f}%'
        else:
            pts = 0
            status = 'fail'
            detail = f'Decelerating: {prev_eps_yoy:+.1f}% → {eps_yoy:+.1f}%'
        score += pts
        checks.append(make_check('c_eps_accel', 'EPS Acceleration', round(eps_yoy - prev_eps_yoy, 1),
                                 'Latest YoY > Prev YoY', status, detail, "O'Neil Ch.2"))

    # --- Check 3: Deceleration SELL signal (-5 penalty) ---
    # Two consecutive quarters where growth rate drops by ≥2/3
    # Only checks the MOST RECENT 3 quarters — past deceleration that has since
    # reversed (re-accelerated) should NOT trigger a current sell signal.
    decel_detected = False
    eps_yoy_series = []
    for i in range(4, len(income)):
        g = yoy_growth(income[i].get('epsDiluted'), income[i - 4].get('epsDiluted'))
        eps_yoy_series.append(g)

    if len(eps_yoy_series) >= 3:
        # Only look at the last 3 data points (current + 2 prior quarters)
        recent = eps_yoy_series[-3:]
        g_prev2, g_prev, g_curr = recent[0], recent[1], recent[2]
        if g_curr is not None and g_prev is not None and g_prev2 is not None:
            if g_prev2 > 0:
                ratio1 = g_prev / g_prev2 if g_prev2 != 0 else 1
                ratio2 = g_curr / g_prev if g_prev != 0 else 1
                if ratio1 <= 0.33 and ratio2 <= 0.33:
                    decel_detected = True

    if decel_detected:
        score -= 5
        checks.append(make_check('c_decel_sell', 'Deceleration SELL Signal', True,
                                 'No 2 consecutive ⅔ slowdowns', 'fail',
                                 'SELL: Two consecutive quarters of ≥⅔ earnings deceleration', "O'Neil Ch.2"))
    else:
        checks.append(make_check('c_decel_sell', 'Deceleration SELL Signal', False,
                                 'No signal', 'pass', 'No deceleration sell signal detected', "O'Neil Ch.2"))

    # --- Check 4: Latest Q sales growth YoY (4 pts) ---
    rev_yoy = yoy_growth(latest.get('revenue'), yoy_q.get('revenue') if yoy_q else None)
    if rev_yoy is not None:
        if rev_yoy >= 25:
            pts = 4
            status = 'pass'
        elif rev_yoy >= 15:
            pts = 3
            status = 'pass'
        elif rev_yoy >= 10:
            pts = 2
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('c_rev_growth', 'Current Q Revenue YoY Growth', round(rev_yoy, 1),
                                 '≥25% (4pts), ≥15% (3pts)', status,
                                 f'{rev_yoy:+.1f}%', "O'Neil Ch.2"))

    # --- Check 5: Sales acceleration over 3 quarters (4 pts) ---
    rev_yoy_series = []
    for i in range(max(0, len(income) - 4), len(income)):
        if i >= 4:
            g = yoy_growth(income[i].get('revenue'), income[i - 4].get('revenue'))
            rev_yoy_series.append(g)

    accel_count = 0
    if len(rev_yoy_series) >= 2:
        for i in range(1, len(rev_yoy_series)):
            if rev_yoy_series[i] is not None and rev_yoy_series[i - 1] is not None:
                if rev_yoy_series[i] > rev_yoy_series[i - 1]:
                    accel_count += 1

    if accel_count >= 3:
        pts = 4
        status = 'pass'
    elif accel_count >= 2:
        pts = 2
        status = 'pass'
    else:
        pts = 0
        status = 'fail'
    score += pts
    checks.append(make_check('c_rev_accel', 'Revenue Acceleration (3Q)', accel_count,
                             '3 consecutive accelerating', status,
                             f'{accel_count} of last quarters accelerating', "O'Neil Ch.2"))

    # --- Check 6: Net margin at/near 8Q high (4 pts) ---
    margins = [safe_float(q.get('netIncomeRatio')) for q in income]
    margins_valid = [m for m in margins if m is not None]
    if margins_valid and margins[-1] is not None:
        latest_margin = margins[-1]
        max_margin = max(margins_valid)
        if max_margin > 0:
            pct_of_high = latest_margin / max_margin
        else:
            pct_of_high = 0

        if latest_margin >= max_margin:
            pts = 3
            status = 'pass'
            detail = f'At 8Q high ({latest_margin * 100:.1f}%)'
        elif pct_of_high >= 0.90:
            pts = 1
            status = 'pass'
            detail = f'Within 10% of 8Q high ({latest_margin * 100:.1f}% vs {max_margin * 100:.1f}%)'
        else:
            pts = 0
            status = 'fail'
            detail = f'Below high ({latest_margin * 100:.1f}% vs {max_margin * 100:.1f}%)'
        score += pts
        checks.append(make_check('c_margin_high', 'Net Margin at/near 8Q High', round(latest_margin * 100, 1),
                                 'At or within 10% of highest', status, detail, "O'Neil Ch.2"))

    return {'score': max(score, 0), 'max': 20, 'checks': checks}


# ---------------------------------------------------------------------------
# A Score: Annual Earnings Growth (20 pts)
# ---------------------------------------------------------------------------

def compute_a_score(income_annual: List[Dict], income_q: List[Dict],
                    ratios_ttm: Any, cash_flow_ttm: Any) -> Dict:
    """income_annual = sorted oldest→newest."""
    checks = []
    score = 0

    annual = list(reversed(income_annual)) if income_annual else []  # oldest first

    # --- Check 1: 3 consecutive years EPS growth (5 pts) ---
    if len(annual) >= 4:
        eps_list = [safe_float(y.get('epsDiluted')) for y in annual]
        # Check last 3 year-over-year changes
        growth_years = []
        for i in range(1, min(4, len(eps_list))):
            if eps_list[i] is not None and eps_list[i - 1] is not None and eps_list[i - 1] != 0:
                growth_years.append(eps_list[i] > eps_list[i - 1])

        up_years = sum(1 for g in growth_years if g)
        total_years = len(growth_years)

        if total_years >= 3 and up_years == total_years:
            pts = 5
            status = 'pass'
        elif total_years >= 3 and up_years >= 2:
            pts = 2
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('a_3yr_growth', '3 Consecutive Years EPS Growth', up_years,
                                 'All 3 years up', status,
                                 f'{up_years}/{total_years} years with EPS growth', "O'Neil Ch.3"))
    else:
        checks.append(make_check('a_3yr_growth', '3 Consecutive Years EPS Growth', None,
                                 'Need 4+ years data', 'info', f'Only {len(annual)} years available', "O'Neil Ch.3"))

    # --- Check 2: Annual EPS growth rate (4 pts) ---
    if len(annual) >= 2:
        latest_eps = safe_float(annual[-1].get('epsDiluted'))
        prev_eps = safe_float(annual[-2].get('epsDiluted'))
        ann_growth = yoy_growth(latest_eps, prev_eps)
        if ann_growth is not None:
            if ann_growth >= 25:
                pts = 4
                status = 'pass'
            elif ann_growth >= 15:
                pts = 3
                status = 'pass'
            elif ann_growth >= 5:
                pts = 1
                status = 'warn'
            else:
                pts = 0
                status = 'fail'
            score += pts
            checks.append(make_check('a_ann_growth', 'Annual EPS Growth Rate', round(ann_growth, 1),
                                     '≥25% (4pts), ≥15% (3pts)', status,
                                     f'{ann_growth:+.1f}%', "O'Neil Ch.3"))

    # --- Check 3: ROE (4 pts) ---
    roe = None
    if ratios_ttm:
        ttm = ratios_ttm[0] if isinstance(ratios_ttm, list) else ratios_ttm
        roe = safe_float(ttm.get('returnOnEquity'))

    if roe is not None:
        roe_pct = roe * 100
        if roe_pct >= 25:
            pts = 4
            status = 'pass'
        elif roe_pct >= 17:
            pts = 3
            status = 'pass'
        elif roe_pct >= 10:
            pts = 1
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('a_roe', 'Return on Equity (TTM)', round(roe_pct, 1),
                                 '≥25% (4pts), ≥17% (3pts)', status,
                                 f'{roe_pct:.1f}%', "O'Neil Ch.3"))

    # --- Check 4: Cash flow/share ≥ EPS × 1.2 (4 pts) ---
    if cash_flow_ttm and income_q:
        cf_ttm = cash_flow_ttm[0] if isinstance(cash_flow_ttm, list) else cash_flow_ttm
        ocf = safe_float(cf_ttm.get('operatingCashFlow'))
        shares = safe_float(income_q[-1].get('weightedAverageShsOutDil'))
        # Compute TTM EPS from last 4 quarters
        ttm_eps = sum(safe_float(q.get('epsDiluted'), 0) for q in income_q[-4:])

        if ocf is not None and shares and shares > 0 and ttm_eps and ttm_eps > 0:
            cf_per_share = ocf / shares
            ratio = cf_per_share / ttm_eps
            if ratio >= 1.2:
                pts = 4
                status = 'pass'
            elif ratio >= 1.0:
                pts = 2
                status = 'pass'
            else:
                pts = 0
                status = 'fail'
            score += pts
            checks.append(make_check('a_cf_eps', 'Cash Flow/Share vs EPS', round(ratio, 2),
                                     'CF/share ≥ EPS × 1.2', status,
                                     f'CF/share: ${cf_per_share:.2f}, EPS: ${ttm_eps:.2f} (ratio: {ratio:.2f}x)',
                                     "O'Neil Ch.3"))

    # --- Check 5: Earnings stability (3 pts) ---
    if len(annual) >= 3:
        eps_list = [safe_float(y.get('epsDiluted')) for y in annual]
        growth_rates = []
        for i in range(1, len(eps_list)):
            g = yoy_growth(eps_list[i], eps_list[i - 1])
            if g is not None:
                growth_rates.append(g)

        if len(growth_rates) >= 2:
            mean = sum(growth_rates) / len(growth_rates)
            variance = sum((g - mean) ** 2 for g in growth_rates) / len(growth_rates)
            stdev = variance ** 0.5

            if stdev < 20:
                pts = 3
                status = 'pass'
            elif stdev < 25:
                pts = 2
                status = 'pass'
            elif stdev < 35:
                pts = 1
                status = 'warn'
            else:
                pts = 0
                status = 'fail'
            score += pts
            checks.append(make_check('a_stability', 'Earnings Stability', round(stdev, 1),
                                     'Stdev <20 (4pts), <25 (3pts)', status,
                                     f'Annual growth stdev: {stdev:.1f}', "O'Neil Ch.3"))

    return {'score': min(score, 20), 'max': 20, 'checks': checks}


# ---------------------------------------------------------------------------
# N Score: New/Catalyst (12 pts)
# ---------------------------------------------------------------------------

def compute_n_score(data: Dict, income: List[Dict], ranking: Optional[Dict]) -> Dict:
    checks = []
    score = 0

    # --- Check 1: IPO age within 10 years (2 pts) ---
    ipo_date_str = None
    if ranking and ranking.get('ipo_date'):
        ipo_date_str = ranking['ipo_date']
    elif data.get('company_info') and isinstance(data['company_info'], dict):
        ipo_date_str = data['company_info'].get('ipoDate')

    if ipo_date_str:
        try:
            ipo_dt = datetime.strptime(ipo_date_str[:10], '%Y-%m-%d').date()
            age_years = (date.today() - ipo_dt).days / 365.25
            if age_years < 5:
                pts = 2
                status = 'pass'
            elif age_years < 10:
                pts = 1
                status = 'pass'
            elif age_years < 15:
                pts = 0
                status = 'warn'
            else:
                pts = 0
                status = 'fail'
            score += pts
            checks.append(make_check('n_ipo_age', 'IPO Age', round(age_years, 1),
                                     '<5y (2pts), <10y (1pt)', status,
                                     f'{age_years:.1f} years since IPO', 'Minervini Ch.11'))
        except (ValueError, TypeError):
            checks.append(make_check('n_ipo_age', 'IPO Age', None, '<10y', 'info',
                                     'IPO date not available', 'Minervini Ch.11'))
    else:
        checks.append(make_check('n_ipo_age', 'IPO Age', None, '<10y', 'info',
                                 'IPO date not available', 'Minervini Ch.11'))

    # --- Check 2: Price within 25% of 52-week high (3 pts) ---
    quote = data.get('quote')
    year_high = None
    current_price = None
    if isinstance(quote, dict):
        year_high = safe_float(quote.get('yearHigh'))
        current_price = safe_float(quote.get('price'))
    if ranking:
        current_price = current_price or safe_float(ranking.get('current_price'))

    if year_high and current_price and year_high > 0:
        pct_from_high = ((year_high - current_price) / year_high) * 100
        if pct_from_high <= 15:
            pts = 3
            status = 'pass'
        elif pct_from_high <= 25:
            pts = 2
            status = 'pass'
        elif pct_from_high <= 35:
            pts = 1
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('n_near_high', 'Price Near 52-Week High', round(pct_from_high, 1),
                                 'Within 25% (3pts), 15% (4pts)', status,
                                 f'{pct_from_high:.1f}% below 52-week high', "O'Neil Ch.4"))

    # --- Check 3: Recent acceleration in EPS/Rev/Margin (3 pts) ---
    accel_count = 0
    if len(income) >= 6:
        # EPS YoY acceleration
        eps_yoy_latest = yoy_growth(income[-1].get('epsDiluted'), income[-5].get('epsDiluted') if len(income) >= 5 else None)
        eps_yoy_prev = yoy_growth(income[-2].get('epsDiluted'), income[-6].get('epsDiluted') if len(income) >= 6 else None)
        if eps_yoy_latest is not None and eps_yoy_prev is not None and eps_yoy_latest > eps_yoy_prev:
            accel_count += 1

        # Revenue YoY acceleration
        rev_yoy_latest = yoy_growth(income[-1].get('revenue'), income[-5].get('revenue') if len(income) >= 5 else None)
        rev_yoy_prev = yoy_growth(income[-2].get('revenue'), income[-6].get('revenue') if len(income) >= 6 else None)
        if rev_yoy_latest is not None and rev_yoy_prev is not None and rev_yoy_latest > rev_yoy_prev:
            accel_count += 1

        # Margin acceleration
        m_latest = safe_float(income[-1].get('netIncomeRatio'))
        m_prev = safe_float(income[-2].get('netIncomeRatio'))
        if m_latest is not None and m_prev is not None and m_latest > m_prev:
            accel_count += 1

    if accel_count >= 2:
        pts = 3
        status = 'pass'
    elif accel_count == 1:
        pts = 1
        status = 'warn'
    else:
        pts = 0
        status = 'fail'
    score += pts
    checks.append(make_check('n_accel', 'Recent Acceleration (EPS/Rev/Margin)', accel_count,
                             '2+ metrics accelerating', status,
                             f'{accel_count}/3 metrics accelerating', "O'Neil Ch.2"))

    # --- Check 4: Positive earnings surprises (4 pts) ---
    beats = 0
    if ranking and ranking.get('earnings'):
        earnings_data = ranking['earnings']
        beats = earnings_data.get('eps_beats') or 0
        if isinstance(beats, int):
            pass
        else:
            beats = 0

    if beats >= 3:
        pts = 4
        status = 'pass'
    elif beats >= 2:
        pts = 2
        status = 'pass'
    elif beats >= 1:
        pts = 1
        status = 'warn'
    else:
        pts = 0
        status = 'fail'
    score += pts
    checks.append(make_check('n_surprises', 'Positive EPS Surprises (Last 4Q)', beats,
                             '≥3 beats (4pts), ≥2 (2pts)', status,
                             f'{beats} positive surprises', 'Minervini Ch.7'))

    return {'score': min(score, 12), 'max': 12, 'checks': checks}


# ---------------------------------------------------------------------------
# S Score: Supply & Demand (13 pts)
# ---------------------------------------------------------------------------

def compute_s_score(income: List[Dict], balance: List[Dict], cash_flow: List[Dict],
                    quote: Any) -> Dict:
    checks = []
    score = 0

    # --- Check 1: D/E ratio declining over 2-3 years (4 pts) ---
    if len(balance) >= 5:
        de_ratios = []
        for q in balance:
            debt = safe_float(q.get('totalDebt', 0))
            equity = safe_float(q.get('totalStockholdersEquity'))
            if equity and equity > 0 and debt is not None:
                de_ratios.append(debt / equity)
            else:
                de_ratios.append(None)

        valid_de = [(i, d) for i, d in enumerate(de_ratios) if d is not None]
        if len(valid_de) >= 4:
            old = valid_de[0][1]
            new = valid_de[-1][1]
            if new < old - 0.05:
                pts = 4
                status = 'pass'
                detail = f'Declining: {old:.2f} → {new:.2f}'
            elif abs(new - old) <= 0.05:
                pts = 3
                status = 'pass'
                detail = f'Stable: {old:.2f} → {new:.2f}'
            else:
                pts = 0
                status = 'fail'
                detail = f'Increasing: {old:.2f} → {new:.2f}'
            score += pts
            checks.append(make_check('s_de_trend', 'D/E Ratio Trend', round(new, 2),
                                     'Declining over time', status, detail, "O'Neil Ch.5"))

    # --- Check 2: Buybacks - shares outstanding declining (4 pts) ---
    if len(income) >= 3:
        shares = [safe_float(q.get('weightedAverageShsOutDil')) for q in income]
        valid_shares = [s for s in shares if s is not None]
        if len(valid_shares) >= 3:
            declining_count = 0
            for i in range(1, len(valid_shares)):
                if valid_shares[i] < valid_shares[i - 1]:
                    declining_count += 1

            if declining_count >= 2:
                pts = 4
                status = 'pass'
            elif declining_count >= 1:
                pts = 2
                status = 'pass'
            else:
                pts = 0
                status = 'fail'
            pct_change = ((valid_shares[-1] - valid_shares[0]) / valid_shares[0]) * 100 if valid_shares[0] else 0
            score += pts
            checks.append(make_check('s_buybacks', 'Share Buybacks (Declining Shares)', round(pct_change, 1),
                                     'Shares declining 2+Q', status,
                                     f'Shares outstanding change: {pct_change:+.1f}%', "O'Neil Ch.5"))

    # --- Check 3: Shares outstanding absolute size (3 pts) ---
    latest_shares = None
    if income:
        latest_shares = safe_float(income[-1].get('weightedAverageShsOutDil'))
    if latest_shares:
        shares_m = latest_shares / 1e6
        if shares_m < 100:
            pts = 3
            status = 'pass'
        elif shares_m < 500:
            pts = 2
            status = 'pass'
        elif shares_m < 1000:
            pts = 1
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('s_float_size', 'Shares Outstanding', round(shares_m, 0),
                                 '<100M (3pts), <500M (2pts)', status,
                                 f'{shares_m:.0f}M shares', "O'Neil Ch.5"))

    # --- Check 4: Net buyback % of market cap (2 pts) ---
    if cash_flow and isinstance(quote, dict):
        mkt_cap = safe_float(quote.get('marketCap'))
        buyback_amt = abs(safe_float(cash_flow[-1].get('commonStockRepurchased'), 0))
        if mkt_cap and mkt_cap > 0:
            buyback_pct = (buyback_amt / mkt_cap) * 100
            if buyback_pct > 1:
                pts = 2
                status = 'pass'
            elif buyback_pct > 0.5:
                pts = 1
                status = 'pass'
            else:
                pts = 0
                status = 'fail'
            score += pts
            checks.append(make_check('s_buyback_pct', 'Buyback % of Market Cap', round(buyback_pct, 2),
                                     '>1% (2pts), >0.5% (1pt)', status,
                                     f'{buyback_pct:.2f}% of market cap', "O'Neil Ch.5"))

    return {'score': min(score, 13), 'max': 13, 'checks': checks}


# ---------------------------------------------------------------------------
# SEPA Score: Minervini Overlay (20 pts)
# ---------------------------------------------------------------------------

def compute_sepa_score(income: List[Dict], balance: List[Dict], cash_flow: List[Dict]) -> Dict:
    checks = []
    score = 0

    # --- Check 1: Code 33 — 3Q consecutive acceleration in EPS + Rev + Margins (6 pts) ---
    code_33_detected = False
    code_33_quarters = 0
    accel_metrics = 0

    if len(income) >= 7:  # Need 7 quarters: 3 current + 4 for YoY
        # Compute YoY growth for each quarter
        eps_yoy_vals = []
        rev_yoy_vals = []
        op_margins = []

        for i in range(4, len(income)):
            eps_yoy_vals.append(yoy_growth(income[i].get('epsDiluted'), income[i - 4].get('epsDiluted')))
            rev_yoy_vals.append(yoy_growth(income[i].get('revenue'), income[i - 4].get('revenue')))
            op_margins.append(safe_float(income[i].get('operatingIncomeRatio')))

        # Check for 3 consecutive quarters of acceleration in all three
        if len(eps_yoy_vals) >= 3:
            eps_accel = all(eps_yoy_vals[i] is not None and eps_yoy_vals[i - 1] is not None
                           and eps_yoy_vals[i] > eps_yoy_vals[i - 1]
                           for i in range(len(eps_yoy_vals) - 2, len(eps_yoy_vals)))
            rev_accel = all(rev_yoy_vals[i] is not None and rev_yoy_vals[i - 1] is not None
                           and rev_yoy_vals[i] > rev_yoy_vals[i - 1]
                           for i in range(len(rev_yoy_vals) - 2, len(rev_yoy_vals)))
            margin_accel = all(op_margins[i] is not None and op_margins[i - 1] is not None
                              and op_margins[i] > op_margins[i - 1]
                              for i in range(len(op_margins) - 2, len(op_margins)))

            accel_metrics = sum([eps_accel, rev_accel, margin_accel])
            code_33_detected = accel_metrics == 3

            # Count consecutive quarters
            if code_33_detected:
                code_33_quarters = 3

    if code_33_detected:
        pts = 6
        status = 'pass'
    elif accel_metrics >= 2:
        pts = 3
        status = 'warn'
    else:
        pts = 0
        status = 'fail'
    score += pts

    code_33_data = {
        'detected': code_33_detected,
        'consecutive_quarters': code_33_quarters,
        'checks': [make_check('sepa_code33', 'Code 33 (Triple Acceleration)', code_33_detected,
                              '3Q accel in EPS + Rev + Margins', status,
                              f'{"ACTIVE" if code_33_detected else "Not detected"} — {accel_metrics}/3 metrics accelerating',
                              'Minervini Ch.8')]
    }

    # --- Check 2: Inventory vs sales growth (3 pts) ---
    if len(income) >= 2 and len(balance) >= 2:
        rev_growth = qoq_growth(income[-1].get('revenue'), income[-2].get('revenue'))
        inv_growth = qoq_growth(balance[-1].get('inventory'), balance[-2].get('inventory'))

        if inv_growth is not None and rev_growth is not None:
            if rev_growth == 0:
                ratio = abs(inv_growth) if inv_growth else 0
            else:
                ratio = inv_growth / abs(rev_growth) if rev_growth != 0 else 0

            if inv_growth <= rev_growth or (inv_growth is not None and inv_growth <= 0):
                pts = 3
                status = 'pass'
            elif ratio < 2:
                pts = 2
                status = 'warn'
            elif ratio >= 4:
                pts = 0
                status = 'fail'
            else:
                pts = 1
                status = 'warn'
            score += pts
            checks.append(make_check('sepa_inv_sales', 'Inventory vs Sales Growth', round(ratio, 1) if rev_growth else None,
                                     'Inventory ≤ sales growth', status,
                                     f'Inv: {inv_growth:+.1f}% vs Rev: {rev_growth:+.1f}%', 'Minervini Ch.8'))
        else:
            checks.append(make_check('sepa_inv_sales', 'Inventory vs Sales Growth', None,
                                     'Inventory ≤ sales growth', 'info',
                                     'No inventory data (may be service company)', 'Minervini Ch.8'))
            score += 3  # Don't penalize service companies with no inventory

    # --- Check 3: Receivables vs sales growth (3 pts) ---
    if len(income) >= 2 and len(balance) >= 2:
        recv_growth = qoq_growth(
            balance[-1].get('netReceivables', balance[-1].get('accountsReceivables')),
            balance[-2].get('netReceivables', balance[-2].get('accountsReceivables'))
        )
        rev_growth = qoq_growth(income[-1].get('revenue'), income[-2].get('revenue'))

        if recv_growth is not None and rev_growth is not None:
            if rev_growth == 0:
                ratio = abs(recv_growth) if recv_growth else 0
            else:
                ratio = recv_growth / abs(rev_growth) if rev_growth != 0 else 0

            if recv_growth <= rev_growth or (recv_growth is not None and recv_growth <= 0):
                pts = 3
                status = 'pass'
            elif ratio < 2:
                pts = 2
                status = 'warn'
            elif ratio >= 3:
                pts = 0
                status = 'fail'
            else:
                pts = 1
                status = 'warn'
            score += pts
            checks.append(make_check('sepa_recv_sales', 'Receivables vs Sales Growth',
                                     round(ratio, 1) if rev_growth else None,
                                     'Receivables ≤ sales growth', status,
                                     f'Recv: {recv_growth:+.1f}% vs Rev: {rev_growth:+.1f}%', 'Minervini Ch.8'))

    # --- Check 4: Margin expansion — gross + net (4 pts) ---
    if len(income) >= 5:
        gross_latest = safe_float(income[-1].get('grossProfitRatio'))
        gross_yoy = safe_float(income[-5].get('grossProfitRatio'))
        net_latest = safe_float(income[-1].get('netIncomeRatio'))
        net_yoy = safe_float(income[-5].get('netIncomeRatio'))

        gross_expanding = gross_latest is not None and gross_yoy is not None and gross_latest > gross_yoy
        net_expanding = net_latest is not None and net_yoy is not None and net_latest > net_yoy

        if gross_expanding and net_expanding:
            pts = 4
            status = 'pass'
        elif gross_expanding or net_expanding:
            pts = 2
            status = 'warn'
        elif gross_latest is not None and gross_yoy is not None and abs(gross_latest - gross_yoy) < 0.01:
            pts = 1
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('sepa_margin_exp', 'Margin Expansion (Gross + Net)', None,
                                 'Both expanding YoY', status,
                                 f'Gross: {"expanding" if gross_expanding else "contracting"}, '
                                 f'Net: {"expanding" if net_expanding else "contracting"}',
                                 'Minervini Ch.7'))

    # --- Check 5: SBC dilution (2 pts) ---
    if cash_flow and income:
        sbc = safe_float(cash_flow[-1].get('stockBasedCompensation'), 0)
        ni = safe_float(income[-1].get('netIncome'))
        if ni and ni > 0:
            sbc_pct = (sbc / ni) * 100
            if sbc_pct < 10:
                pts = 2
                status = 'pass'
            elif sbc_pct < 20:
                pts = 1
                status = 'warn'
            else:
                pts = 0
                status = 'fail'
            score += pts
            checks.append(make_check('sepa_sbc', 'SBC Dilution Impact', round(sbc_pct, 1),
                                     'SBC <10% of NI', status,
                                     f'SBC is {sbc_pct:.1f}% of net income', 'Minervini Ch.8'))

    # --- Check 6: Leadership profile — EPS growth 20%+ (2 pts) ---
    if len(income) >= 5:
        eps_yoy = yoy_growth(income[-1].get('epsDiluted'), income[-5].get('epsDiluted'))
        if eps_yoy is not None:
            if eps_yoy >= 35:
                pts = 2
                status = 'pass'
            elif eps_yoy >= 20:
                pts = 1
                status = 'pass'
            else:
                pts = 0
                status = 'fail'
            score += pts
            checks.append(make_check('sepa_leadership', 'Leadership Profile (EPS 20%+)', round(eps_yoy, 1),
                                     '≥35% (2pts), ≥20% (1pt)', status,
                                     f'EPS YoY: {eps_yoy:+.1f}%', 'Minervini Ch.6'))

    return {'score': min(score, 20), 'max': 20, 'checks': checks, 'code_33': code_33_data}


# ---------------------------------------------------------------------------
# I Score: Institutional Sponsorship (15 pts)
# ---------------------------------------------------------------------------

# Top fund families — used for quality check
TOP_FUNDS = {
    'vanguard', 'fidelity', 'blackrock', 'state street', 't. rowe price',
    'capital group', 'wellington', 'jpmorgan', 'goldman sachs', 'morgan stanley',
    'invesco', 'american funds', 'schwab', 'dimensional', 'northern trust',
    'pimco', 'ark invest', 'berkshire hathaway',
}


def _match_top_fund(name: str) -> bool:
    lower = name.lower()
    return any(f in lower for f in TOP_FUNDS)


def compute_i_score(data: Dict, quote: Any) -> Dict:
    """Institutional Sponsorship score from O'Neil Ch.6."""
    checks = []
    score = 0

    inst_holders = data.get('institutional_holders')
    mf_holders = data.get('mutual_fund_holders')
    float_data = data.get('shares_float')

    # --- Check 1: Number of institutional holders (4 pts) ---
    holder_count = 0
    if isinstance(inst_holders, list):
        holder_count = len(inst_holders)
    elif isinstance(mf_holders, list):
        holder_count = len(mf_holders)

    if holder_count >= 50:
        pts = 4
        status = 'pass'
    elif holder_count >= 20:
        pts = 3
        status = 'pass'
    elif holder_count >= 10:
        pts = 1
        status = 'warn'
    else:
        pts = 0
        status = 'fail'
    score += pts
    checks.append(make_check('i_holder_count', 'Number of Institutional Holders', holder_count,
                             '≥50 (4pts), ≥20 (3pts)', status,
                             f'{holder_count} institutional holders', "O'Neil Ch.6"))

    # --- Check 2: Quality — top funds among holders (3 pts) ---
    top_fund_count = 0
    top_fund_names = []
    if isinstance(inst_holders, list):
        for h in inst_holders:
            name = h.get('holder') or h.get('investorName') or ''
            if _match_top_fund(name):
                top_fund_count += 1
                if len(top_fund_names) < 3:
                    top_fund_names.append(name.split(' ')[0])  # First word
    if isinstance(mf_holders, list) and top_fund_count == 0:
        for h in mf_holders:
            name = h.get('holder') or h.get('investorName') or ''
            if _match_top_fund(name):
                top_fund_count += 1
                if len(top_fund_names) < 3:
                    top_fund_names.append(name.split(' ')[0])

    if top_fund_count >= 3:
        pts = 3
        status = 'pass'
    elif top_fund_count >= 1:
        pts = 2
        status = 'pass'
    else:
        pts = 0
        status = 'fail'
    score += pts
    detail = f'{top_fund_count} top-tier funds' + (f' ({", ".join(top_fund_names)})' if top_fund_names else '')
    checks.append(make_check('i_quality', 'Quality: Top Funds Among Holders', top_fund_count,
                             '≥3 top funds (3pts), ≥1 (2pts)', status, detail, "O'Neil Ch.6"))

    # --- Check 3: Institutional ownership trend — net change (4 pts) ---
    net_change = 0
    change_count = 0
    if isinstance(inst_holders, list):
        for h in inst_holders:
            ch = safe_float(h.get('change'))
            if ch is not None:
                net_change += ch
                change_count += 1

    if change_count > 0:
        if net_change > 0:
            pts = 4
            status = 'pass'
            detail = f'Net increase: {net_change:+,.0f} shares across {change_count} holders'
        elif net_change == 0:
            pts = 2
            status = 'warn'
            detail = f'Stable across {change_count} holders'
        else:
            pts = 0
            status = 'fail'
            detail = f'Net decrease: {net_change:+,.0f} shares across {change_count} holders'
        score += pts
        checks.append(make_check('i_trend', 'Institutional Ownership Trend (QoQ)', net_change,
                                 'Increasing (4pts), Stable (2pts)', status, detail, "O'Neil Ch.6"))
    else:
        checks.append(make_check('i_trend', 'Institutional Ownership Trend (QoQ)', None,
                                 'Increasing', 'info', 'Change data not available', "O'Neil Ch.6"))

    # --- Check 4: Overowned warning (2 pts) ---
    inst_ownership_pct = None
    if isinstance(float_data, dict):
        free_float = safe_float(float_data.get('freeFloat'))
        if free_float is not None:
            inst_ownership_pct = (1 - free_float / 100) * 100 if free_float <= 100 else None
    # Fallback: estimate from shares
    if inst_ownership_pct is None and isinstance(inst_holders, list) and isinstance(quote, dict):
        total_inst_shares = sum(safe_float(h.get('shares'), 0) for h in inst_holders)
        outstanding = safe_float(quote.get('sharesOutstanding'))
        if outstanding and outstanding > 0 and total_inst_shares > 0:
            inst_ownership_pct = (total_inst_shares / outstanding) * 100

    if inst_ownership_pct is not None:
        if inst_ownership_pct < 50:
            pts = 2
            status = 'pass'
        elif inst_ownership_pct < 70:
            pts = 1
            status = 'warn'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('i_overowned', 'Overowned Warning', round(inst_ownership_pct, 1),
                                 '<50% (2pts), <70% (1pt)', status,
                                 f'{inst_ownership_pct:.1f}% institutional ownership', "O'Neil Ch.6"))
    else:
        checks.append(make_check('i_overowned', 'Overowned Warning', None,
                                 '<70% institutional', 'info', 'Ownership data not available', "O'Neil Ch.6"))

    # --- Check 5: Float size (2 pts) ---
    float_shares = None
    if isinstance(float_data, dict):
        float_shares = safe_float(float_data.get('floatShares'))
    # Fallback to shares outstanding from quote
    if float_shares is None and isinstance(quote, dict):
        float_shares = safe_float(quote.get('sharesOutstanding'))

    if float_shares is not None:
        float_m = float_shares / 1e6
        if float_m < 50:
            pts = 2
            status = 'pass'
        elif float_m < 200:
            pts = 1
            status = 'pass'
        else:
            pts = 0
            status = 'fail'
        score += pts
        checks.append(make_check('i_float', 'Float Size', round(float_m, 0),
                                 '<50M (2pts), <200M (1pt)', status,
                                 f'{float_m:.0f}M float shares', "O'Neil Ch.5"))

    return {
        'score': min(score, 15), 'max': 15, 'checks': checks,
        'holder_count': holder_count,
        'top_funds': top_fund_names,
        'inst_ownership_pct': round(inst_ownership_pct, 1) if inst_ownership_pct else None,
        'float_shares_m': round(float_shares / 1e6, 1) if float_shares else None,
    }


# ---------------------------------------------------------------------------
# Trend Template: 8 Criteria (pass/fail)
# ---------------------------------------------------------------------------

def compute_trend_template(ranking: Optional[Dict], quote: Any) -> Dict:
    checks = []
    passing = 0

    if not ranking:
        return {'passing': 0, 'total': 8, 'checks': [
            make_check('tt_no_data', 'No ranking data', None, '', 'info',
                       'Stock not found in rankings.json', 'Minervini Ch.5')
        ]}

    price = safe_float(ranking.get('current_price'))
    ma_50 = safe_float(ranking.get('ma_50'))
    ma_150 = safe_float(ranking.get('ma_150'))
    ma_200 = safe_float(ranking.get('ma_200'))
    rs_rank = safe_float(ranking.get('rs_rank'))

    year_high = None
    year_low = None
    if isinstance(quote, dict):
        year_high = safe_float(quote.get('yearHigh'))
        year_low = safe_float(quote.get('yearLow'))

    # 1. Price > 150-day AND 200-day MA
    if price and ma_150 and ma_200:
        ok = price > ma_150 and price > ma_200
        if ok:
            passing += 1
        checks.append(make_check('tt_price_above_150_200', 'Price > 150-day & 200-day MA',
                                 price, 'Price above both MAs', 'pass' if ok else 'fail',
                                 f'Price: ${price:.2f}, MA150: ${ma_150:.2f}, MA200: ${ma_200:.2f}',
                                 'Minervini Ch.5'))

    # 2. 150-day MA > 200-day MA
    if ma_150 and ma_200:
        ok = ma_150 > ma_200
        if ok:
            passing += 1
        checks.append(make_check('tt_150_above_200', '150-day MA > 200-day MA',
                                 round(ma_150 - ma_200, 2), 'MA150 > MA200', 'pass' if ok else 'fail',
                                 f'MA150: ${ma_150:.2f}, MA200: ${ma_200:.2f}',
                                 'Minervini Ch.5'))

    # 3. 200-day MA trending up (approximate: if MA150 > MA200, 200 is likely rising)
    if ma_150 and ma_200:
        ok = ma_150 > ma_200  # Proxy: if 150 > 200 for an extended period, 200 is trending up
        if ok:
            passing += 1
        checks.append(make_check('tt_200_trending_up', '200-day MA Trending Up',
                                 None, 'Rising for 1+ month', 'pass' if ok else 'fail',
                                 f'{"Likely trending up" if ok else "May not be trending up"} (MA150 {">" if ok else "<"} MA200)',
                                 'Minervini Ch.5'))

    # 4. 50-day MA > 150-day AND 200-day MA
    if ma_50 and ma_150 and ma_200:
        ok = ma_50 > ma_150 and ma_50 > ma_200
        if ok:
            passing += 1
        checks.append(make_check('tt_50_above_150_200', '50-day MA > 150-day & 200-day MA',
                                 round(ma_50, 2), 'MA50 above both', 'pass' if ok else 'fail',
                                 f'MA50: ${ma_50:.2f}, MA150: ${ma_150:.2f}, MA200: ${ma_200:.2f}',
                                 'Minervini Ch.5'))

    # 5. Price > 50-day MA
    if price and ma_50:
        ok = price > ma_50
        if ok:
            passing += 1
        checks.append(make_check('tt_price_above_50', 'Price > 50-day MA',
                                 price, 'Price above MA50', 'pass' if ok else 'fail',
                                 f'Price: ${price:.2f}, MA50: ${ma_50:.2f}',
                                 'Minervini Ch.5'))

    # 6. Price ≥30% above 52-week low
    if price and year_low and year_low > 0:
        pct_above_low = ((price - year_low) / year_low) * 100
        ok = pct_above_low >= 30
        if ok:
            passing += 1
        checks.append(make_check('tt_30pct_above_low', 'Price ≥30% Above 52-Week Low',
                                 round(pct_above_low, 1), '≥30% above low', 'pass' if ok else 'fail',
                                 f'{pct_above_low:.1f}% above low (${year_low:.2f})',
                                 'Minervini Ch.5'))

    # 7. Price within 25% of 52-week high
    if price and year_high and year_high > 0:
        pct_from_high = ((year_high - price) / year_high) * 100
        ok = pct_from_high <= 25
        if ok:
            passing += 1
        checks.append(make_check('tt_within_25pct_high', 'Price Within 25% of 52-Week High',
                                 round(pct_from_high, 1), '≤25% from high', 'pass' if ok else 'fail',
                                 f'{pct_from_high:.1f}% below high (${year_high:.2f})',
                                 'Minervini Ch.5'))

    # 8. RS rating ≥70
    if rs_rank is not None:
        ok = rs_rank >= 70
        if ok:
            passing += 1
        status = 'pass' if rs_rank >= 80 else ('pass' if ok else 'fail')
        checks.append(make_check('tt_rs_70', 'RS Rating ≥70 (prefer 80+)',
                                 int(rs_rank), '≥70, prefer 80+', status,
                                 f'RS Rank: {int(rs_rank)}',
                                 'Minervini Ch.5'))

    return {'passing': passing, 'total': 8, 'checks': checks}


# ---------------------------------------------------------------------------
# Flags generation
# ---------------------------------------------------------------------------

def generate_flags(c_score, a_score, n_score, s_score, i_score, sepa_score, trend_template,
                   income: List[Dict], ranking: Optional[Dict], quote: Any) -> List[Dict]:
    flags = []

    for section in [c_score, a_score, n_score, s_score, i_score,
                    sepa_score.get('earnings_quality', sepa_score)]:
        if not isinstance(section, dict):
            continue
        for check in section.get('checks', []):
            label = check.get('label', '')
            detail = check.get('detail', '')
            msg = f'{label}: {detail}' if label and detail and label not in detail else (detail or label)
            if check['status'] == 'pass' and check['value'] is not None:
                flags.append({'type': 'green', 'category': check['id'], 'message': msg,
                              'source': check['source']})
            elif check['status'] == 'fail':
                flag_type = 'red' if 'SELL' in detail or 'RED' in label else 'yellow'
                flags.append({'type': flag_type, 'category': check['id'], 'message': msg,
                              'source': check['source']})

    # Code 33 flag
    code_33 = sepa_score.get('code_33', {})
    if code_33.get('detected'):
        flags.append({'type': 'green', 'category': 'code_33', 'message': 'CODE 33 ACTIVE: Triple acceleration in EPS, Revenue & Operating Margins',
                      'source': 'Minervini Ch.8'})

    # Trend Template flag
    tt = trend_template
    if tt.get('passing', 0) == 8:
        flags.append({'type': 'green', 'category': 'trend_template', 'message': 'All 8 Trend Template criteria met',
                      'source': 'Minervini Ch.5'})
    elif tt.get('passing', 0) >= 6:
        flags.append({'type': 'yellow', 'category': 'trend_template',
                      'message': f'Trend Template: {tt["passing"]}/8 criteria met',
                      'source': 'Minervini Ch.5'})
    elif tt.get('passing', 0) < 6:
        flags.append({'type': 'red', 'category': 'trend_template',
                      'message': f'Trend Template: Only {tt["passing"]}/8 criteria met',
                      'source': 'Minervini Ch.5'})

    # --- GAP 2: Sales validation flag ---
    # EPS growing but revenue not backing it
    if len(income) >= 5:
        eps_yoy = yoy_growth(income[-1].get('epsDiluted'), income[-5].get('epsDiluted'))
        rev_yoy = yoy_growth(income[-1].get('revenue'), income[-5].get('revenue'))
        if eps_yoy is not None and rev_yoy is not None:
            if eps_yoy >= 25 and rev_yoy < 10:
                flags.append({'type': 'red', 'category': 'sales_validation',
                              'message': f'EPS +{eps_yoy:.0f}% not backed by sales ({rev_yoy:+.0f}%) — unsustainable',
                              'source': "O'Neil Ch.2"})
            if rev_yoy < 0 and eps_yoy > 0:
                flags.append({'type': 'yellow', 'category': 'rev_eps_diverge',
                              'message': f'Revenue declining ({rev_yoy:+.0f}%) while EPS growing ({eps_yoy:+.0f}%)',
                              'source': "O'Neil Ch.2"})

    # --- GAP 4: Earnings declining YoY sell signal ---
    if len(income) >= 6:
        latest_eps_yoy = yoy_growth(income[-1].get('epsDiluted'), income[-5].get('epsDiluted'))
        prev_eps_yoy = yoy_growth(income[-2].get('epsDiluted'), income[-6].get('epsDiluted'))
        if latest_eps_yoy is not None and prev_eps_yoy is not None:
            if latest_eps_yoy < 0 and prev_eps_yoy < 0:
                flags.append({'type': 'red', 'category': 'eps_declining_sell',
                              'message': f'SELL: 2 consecutive quarters of declining EPS YoY ({prev_eps_yoy:+.0f}% → {latest_eps_yoy:+.0f}%)',
                              'source': "O'Neil Ch.10"})

    # --- GAP 5: RS below leader threshold ---
    if ranking:
        rs = safe_float(ranking.get('rs_rank'))
        if rs is not None:
            if rs < 50:
                flags.append({'type': 'red', 'category': 'rs_lagging',
                              'message': f'RS Rank {int(rs)} — lagging market, potential sell',
                              'source': "O'Neil Ch.7"})
            elif rs < 70:
                flags.append({'type': 'yellow', 'category': 'rs_below_leader',
                              'message': f'RS Rank {int(rs)} — below leader threshold (70+)',
                              'source': "O'Neil Ch.7"})

    # --- GAP 6: Price context flag ---
    current_price = None
    if isinstance(quote, dict):
        current_price = safe_float(quote.get('price'))
    if not current_price and ranking:
        current_price = safe_float(ranking.get('current_price'))
    if current_price and current_price < 15:
        flags.append({'type': 'yellow', 'category': 'low_price',
                      'message': f'Price ${current_price:.2f} below institutional-quality range ($15+)',
                      'source': "O'Neil Ch.5"})

    # --- GAP 10: Below 200-day MA sell signal ---
    if ranking:
        ma_200 = safe_float(ranking.get('ma_200'))
        price = safe_float(ranking.get('current_price'))
        if ma_200 and price and ma_200 > 0:
            pct_below = ((ma_200 - price) / ma_200) * 100
            if pct_below > 5:
                flags.append({'type': 'red', 'category': 'below_200ma_sell',
                              'message': f'SELL: Price {pct_below:.1f}% below 200-day MA (${ma_200:.2f})',
                              'source': "O'Neil Ch.10"})

    # Sort: red first, yellow, green
    order = {'red': 0, 'yellow': 1, 'green': 2}
    flags.sort(key=lambda f: order.get(f['type'], 3))

    return flags


# ---------------------------------------------------------------------------
# Main scoring orchestrator
# ---------------------------------------------------------------------------

def compute_eps_rating(c_score: Dict, a_score: Dict) -> int:
    """Compute a 1-99 EPS Rating: 40% current Q EPS YoY, 60% annual growth."""
    # Get current Q EPS YoY from c_score checks
    c_eps_yoy = None
    for check in c_score.get('checks', []):
        if check['id'] == 'c_eps_growth' and check['value'] is not None:
            c_eps_yoy = check['value']
            break

    # Get annual growth from a_score checks
    a_growth = None
    for check in a_score.get('checks', []):
        if check['id'] == 'a_ann_growth' and check['value'] is not None:
            a_growth = check['value']
            break

    # Normalize each to 0-99 range based on O'Neil thresholds
    # Current Q: 0% → 30, 25% → 70, 50% → 85, 100%+ → 99
    if c_eps_yoy is not None:
        c_norm = min(99, max(1, 30 + (c_eps_yoy / 100) * 69))
    else:
        c_norm = 30  # Unknown = below average

    # Annual: 0% → 30, 25% → 70, 50% → 85, 100%+ → 99
    if a_growth is not None:
        a_norm = min(99, max(1, 30 + (a_growth / 100) * 69))
    else:
        a_norm = 30

    return int(min(99, max(1, c_norm * 0.4 + a_norm * 0.6)))


def compute_canslim_sepa(data: Dict, ranking: Optional[Dict]) -> Dict:
    income = list(reversed(data.get('income_statement') or []))
    balance = list(reversed(data.get('balance_sheet') or []))
    cash_flow = list(reversed(data.get('cash_flow') or []))
    income_annual = data.get('income_statement_annual') or []

    ratios_ttm = data.get('ratios_ttm')
    cash_flow_ttm = data.get('cash_flow_ttm')
    quote = data.get('quote')

    # Compute each score
    c = compute_c_score(income)
    a = compute_a_score(income_annual, income, ratios_ttm, cash_flow_ttm)
    n = compute_n_score(data, income, ranking)
    s = compute_s_score(income, balance, cash_flow, quote)
    i = compute_i_score(data, quote)
    sepa_result = compute_sepa_score(income, balance, cash_flow)

    # Extract code_33 and earnings_quality from SEPA
    code_33 = sepa_result.pop('code_33', {'detected': False, 'consecutive_quarters': 0, 'checks': []})
    sepa_eq = {'score': sepa_result['score'], 'max': sepa_result['max'], 'checks': sepa_result['checks']}

    tt = compute_trend_template(ranking, quote)

    # EPS Rating composite (Gap 8)
    eps_rating = compute_eps_rating(c, a)

    # Flags (with new sell signals)
    flags = generate_flags(c, a, n, s, i, {'earnings_quality': sepa_eq, 'code_33': code_33}, tt,
                          income, ranking, quote)

    # Overall score: C(20) + A(20) + N(12) + S(13) + I(15) + SEPA(20) = 100
    canslim_total = c['score'] + a['score'] + n['score'] + s['score'] + i['score']
    canslim_max = c['max'] + a['max'] + n['max'] + s['max'] + i['max']
    sepa_total = sepa_eq['score']
    sepa_max = sepa_eq['max']
    overall = max(canslim_total + sepa_total, 0)

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
        'overall_rating': rating,
        'eps_rating': eps_rating,
        'canslim': {
            'c_score': c,
            'a_score': a,
            'n_score': n,
            's_score': s,
            'i_score': i,
            'total': canslim_total,
            'max': canslim_max,
        },
        'sepa': {
            'trend_template': tt,
            'code_33': code_33,
            'earnings_quality': sepa_eq,
            'total': sepa_total,
            'max': sepa_max,
        },
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
    print("FUNDAMENTALS PIPELINE (CAN SLIM + SEPA)")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Load rankings
    if not os.path.exists('rankings.json'):
        print("ERROR: rankings.json not found. Run process_stocks.py first.")
        sys.exit(1)

    with open('rankings.json', 'r') as f:
        rankings = json.load(f)

    all_stocks = rankings.get('data', [])
    rankings_map = {s['symbol']: s for s in all_stocks}

    # Filter to RS rank 70+
    min_rs = int(os.environ.get('FUNDAMENTALS_MIN_RS', '70'))
    filtered = [s for s in all_stocks if s.get('rs_rank', 0) >= min_rs]
    all_symbols = [s['symbol'] for s in filtered]
    print(f"Found {len(all_stocks)} total, {len(all_symbols)} with RS >= {min_rs}")

    # Optional limit
    limit = os.environ.get('FUNDAMENTALS_LIMIT')
    if limit:
        all_symbols = all_symbols[:int(limit)]
        print(f"Limited to {len(all_symbols)} symbols")

    os.makedirs('fundamentals', exist_ok=True)

    # Determine freshness threshold — skip stocks updated within this window
    max_age_days = int(os.environ.get('FUNDAMENTALS_MAX_AGE_DAYS', '7'))
    now = datetime.now()

    success = 0
    skipped = 0
    errors = 0
    pipeline_start = time.time()

    for i, symbol in enumerate(all_symbols):
        # Timeout safety — save what we have and exit cleanly
        elapsed = time.time() - pipeline_start
        if elapsed > MAX_RUNTIME_SECONDS:
            print(f"\n⚠ Runtime limit reached ({elapsed/3600:.1f}h). Processed {success}, skipped {skipped}. Saving and exiting.")
            break

        # Skip fresh files — if JSON exists and is recent, don't re-fetch
        output_path = f"fundamentals/{symbol}.json"
        if os.path.exists(output_path) and max_age_days > 0:
            try:
                with open(output_path, 'r') as f:
                    existing = json.load(f)
                last_updated = existing.get('last_updated', '')
                if last_updated:
                    age = (now - datetime.fromisoformat(last_updated)).total_seconds() / 86400
                    if age < max_age_days:
                        skipped += 1
                        if skipped <= 5 or skipped % 100 == 0:
                            print(f"  [{i+1}/{len(all_symbols)}] {symbol} — fresh ({age:.1f}d old), skipping")
                        continue
            except Exception:
                pass  # If we can't read it, re-process

        print(f"\n[{i+1}/{len(all_symbols)}] {symbol}")

        try:
            fund_data = fetch_fundamentals(symbol)

            if not fund_data.get('income_statement'):
                print(f"  Skipping {symbol} — no income statement data")
                errors += 1
                continue

            # Get ranking data for cross-reference
            ranking = rankings_map.get(symbol)

            # Compute CAN SLIM + SEPA analysis
            fund_data['analysis'] = compute_canslim_sepa(fund_data, ranking)
            fund_data['last_updated'] = datetime.now().isoformat()

            # Save
            output_path = f"fundamentals/{symbol}.json"
            with open(output_path, 'w') as f:
                json.dump(fund_data, f, separators=(',', ':'))

            score = fund_data['analysis']['overall_score']
            rating = fund_data['analysis']['overall_rating']
            tt_pass = fund_data['analysis']['sepa']['trend_template']['passing']
            code33 = fund_data['analysis']['sepa']['code_33']['detected']
            print(f"  Score: {score}/100 ({rating}) | TT: {tt_pass}/8 | Code33: {'YES' if code33 else 'no'}")
            success += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

    # Build screener index
    print("\nBuilding fundamentals/index.json...")
    index_stocks = []
    for symbol_file in sorted(os.listdir('fundamentals')):
        if not symbol_file.endswith('.json') or symbol_file == 'index.json':
            continue
        try:
            with open(f'fundamentals/{symbol_file}') as f:
                d = json.load(f)
            a = d.get('analysis', {})
            cs = a.get('canslim', {})
            sepa = a.get('sepa', {})
            tt = sepa.get('trend_template', {})
            fl = a.get('flags', [])
            index_stocks.append({
                'symbol': d.get('symbol', symbol_file.replace('.json', '')),
                'score': a.get('overall_score', 0),
                'rating': a.get('overall_rating', 'weak'),
                'eps_rating': a.get('eps_rating'),
                'c': cs.get('c_score', {}).get('score', 0),
                'a': cs.get('a_score', {}).get('score', 0),
                'n': cs.get('n_score', {}).get('score', 0),
                's': cs.get('s_score', {}).get('score', 0),
                'i': cs.get('i_score', {}).get('score', 0),
                'sepa': sepa.get('earnings_quality', {}).get('score', 0),
                'tt': tt.get('passing', 0),
                'code33': sepa.get('code_33', {}).get('detected', False),
                'sells': any(f['type'] == 'red' and 'SELL' in f.get('message', '') for f in fl),
                'decel': any(f.get('category') == 'c_decel_sell' for f in fl if f['type'] == 'red'),
                'eps_accel': any(c.get('id') == 'c_eps_accel' and c.get('status') == 'pass' for c in cs.get('c_score', {}).get('checks', [])),
            })
        except Exception as e:
            print(f"  Warning: Could not read {symbol_file}: {e}")

    index_stocks.sort(key=lambda x: x['score'], reverse=True)

    with open('fundamentals/index.json', 'w') as f:
        json.dump({
            'last_updated': datetime.now().isoformat(),
            'count': len(index_stocks),
            'stocks': index_stocks,
        }, f, separators=(',', ':'))

    print(f"Index: {len(index_stocks)} stocks written to fundamentals/index.json")
    if index_stocks:
        top5 = ', '.join(s['symbol'] + '(' + str(s['score']) + ')' for s in index_stocks[:5])
        print(f"Top 5: {top5}")

    print()
    print("=" * 80)
    print(f"COMPLETE: {success} processed, {skipped} skipped (fresh), {errors} failed")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
