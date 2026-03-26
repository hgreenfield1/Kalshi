# Dashboard Implementation Plan

**Target: Sat Mar 28 (v1)**

Dark, minimal, premium. Inspired by Linear.app — not a generic data dashboard.

---

## Tech Stack

**Backend:** FastAPI (`dashboard_api.py`) — reads `live_state/` JSON files + `backtest_predictions.db`
**Frontend:** React 18 + Vite + Tailwind CSS + Recharts
**Real-time:** Server-Sent Events (SSE) — no WebSocket needed, one-way stream
**Build:** `vite build` → `dashboard/dist/` → served by FastAPI `StaticFiles`

**Why not Streamlit/Dash:** Layout fights, redraws entire page on state changes, impossible to achieve premium aesthetics without constant CSS wrestling.
**Why not Next.js:** SSR/RSC adds zero value here (all data is client-fetched from localhost). Build overhead costs half a day.
**Why SSE over WebSocket:** The dashboard only receives data, never sends. SSE is a plain HTTP stream, auto-reconnects, works through any proxy.

---

## Design Tokens

```css
/* src/styles/tokens.css */
--bg-base:           #0B0D0E;   /* page background */
--bg-surface:        #111315;   /* cards */
--bg-elevated:       #1A1D1F;   /* dropdowns, tooltips */
--border-subtle:     #222527;   /* card borders */
--border-default:    #2E3235;   /* input borders */
--text-primary:      #F1F3F5;
--text-secondary:    #8A8F97;
--text-muted:        #4E5560;
--accent:            #7C3AED;   /* violet — primary interactive */
--accent-light:      #A855F7;
--green:             #22C55E;
--red:               #EF4444;
--yellow:            #EAB308;
```

Font: **Inter** (Google Fonts CDN). No other typeface.
Radius: 8px cards, 6px inputs/buttons. Subtle box-shadow on cards (no hard borders).

---

## Routes

```
/live                  Today's games — live grid
/live/:ticker          Game detail (live or historical)
/results               Aggregated live trading results
/backtest              Backtest performance
```

---

## Pages & Components

### Shared Layout
```
Layout
├── Sidebar
│   ├── Logo / wordmark
│   ├── Nav links: Live · Results · Backtest
│   └── Daily P&L badge (live total, green/red)
└── <Outlet />
```

### Live Games (`/live`)
```
LiveGamesPage
├── DailyPnLBanner      — total P&L, # active games, PAPER/LIVE mode badge
├── GameGrid (CSS grid)
│   └── GameCard × N
│       ├── Teams + score pill
│       ├── Inning / outs / runners row
│       ├── Status pill: running (green pulse) · pending · done
│       ├── Position (long/short/flat)
│       └── P&L delta
└── SSEConnection       — invisible; drives GameGrid updates via Zustand
```

### Game Detail (`/live/:ticker`)
Shared for live games and resolved historical games.
```
GameDetailPage
├── GameHeader
│   ├── Team names, current score, inning, outs, runners
│   └── Pitcher names (home/away)
├── PriceChart  (Recharts ComposedChart)
│   ├── AreaSeries     — model_prob (violet gradient fill, 20% opacity)
│   ├── LineSeries     — bid price (green)
│   ├── LineSeries     — ask price (red)
│   └── ReferenceLine  — one vertical line per trade (entry/exit marker)
├── PositionPanel      — cash · positions · realized P&L · # trades
└── TradeTable         — chronological: action · price · qty · P&L after
```

### Aggregated Results (`/results`)
```
ResultsPage
├── FilterBar           — strategy version · model version · date range
├── MetricsRow          — total P&L · win rate · # games · # trades
├── CumulativePnLChart  — AreaChart, green fill above zero / red below
└── GameTable           — sortable: date · teams · P&L · trades · strategy · model
```

### Backtest Performance (`/backtest`)
```
BacktestPage
├── FilterBar           — same component, different default values
├── MetricsRow          — adds Sharpe ratio, avg ROI, std dev
├── CumulativePnLChart  — same component, backtest data source
├── PnLDistributionChart — histogram (BarChart, bins computed client-side)
└── GameTable           — same component, backtest data source
```

### Shared Design Components (build these first)
- `StatCard` — dark elevated card, label + large number + delta badge
- `StatusPill` — colored dot + label, variants: running/pending/done/no_market/live/paper
- `DataTable` — sticky header, sortable columns, row hover highlight, virtualized if >200 rows
- `FilterBar` — horizontal pill selectors + dropdowns, violet active state
- `CumulativePnLChart` — reusable; takes `data: {date, pnl, cumulative_pnl}[]`
- `PriceChart` — reusable; takes `{ticks, trades}`, renders bid/ask/model/markers

---

## API Design

All endpoints in `dashboard_api.py` (new file, standalone FastAPI app).

### Live Data

```
GET /api/live/schedule
    → today's scheduler_{YYYYMMDD}.json entries
    → {games: [{game_id, market_ticker, home_team, away_team, scheduled_start, status}]}

GET /api/live/games/{ticker}
    → live_state/game_{safe_ticker}.json
    → {ticker, portfolio, trade_history, strategy_state, pregame_win_probability, saved_at}

GET /api/live/summary
    → aggregate all game files for today
    → {total_pnl, active_count, pending_count, done_count, total_trades, mode}

GET /api/live/stream
    → SSE endpoint; polls file mtimes every 5s
    → emits: data: {type: "game_update", ticker, portfolio, ...}\n\n

GET /api/live/historical
    → lists all scheduler_{date}.json files except today
    → [{date, games_count, total_pnl}]

GET /api/live/historical/{date}
    → same as schedule + per-game state for a past date
```

### Backtest Data

```
GET /api/backtest/filters
    → {strategies: [...], models: [...]}

GET /api/backtest/games?strategy=&model=&start=&end=
    → per-game table: [{game_id, date, home, away, pnl, trades, strategy, model, outcome}]

GET /api/backtest/cumulative_pnl?strategy=&model=&start=&end=
    → [{date, game_id, pnl, cumulative_pnl}]  ordered by game start

GET /api/backtest/metrics?strategy=&model=&start=&end=
    → {total_pnl, win_rate, avg_roi, sharpe, total_games, total_trades, std_dev}

GET /api/backtest/distribution?strategy=&model=
    → [pnl_float, ...]  flat array; frontend bins into histogram

GET /api/backtest/game/{game_id}
    → all timestep rows for one backtest game (bid, ask, model_prob, signal per tick)
```

---

## Real-Time Update Flow

```
LiveGameEngine  ──writes──▶  live_state/game_*.json  (every 30s or on trade)
                                        │
dashboard_api.py /api/live/stream  ──polls──▶  file mtime every 5s
                                        │
                              emit SSE event if changed
                                        │
Frontend EventSource  ──receives──▶  Zustand store update
                                        │
                              React re-renders affected GameCard only
```

Max latency: 30s (engine write) + 5s (SSE poll) = 35s. Acceptable given the 30s strategy cycle.

---

## Required Code Changes

Only **one existing file** needs modification:

### `Markets/Baseball/strategies.py` — extend `save_state()` in `BaseMLBStrategy`

The `price_history` and `model_history` deques exist in-memory but are not being serialized to the JSON state files (the arrays in game files are currently empty). The chart in `GameDetailPage` depends on this data.

```python
# In BaseMLBStrategy (add alongside existing fields):
def __init__(self):
    ...
    self._tick_history: list[dict] = []  # {ts, bid, ask, model_prob}

# In on_timestep(), append before returning:
    self._tick_history.append({
        'ts': context.timestamp,
        'bid': context.bid_price,
        'ask': context.ask_price,
        'model_prob': model_prob,
    })

def save_state(self) -> dict:
    return {
        **super().save_state(),
        'tick_history': self._tick_history[-200:],  # cap at 200 ticks (~100min)
    }

def restore_state(self, state: dict) -> None:
    super().restore_state(state)
    self._tick_history = state.get('tick_history', [])
```

This is the only change to existing engine code. Everything else is additive.

---

## Build Order

| Step | Task | Time |
|------|------|------|
| 0 | Design tokens CSS + Tailwind config + Inter font | 20 min |
| 1 | FastAPI backend: live endpoints + SSE + static mount | 1.5 hr |
| 2 | FastAPI backend: backtest endpoints (port from backtest_api.py) | 45 min |
| 3 | React shell: Layout + Sidebar + Router + shared components | 1 hr |
| 4 | Live Games page + GameCard + SSE hook | 1 hr |
| 5 | Game Detail page + PriceChart | 45 min |
| 6 | Extend save_state() to write tick_history | 20 min |
| 7 | Results page + CumulativePnLChart + GameTable | 45 min |
| 8 | Backtest page + MetricsRow + PnLDistributionChart | 45 min |
| 9 | `vite build`, verify static serving, add loading skeletons | 30 min |

Total: ~7.5 hours for a full v1.

---

## File Structure

```
Kalshi/
├── dashboard_api.py          # New: FastAPI app (all API routes)
├── dashboard/                # New: Vite + React project
│   ├── index.html
│   ├── vite.config.ts        # proxy /api/* → localhost:8080 in dev
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx            # Router setup
│   │   ├── styles/
│   │   │   └── tokens.css
│   │   ├── components/        # StatCard, DataTable, FilterBar, etc.
│   │   ├── charts/            # PriceChart, CumulativePnLChart, Distribution
│   │   ├── pages/
│   │   │   ├── LiveGamesPage.tsx
│   │   │   ├── GameDetailPage.tsx
│   │   │   ├── ResultsPage.tsx
│   │   │   └── BacktestPage.tsx
│   │   ├── store/             # Zustand: live game state, SSE listener
│   │   └── api/               # typed fetch wrappers for each endpoint
│   └── dist/                  # vite build output, served by FastAPI
```

---

## Notes

- **Historical game detail**: same `GameDetailPage` component, just fetches from `/api/live/historical/{date}` instead of `/api/live/games/{ticker}`. The `tick_history` from `save_state()` is preserved in the JSON file after resolution.
- **No new database**: dashboard is a pure reader of existing files.
- **Running alongside the scheduler**: `uvicorn dashboard_api:app --port 8080` is a separate process. Zero coupling to the engine.
- **Position reconciliation gap** (noted in trading plan): before enabling auto-execute, add a `/api/live/reconcile` endpoint that fetches actual Kalshi portfolio positions via REST and diffs against local state.
