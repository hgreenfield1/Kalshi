---
name: market-filter
description: This skill should be used when the user is fetching markets, filtering markets, setting up market filters, using SeriesMarketFilter, StatusMarketFilter, or CompositeMarketFilter, or calling http_client.get_markets in this codebase.
version: 1.0.0
---

# Market Getting & Filtering

## Status Value Sets (Important)

These are two completely separate enumerations — do not mix them up.

**API query parameter** (`status=` in `get_markets`):
- Valid values: `'open'`, `'closed'`, `'settled'`
- This is what you pass to the HTTP client to filter server-side.

**Market object `status` property** (what `StatusMarketFilter` checks):
- Valid values: `'initialized'`, `'inactive'`, `'active'`, `'closed'`, `'determined'`, `'disputed'`, `'amended'`, `'finalized'`
- A market returned by the API with query `status='settled'` will have `market.status == 'finalized'`.

So to get finalized markets:
```
http_client.get_markets(..., status='settled')   # API query param
StatusMarketFilter('finalized')                  # market object property
```

## Standard Pattern

```python
from Core.market_filter import SeriesMarketFilter, StatusMarketFilter, CompositeMarketFilter

# 1. Create filter
market_filter = CompositeMarketFilter(
    SeriesMarketFilter([SERIES_TICKER]),
    StatusMarketFilter('finalized')   # <-- 'finalized', not 'settled'
)

# 2. Fetch from API — returns dict[ticker, Market]
all_markets = http_client.get_markets([SERIES_TICKER], status='settled')  # <-- 'settled'

# 3. Apply filter — filter() expects a list
filtered_markets = market_filter.filter(list(all_markets.values()))

# 4. If you need ticker-keyed access after filtering:
# markets_by_ticker = {m.ticker: m for m in filtered_markets}
```

## Deduplication (Baseball)

Baseball markets have both home and away entries per game. To avoid running duplicate backtests, keep only home team markets:

```python
home_markets = [m for m in filtered_markets if m.ticker.split('-')[-1] in m.ticker.split('-')[1]]
```

## Filter Classes

- **`SeriesMarketFilter(series_tickers: List[str])`** — keeps markets whose `series_ticker` is in the list.
- **`StatusMarketFilter(status: str)`** — keeps markets whose `status` matches. Use `'finalized'`.
- **`CompositeMarketFilter(*filters)`** — AND-chains any number of filters. Order doesn't matter for correctness, but put cheaper filters first.

All live in `Core/market_filter.py`.
