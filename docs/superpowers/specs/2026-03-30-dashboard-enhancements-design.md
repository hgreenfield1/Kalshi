# Dashboard Enhancements Design

**Date:** 2026-03-30
**Scope:** Trade markers on game charts; filterable flat results page; API improvements

---

## Overview

Two features and one API fix:

1. **Trade markers** — up/down arrows on the price chart in `GameDetailPage` (live) and the backtest game detail view, placed at the exact timestamp each trade was executed.
2. **Filterable results page** — replace the session-grouped `ResultsPage` with a flat list of all historical live games, filterable by date range, team, P&L range, trade count range, and win/loss outcome.
3. **Trade timestamps** — add `ts` to each trade entry in `portfolio.trade_history` so live chart markers have accurate x-axis placement.

---

## 1. Trade Timestamps (Backend Fix)

### Problem
`portfolio.trade_history` entries have no `ts` field, so arrows can't be placed at the correct x-position on the time-series chart.

### Fix
In `Core/live_engine.py`, immediately after each `executor.execute(order, ...)` call, stamp the last trade entry:

```python
self.executor.execute(order, self.market.ticker, self.portfolio, bid, ask)
self.portfolio.trade_history[-1]['ts'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
```

- No changes to `portfolio.py` (shared with backtest) or `executor.py`.
- Existing JSON files without `ts` degrade gracefully — trades without a timestamp simply render no arrow.
- Backtest: no change needed. `signal != 0` rows in the `predictions` table already carry a `timestamp`.

---

## 2. Trade Markers on Game Charts

### Live — `GameDetailPage`

**Data source:** `tick_history` (has `ts`, `bid`, `ask`, `model_prob`) and `portfolio.trade_history` (has `action`, `price`, `ts` after the fix above).

**Rendering:** A custom SVG overlay layer on top of the existing Recharts chart in `dashboard/src/charts/PriceChart.tsx`.

- For each trade with a `ts`, find the nearest tick by timestamp to get the x-pixel position.
- Render an upward green triangle for `buy` at the ask price (`trade.price`), downward red triangle for `sell` at the bid price (`trade.price`). `portfolio.execute_buy` stores `ask_price` as `price` and `execute_sell` stores `bid_price` as `price`, so `trade.price` is correct for both.
- Trades without `ts` (historical files before the fix) are silently skipped.
- Add buy/sell arrow entries to the chart legend.

**Collapsible trade table:** Below the chart, a collapsible section titled "Trade History (N trades)" showing: Time, Action (colored pill), Price, Qty, Position. Defaults to expanded; collapses on header click.

### Backtest — game detail via `/api/backtest/game/{game_id}`

**Data source:** Rows from the `predictions` table for the given game. `signal != 0` rows are trades; `timestamp` gives placement; `bid_price`/`ask_price` give price context.

- `signal > 0` → buy arrow; `signal < 0` → sell arrow.
- Same SVG overlay approach as live chart.
- Same collapsible trade table below.

---

## 3. Filterable Results Page

### New API Endpoint

`GET /api/live/results?from=YYYY-MM-DD&to=YYYY-MM-DD&team=XXX&pnl_min=N&pnl_max=N&trades_min=N&trades_max=N&outcome=win|loss|all`

All parameters are optional. The API scans only `scheduler_*.json` files within the requested date range, applies filters server-side, and loads `game_TICKER.json` only for matching entries. Returns a flat JSON array:

```json
[
  {
    "date": "2026-03-27",
    "ticker": "KXMLBGAME-26MAR272015LAAHOU-HOU",
    "home_team": "HOU",
    "away_team": "LAA",
    "status": "done",
    "pregame_win_probability": 61.0,
    "pnl": -0.71,
    "trade_count": 10
  },
  ...
]
```

Games with status `no_market` or `skipped` are included unless filtered out by outcome or trade count. Team filter matches case-insensitively against `home_team` or `away_team`. The frontend does no additional filtering — results are exactly what the API returns.

### ResultsPage Redesign (`dashboard/src/pages/ResultsPage.tsx`)

**Layout:** Full-page replacement of the session-grouped view.

**Summary stat bar** (top): Total P&L, Games count, Win Rate, Avg P&L — computed from the filtered result set, updating live as filters change. Win Rate and Avg P&L exclude `no_market` and `skipped` games (status must be `done` to count).

**Single-row filter bar:**

| Control | Type | Behavior |
|---------|------|----------|
| From / To | Date inputs | Filter by game date |
| Team | Text input | Case-insensitive match against home_team or away_team |
| P&L min → max | Number inputs | Filter by pnl range (inclusive) |
| Trades min → max | Number inputs | Filter by trade_count range (inclusive) |
| Win / Loss / All | Toggle pills | Win = pnl > 0; Loss = pnl ≤ 0; All = no filter |
| Apply | Button | Sends current filter values to API and fetches results |
| Reset | Button | Clears all filters and re-fetches with no filters |

Filtering is server-side. Results are only fetched when the user clicks **Apply** (or **Reset**). Summary stats update to reflect the returned result set.

**Game table** (below filter bar): Sortable columns — Date, Matchup (Away @ Home), Status pill, Pregame %, Trades, P&L. Default sort: Date descending. Clicking a row navigates to `GameDetailPage` for that ticker.

---

## 4. Files Changed

| File | Change |
|------|--------|
| `Core/live_engine.py` | Stamp `ts` on trade entries after execution |
| `Scripts/dashboard_api.py` | Add `GET /api/live/results` endpoint |
| `dashboard/src/api/live.ts` | Add `useResults()` hook |
| `dashboard/src/charts/PriceChart.tsx` | Add trade arrow SVG overlay + legend entries |
| `dashboard/src/pages/GameDetailPage.tsx` | Add collapsible trade table below chart |
| `dashboard/src/pages/BacktestPage.tsx` | Add trade arrows + collapsible table to game detail |
| `dashboard/src/pages/ResultsPage.tsx` | Full replacement with flat filterable table |

---

## 5. Out of Scope

- No changes to the backtest filter page (strategy/model filters stay as-is).
- No changes to live game grid (`LiveGamesPage`).
- No pagination on results table (scroll through filtered results).
- No real-time auto-refresh of results page (fetch on Apply only).
