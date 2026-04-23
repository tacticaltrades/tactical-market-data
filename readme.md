# tactical-market-data

Automated stock data pipeline powering the tactical-trades web app. Pulls prices, fundamentals, and IPO data from [Financial Modeling Prep](https://financialmodelingprep.com/) and commits the generated JSON files back to this repo, which the web app consumes as a static data source.

## Pipelines

| Workflow                 | Schedule                                 | Purpose |
|--------------------------|------------------------------------------|---------|
| `main_phantom.yml`       | Mon–Thu 4:20 PM ET (21:20 UTC)           | Daily incremental: refresh prices, RS scores, moving averages, ADR/ATR. Reuses existing profiles + earnings. ~15 min. |
|                          | Fri 4:20 PM ET (21:20 UTC)               | Weekly full rebuild: fresh profiles, earnings, market cap, full 5-year price history. ~2 hours. |
| `ipo.yml`                | Fri 4:00 PM ET (21:00 UTC)               | Refresh IPO calendar (`ipo_dates.json`) 20 min before the Friday full rebuild reads it. |
| `fundamentals.yml`       | Fri 10:00 PM ET (Sat 02:00 UTC)          | Per-stock CAN SLIM / SEPA scoring. Smart-skip: only re-scores stocks with data older than 7 days. |
| `backfill_history.yml`   | Manual only                              | Per-symbol 15-year OHLCV archive to `history/{SYMBOL}.json`, served by the `fmp-history` edge function. |

All workflows also accept `workflow_dispatch` for manual runs from the Actions tab.

## Scripts

- **`process_stocks.py`** — main pipeline. `--mode full` for a complete rebuild, `--mode daily` for incremental price/RS refresh.
- **`process_ipo.py`** — pulls IPO calendar + prospectus data from FMP for the last 3 years.
- **`process_fundamentals.py`** — quarterly/annual financial statements, ratios, and scoring (C / A / N / S / SEPA + Minervini trend template). Writes one file per stock to `fundamentals/`.
- **`process_backfill.py`** — deep OHLCV backfill for chart history. Run manually.
- **`adjust_phantom.py`** — pads the RS ranking denominator with ~2,800 fake low-RS stocks when the FMP universe is below 7,000, so percentile ranks line up with IBD's ~8,000-stock universe. Triggered inline by `main_phantom.yml` when needed.

## Outputs

- `rankings.json` — primary leaderboard consumed by the web app.
- `historical_data.json` — 5-year compressed price sample. Rewritten only on Friday full rebuilds.
- `recent_ipos.json` — IPOs from the last 2 years with full stock data.
- `ipo_dates.json` — `symbol → ipo_date` lookup.
- `fundamentals/{SYMBOL}.json` — per-stock fundamentals + scores.
- `history/{SYMBOL}.json` — deep per-stock OHLCV archive (backfill only).

## RS score formula

IBD-style weighted average of trailing returns, weighted toward the recent quarter:

```
RS = 0.4 × 3m_return + 0.2 × 6m_return + 0.2 × 9m_return + 0.2 × 12m_return
```

For stocks with fewer than 252 trading days of history, the formula reweights to use whatever windows are available (see `calculate_ibd_rs_score_flexible` in `process_stocks.py`). Each stock is then assigned a 1–99 percentile rank across the full universe (including phantoms when enabled).

## Setup

1. Add `FMP_API_KEY` under **Settings → Secrets and variables → Actions** (FMP Premium plan required — 300 req/min).
2. Under **Settings → Actions → General**, enable **Read and write permissions** for workflows.
3. Manually run `main_phantom.yml` with `mode=full` once to seed `rankings.json` and `historical_data.json`.

## Rate limiting

FMP Premium allows 300 req/min. All scripts sleep 0.15s between calls (~400 req/min theoretical, well under the cap in practice). If you hit limits, raise `RATE_DELAY` in the affected script.
