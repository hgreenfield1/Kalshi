# Dashboard Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add buy/sell trade arrows to game price charts with collapsible trade tables, and replace the session-grouped Results page with a flat server-filtered game list.

**Architecture:** Backend: stamp `ts` on trades in `live_engine.py`, add `GET /api/live/results` with server-side filtering to `dashboard_api.py`. Frontend: replace `ReferenceLine` markers with custom `ReferenceDot` arrow shapes in `PriceChart.tsx`, add collapsible trade tables to `GameDetailPage` and `BacktestPage`, fully rewrite `ResultsPage` with filter bar and Apply button.

**Tech Stack:** Python/FastAPI, React/TypeScript, Recharts, Zustand, React Router

---

## File Map

| File | Change |
|------|--------|
| `Core/live_engine.py` | One line: stamp `ts` on each `trade_history` entry after execution |
| `Scripts/dashboard_api.py` | New `GET /api/live/results` endpoint with server-side filtering |
| `dashboard/src/api/live.ts` | Add `ts?` to trade type; add `ResultGame`, `ResultsFilter`, `fetchResults` |
| `dashboard/src/charts/PriceChart.tsx` | Replace `ReferenceLine` with `ReferenceDot` + custom `BuyArrow`/`SellArrow` shapes |
| `dashboard/src/pages/GameDetailPage.tsx` | Collapsible wrapper + Time column on trade table |
| `dashboard/src/pages/BacktestPage.tsx` | Trade arrows + collapsible table in game detail section |
| `dashboard/src/pages/ResultsPage.tsx` | Full replacement: flat table, single-row filter bar, Apply/Reset |

---

## Task 1: Stamp trade timestamps in live_engine.py

**Files:**
- Modify: `Core/live_engine.py`

- [ ] **Step 1: Add the timestamp stamp after executor.execute()**

Open `Core/live_engine.py`. Find the `for order in orders:` loop in `_poll`. It currently looks like:

```python
        for order in orders:
            self._logger.info(
                f'Signal: {order.side.value.upper()} {order.quantity}x '
                f'@ {order.limit_price:.1f}c'
            )
            self.executor.execute(order, self.market.ticker, self.portfolio, bid, ask)
```

Add one line immediately after `executor.execute(...)`:

```python
        for order in orders:
            self._logger.info(
                f'Signal: {order.side.value.upper()} {order.quantity}x '
                f'@ {order.limit_price:.1f}c'
            )
            self.executor.execute(order, self.market.ticker, self.portfolio, bid, ask)
            self.portfolio.trade_history[-1]['ts'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
```

`datetime` and `timezone` are already imported (used in `_resolve`). No new imports needed.

- [ ] **Step 2: Verify by inspection**

Read `Core/live_engine.py` lines 1–20 to confirm `from datetime import datetime, timezone` is present.

- [ ] **Step 3: Commit**

```bash
git add Core/live_engine.py
git commit -m "feat: stamp ts on trade_history entries at execution time"
```

---

## Task 2: Update TypeScript types and add fetchResults

**Files:**
- Modify: `dashboard/src/api/live.ts`

- [ ] **Step 1: Add `ts?` to the trade_history entry type**

In `live.ts`, find the `GameState` interface and update `portfolio.trade_history`:

```typescript
export interface GameState {
  ticker: string
  game_id: number
  pregame_prob_fetched: boolean
  pregame_win_probability: number
  portfolio: {
    cash: number
    positions: number
    trade_history: Array<{
      action: string
      price: number
      quantity: number
      positions: number
      cash: number
      ts?: string   // ISO timestamp — present after the live_engine fix, absent on older files
    }>
  }
  strategy_state: {
    active_signal: string | null
    entry_price: number | null
    tick_history?: Array<{
      ts: string
      bid: number
      ask: number
      model_prob: number
    }>
  }
  saved_at: string
}
```

- [ ] **Step 2: Add ResultGame, ResultsFilter, and fetchResults at the bottom of live.ts**

```typescript
export interface ResultGame {
  date: string
  ticker: string
  home_team: string
  away_team: string
  status: string
  pregame_win_probability: number | null
  pnl: number
  trade_count: number
}

export interface ResultsFilter {
  from?: string
  to?: string
  team?: string
  pnl_min?: number
  pnl_max?: number
  trades_min?: number
  trades_max?: number
  outcome?: 'win' | 'loss' | 'all'
}

export async function fetchResults(filters: ResultsFilter): Promise<ResultGame[]> {
  const params = new URLSearchParams()
  if (filters.from)              params.set('from', filters.from)
  if (filters.to)                params.set('to', filters.to)
  if (filters.team)              params.set('team', filters.team)
  if (filters.pnl_min != null)   params.set('pnl_min', String(filters.pnl_min))
  if (filters.pnl_max != null)   params.set('pnl_max', String(filters.pnl_max))
  if (filters.trades_min != null) params.set('trades_min', String(filters.trades_min))
  if (filters.trades_max != null) params.set('trades_max', String(filters.trades_max))
  if (filters.outcome && filters.outcome !== 'all') params.set('outcome', filters.outcome)
  const res = await fetch(`/api/live/results?${params}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/api/live.ts
git commit -m "feat: add ts to trade type, add ResultGame/ResultsFilter/fetchResults"
```

---

## Task 3: Add /api/live/results endpoint to dashboard_api.py

**Files:**
- Modify: `Scripts/dashboard_api.py`

- [ ] **Step 1: Add the endpoint**

Find the last live endpoint in `dashboard_api.py` (the `GET /api/live/historical/{date_str}` handler) and add the following immediately after it:

```python
@app.get("/api/live/results")
def get_live_results(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    pnl_min: Optional[float] = Query(None),
    pnl_max: Optional[float] = Query(None),
    trades_min: Optional[int] = Query(None),
    trades_max: Optional[int] = Query(None),
    outcome: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    """Flat list of all historical live games with server-side filtering."""
    results: List[Dict[str, Any]] = []

    for sched_path in sorted(LIVE_STATE_DIR.glob("scheduler_*.json")):
        date_str = sched_path.stem.replace("scheduler_", "")
        try:
            game_date = datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError:
            continue

        # Date range — skip entire file before reading entries
        if from_date:
            try:
                if game_date < datetime.strptime(from_date, "%Y-%m-%d").date():
                    continue
            except ValueError:
                pass
        if to_date:
            try:
                if game_date > datetime.strptime(to_date, "%Y-%m-%d").date():
                    continue
            except ValueError:
                pass

        sched = _read_json(sched_path)
        if not sched:
            continue

        for entry in sched.get("entries", []):
            ticker    = entry.get("market_ticker", "")
            status    = entry.get("status", "")
            home_team = entry.get("home_team", "")
            away_team = entry.get("away_team", "")

            # Team filter before loading game file
            if team and team.upper() not in (home_team.upper(), away_team.upper()):
                continue

            game_data = _read_json(_game_path(ticker)) if ticker else None
            pnl: float = 0.0
            trade_count: int = 0
            pregame_win_probability: Optional[float] = None

            if game_data:
                portfolio = game_data.get("portfolio", {})
                pnl = _calc_pnl(portfolio)
                trade_count = len(portfolio.get("trade_history", []))
                pregame_win_probability = game_data.get("pregame_win_probability")

            # P&L filters
            if pnl_min is not None and pnl < pnl_min:
                continue
            if pnl_max is not None and pnl > pnl_max:
                continue

            # Trade count filters
            if trades_min is not None and trade_count < trades_min:
                continue
            if trades_max is not None and trade_count > trades_max:
                continue

            # Outcome filter — only applies to done games
            if outcome == "win" and not (status == "done" and pnl > 0):
                continue
            if outcome == "loss" and not (status == "done" and pnl <= 0):
                continue

            results.append({
                "date": game_date.isoformat(),
                "ticker": ticker,
                "home_team": home_team,
                "away_team": away_team,
                "status": status,
                "pregame_win_probability": pregame_win_probability,
                "pnl": round(pnl, 2),
                "trade_count": trade_count,
            })

    results.sort(key=lambda x: x["date"], reverse=True)
    return results
```

- [ ] **Step 2: Test the endpoint**

With the dashboard server running (`uvicorn dashboard_api:app --host 0.0.0.0 --port 8080` from `Scripts/`):

```bash
# All games — should return a JSON array sorted by date desc
curl "http://localhost:8080/api/live/results" | python -m json.tool | head -30

# Team filter
curl "http://localhost:8080/api/live/results?team=HOU" | python -m json.tool

# Win filter — should only return done games with pnl > 0
curl "http://localhost:8080/api/live/results?outcome=win" | python -m json.tool

# Date range
curl "http://localhost:8080/api/live/results?from=2026-03-26&to=2026-03-27" | python -m json.tool
```

Expected for each: valid JSON array, results match the filter criteria.

- [ ] **Step 3: Commit**

```bash
git add Scripts/dashboard_api.py
git commit -m "feat: add /api/live/results endpoint with server-side filtering"
```

---

## Task 4: PriceChart — ReferenceDot trade arrows

**Files:**
- Modify: `dashboard/src/charts/PriceChart.tsx`

The current implementation uses `ReferenceLine` (vertical dashed lines) placed at approximate timestamps. Replace with `ReferenceDot` + custom SVG arrow shapes placed at `trade.price` on the y-axis.

- [ ] **Step 1: Update the Recharts import — swap ReferenceLine for ReferenceDot**

```typescript
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot
} from 'recharts'
```

- [ ] **Step 2: Add `ts?` to the Trade interface**

```typescript
interface Trade {
  action: string
  price: number
  quantity: number
  ts?: string
}
```

- [ ] **Step 3: Add helper and arrow shape components before CustomTooltip**

```typescript
function findNearestLabel(ts: string, ticks: Tick[]): string | null {
  if (!ticks.length) return null
  const t = new Date(ts).getTime()
  let nearest = ticks[0]
  let minDiff = Math.abs(new Date(ticks[0].ts).getTime() - t)
  for (const tick of ticks.slice(1)) {
    const diff = Math.abs(new Date(tick.ts).getTime() - t)
    if (diff < minDiff) { minDiff = diff; nearest = tick }
  }
  return new Date(nearest.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function BuyArrow({ cx, cy }: { cx?: number; cy?: number }) {
  if (cx == null || cy == null) return null
  return (
    <g>
      <polygon points={`${cx},${cy - 10} ${cx - 6},${cy} ${cx + 6},${cy}`} fill="#22c55e" />
      <line x1={cx} y1={cy} x2={cx} y2={cy + 8} stroke="#22c55e" strokeWidth={1.5} />
    </g>
  )
}

function SellArrow({ cx, cy }: { cx?: number; cy?: number }) {
  if (cx == null || cy == null) return null
  return (
    <g>
      <polygon points={`${cx},${cy + 10} ${cx - 6},${cy} ${cx + 6},${cy}`} fill="#ef4444" />
      <line x1={cx} y1={cy - 8} x2={cx} y2={cy} stroke="#ef4444" strokeWidth={1.5} />
    </g>
  )
}
```

- [ ] **Step 4: Replace tradeTs computation inside PriceChart**

Remove this block:

```typescript
  // Find timestamps of trades to draw reference lines
  const tradeTs = trades.map((tr, i) => ({
    ts: ticks[Math.max(0, ticks.length - 1 - i)]?.ts,
    action: tr.action,
  })).filter(t => t.ts)
```

Replace with:

```typescript
  // Map each timestamped trade to its nearest tick's x-axis label and the trade price
  const tradeMarkers = trades
    .filter(tr => tr.ts)
    .map(tr => ({
      label: findNearestLabel(tr.ts!, ticks),
      price: tr.price,
      action: tr.action,
    }))
    .filter(m => m.label !== null)
```

- [ ] **Step 5: Replace ReferenceLine JSX with ReferenceDot JSX inside ComposedChart**

Remove:

```typescript
        {/* Trade markers */}
        {tradeTs.map((t, i) => (
          <ReferenceLine
            key={i}
            x={t.ts ? new Date(t.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
            stroke="var(--yellow)"
            strokeDasharray="4 4"
            strokeWidth={1}
          />
        ))}
```

Replace with:

```typescript
        {/* Trade arrows: buy = green up, sell = red down, placed at trade price */}
        {tradeMarkers.map((m, i) => (
          <ReferenceDot
            key={i}
            x={m.label!}
            y={m.price}
            r={0}
            shape={m.action === 'buy'
              ? (props: any) => <BuyArrow cx={props.cx} cy={props.cy} />
              : (props: any) => <SellArrow cx={props.cx} cy={props.cy} />
            }
          />
        ))}
```

- [ ] **Step 6: Build**

```bash
cd dashboard && npm run build
```

Expected: zero TypeScript errors, build succeeds.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/charts/PriceChart.tsx
git commit -m "feat: replace trade ReferenceLine with ReferenceDot up/down arrows at trade price"
```

---

## Task 5: GameDetailPage — collapsible trade table + Time column

**Files:**
- Modify: `dashboard/src/pages/GameDetailPage.tsx`

- [ ] **Step 1: Add collapsed state**

Inside `GameDetailPage`, after the existing data reads (`portfolio`, `tickHistory`, etc.), add:

```typescript
  const [tradesCollapsed, setTradesCollapsed] = useState(false)
```

`useState` is already imported.

- [ ] **Step 2: Add Time as the first column in tradeColumns**

Replace the existing `tradeColumns` definition with:

```typescript
  const tradeColumns: Column<typeof trades[0]>[] = [
    {
      key: 'ts' as any,
      label: 'Time',
      render: row => (row as any).ts
        ? new Date((row as any).ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '—',
    },
    {
      key: 'action',
      label: 'Action',
      render: row => (
        <span style={{
          fontWeight: 600,
          color: row.action === 'buy' ? 'var(--green)' : 'var(--red)',
          textTransform: 'uppercase',
          fontSize: 11,
        }}>
          {row.action}
        </span>
      ),
    },
    { key: 'price', label: 'Price', align: 'right', render: row => `${row.price}¢` },
    { key: 'quantity', label: 'Qty', align: 'right' },
    { key: 'positions', label: 'Pos', align: 'right' },
    {
      key: 'cash',
      label: 'Cash',
      align: 'right',
      render: row => {
        const delta = row.cash - 100
        return (
          <span style={{ color: delta >= 0 ? 'var(--green)' : 'var(--red)' }}>
            ${row.cash.toFixed(2)}
          </span>
        )
      },
    },
  ]
```

- [ ] **Step 3: Replace the trade table section with a collapsible version**

Find the existing trade table block at the bottom of the return:

```typescript
      {/* Trade table */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 12 }}>
          Trade History ({trades.length})
        </div>
        <DataTable
          columns={tradeColumns}
          rows={trades}
          rowKey={(_, i) => i!}
        />
      </div>
```

Replace with:

```typescript
      {/* Trade table — collapsible */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        overflow: 'hidden',
      }}>
        <div
          onClick={() => setTradesCollapsed(c => !c)}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '12px 16px',
            cursor: 'pointer',
            userSelect: 'none',
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>
            Trade History{' '}
            <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({trades.length})</span>
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {tradesCollapsed ? '▼ expand' : '▲ collapse'}
          </span>
        </div>
        {!tradesCollapsed && (
          <DataTable
            columns={tradeColumns}
            rows={trades}
            rowKey={(_, i) => i!}
          />
        )}
      </div>
```

- [ ] **Step 4: Build and verify**

```bash
cd dashboard && npm run build
```

Open `http://localhost:8080/live`, click a game with trades. Verify:
- "Trade History (N)" header with collapse arrow
- Clicking header collapses/expands the table
- Time column shows `HH:MM AM/PM` for new trades with `ts`, `—` for older trades
- Buy/sell arrows appear on the chart at correct prices

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/GameDetailPage.tsx
git commit -m "feat: collapsible trade table with Time column in GameDetailPage"
```

---

## Task 6: BacktestPage — trade arrows + collapsible table in game detail

**Files:**
- Modify: `dashboard/src/pages/BacktestPage.tsx`

- [ ] **Step 1: Read the full BacktestPage to find the game detail section**

Read `dashboard/src/pages/BacktestPage.tsx` from line 150 to end. Find where the game detail is rendered (look for `selectedGame`, `gameDetail`, or a fetch for `/api/backtest/game`).

- [ ] **Step 2: Understand the prediction row structure**

The `/api/backtest/game/{game_id}` endpoint returns rows from the `predictions` table:

```typescript
interface PredictionRow {
  id: number
  timestamp: string       // ISO — use for x-axis placement
  predicted_prob: number
  bid_price: number
  ask_price: number
  cash: number
  positions: number
  signal: number | null   // non-zero = trade; positive = buy, negative = sell
}
```

- [ ] **Step 3: Derive ticks and trade markers from prediction rows**

In the game detail section, after the prediction rows are available (call them `rows`), add:

```typescript
const ticks = (rows ?? []).filter((r: any) => r.timestamp !== 'FINAL').map((r: any) => ({
  ts: r.timestamp,
  bid: r.bid_price,
  ask: r.ask_price,
  model_prob: r.predicted_prob * 100,
}))

const backtestTrades = (rows ?? [])
  .filter((r: any) => r.timestamp !== 'FINAL' && r.signal != null && r.signal !== 0)
  .map((r: any) => ({
    action: r.signal > 0 ? 'buy' : 'sell',
    price: r.signal > 0 ? r.ask_price : r.bid_price,
    quantity: 1,
    ts: r.timestamp,
    positions: r.positions,
  }))
```

- [ ] **Step 4: Pass backtestTrades to PriceChart**

In the game detail chart render:

```typescript
<PriceChart ticks={ticks} trades={backtestTrades} />
```

- [ ] **Step 5: Add collapsed state and collapsible trade table below the chart**

Add state near the top of the component or sub-component that renders the game detail:

```typescript
const [tradesCollapsed, setTradesCollapsed] = useState(false)
```

Add this block after the PriceChart:

```typescript
<div style={{
  background: 'var(--bg-surface)',
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  overflow: 'hidden',
  marginTop: 16,
}}>
  <div
    onClick={() => setTradesCollapsed(c => !c)}
    style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '12px 16px',
      cursor: 'pointer',
      userSelect: 'none',
    }}
  >
    <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>
      Trade History{' '}
      <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({backtestTrades.length})</span>
    </span>
    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
      {tradesCollapsed ? '▼ expand' : '▲ collapse'}
    </span>
  </div>
  {!tradesCollapsed && (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
      <thead>
        <tr style={{ background: 'var(--bg-elevated)' }}>
          <th style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--text-muted)', fontWeight: 500 }}>Time</th>
          <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-muted)', fontWeight: 500 }}>Action</th>
          <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text-muted)', fontWeight: 500 }}>Price</th>
          <th style={{ textAlign: 'right', padding: '6px 12px', color: 'var(--text-muted)', fontWeight: 500 }}>Position</th>
        </tr>
      </thead>
      <tbody>
        {backtestTrades.map((t: any, i: number) => (
          <tr key={i} style={{ borderTop: '1px solid var(--border-subtle)' }}>
            <td style={{ padding: '6px 12px', color: 'var(--text-muted)' }}>
              {new Date(t.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </td>
            <td style={{ padding: '6px 8px' }}>
              <span style={{
                fontWeight: 600,
                color: t.action === 'buy' ? 'var(--green)' : 'var(--red)',
                textTransform: 'uppercase',
                fontSize: 11,
              }}>
                {t.action}
              </span>
            </td>
            <td style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text-primary)' }}>
              {t.price.toFixed(1)}¢
            </td>
            <td style={{ textAlign: 'right', padding: '6px 12px', color: 'var(--text-secondary)' }}>
              {t.positions}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )}
</div>
```

- [ ] **Step 6: Build and verify**

```bash
cd dashboard && npm run build
```

Open `http://localhost:8080/backtest`, click a game with trades. Verify:
- Green up arrows at buy prices, red down arrows at sell prices on chart
- Collapsible trade table appears below with Time, Action, Price, Position columns

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/pages/BacktestPage.tsx
git commit -m "feat: trade arrows and collapsible table in backtest game detail"
```

---

## Task 7: Replace ResultsPage

**Files:**
- Modify: `dashboard/src/pages/ResultsPage.tsx`

- [ ] **Step 1: Replace the full file**

Replace the entire contents of `dashboard/src/pages/ResultsPage.tsx` with:

```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchResults, type ResultGame, type ResultsFilter } from '../api/live'
import StatusPill from '../components/StatusPill'

export default function ResultsPage() {
  const navigate = useNavigate()

  // Filter inputs
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [team, setTeam] = useState('')
  const [pnlMin, setPnlMin] = useState('')
  const [pnlMax, setPnlMax] = useState('')
  const [tradesMin, setTradesMin] = useState('')
  const [tradesMax, setTradesMax] = useState('')
  const [outcome, setOutcome] = useState<'win' | 'loss' | 'all'>('all')

  // Fetch state
  const [games, setGames] = useState<ResultGame[]>([])
  const [loading, setLoading] = useState(false)
  const [fetched, setFetched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Sort state
  const [sortKey, setSortKey] = useState<keyof ResultGame>('date')
  const [sortAsc, setSortAsc] = useState(false)

  function handleSort(key: keyof ResultGame) {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  async function handleApply() {
    setLoading(true)
    setError(null)
    const filters: ResultsFilter = {}
    if (from)              filters.from = from
    if (to)                filters.to = to
    if (team)              filters.team = team
    if (pnlMin !== '')     filters.pnl_min = parseFloat(pnlMin)
    if (pnlMax !== '')     filters.pnl_max = parseFloat(pnlMax)
    if (tradesMin !== '')  filters.trades_min = parseInt(tradesMin, 10)
    if (tradesMax !== '')  filters.trades_max = parseInt(tradesMax, 10)
    if (outcome !== 'all') filters.outcome = outcome
    try {
      setGames(await fetchResults(filters))
      setFetched(true)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setFrom(''); setTo(''); setTeam('')
    setPnlMin(''); setPnlMax('')
    setTradesMin(''); setTradesMax('')
    setOutcome('all')
    setGames([])
    setFetched(false)
    setError(null)
  }

  const sorted = [...games].sort((a, b) => {
    const av = a[sortKey] ?? 0
    const bv = b[sortKey] ?? 0
    const cmp = av < bv ? -1 : av > bv ? 1 : 0
    return sortAsc ? cmp : -cmp
  })

  // Summary stats — done games only for win rate / avg P&L
  const doneGames = games.filter(g => g.status === 'done')
  const totalPnl = doneGames.reduce((s, g) => s + g.pnl, 0)
  const winRate = doneGames.length ? doneGames.filter(g => g.pnl > 0).length / doneGames.length : 0
  const avgPnl = doneGames.length ? totalPnl / doneGames.length : 0

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border-default)',
    borderRadius: 4,
    padding: '4px 7px',
    color: 'var(--text-primary)',
    fontSize: 12,
    outline: 'none',
  }

  function thStyle(key: keyof ResultGame, align: 'left' | 'right' = 'left'): React.CSSProperties {
    return {
      textAlign: align,
      padding: '8px 12px',
      color: sortKey === key ? 'var(--accent-light)' : 'var(--text-muted)',
      fontWeight: 500,
      fontSize: 11,
      cursor: 'pointer',
      userSelect: 'none',
      whiteSpace: 'nowrap',
    }
  }

  function sortIndicator(key: keyof ResultGame) {
    if (sortKey !== key) return ' ↕'
    return sortAsc ? ' ↑' : ' ↓'
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Results</h1>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Live trading history</div>
      </div>

      {/* Summary stats — shown after first fetch */}
      {fetched && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          {[
            { label: 'Games',     value: games.length },
            { label: 'Done',      value: doneGames.length },
            { label: 'Total P&L', value: `${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)}`, color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)' },
            { label: 'Win Rate',  value: `${(winRate * 100).toFixed(0)}%` },
            { label: 'Avg P&L',   value: `${avgPnl >= 0 ? '+' : ''}$${avgPnl.toFixed(2)}`, color: avgPnl >= 0 ? 'var(--green)' : 'var(--red)' },
          ].map(m => (
            <div key={m.label} style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 8,
              padding: '10px 14px',
              minWidth: 90,
            }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{m.label}</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: (m as any).color ?? 'var(--text-primary)' }}>{m.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Single-row filter bar */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        padding: '10px 14px',
        display: 'flex',
        gap: 10,
        alignItems: 'center',
        flexWrap: 'wrap',
        marginBottom: 16,
      }}>
        {/* Date range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>From</span>
          <input type="date" value={from} onChange={e => setFrom(e.target.value)} style={inputStyle} />
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>To</span>
          <input type="date" value={to} onChange={e => setTo(e.target.value)} style={inputStyle} />
        </div>

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* Team */}
        <input
          type="text"
          placeholder="Team..."
          value={team}
          onChange={e => setTeam(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleApply()}
          style={{ ...inputStyle, width: 80 }}
        />

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* P&L range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>P&amp;L</span>
          <input type="number" step="0.01" placeholder="min" value={pnlMin} onChange={e => setPnlMin(e.target.value)} style={{ ...inputStyle, width: 60 }} />
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>→</span>
          <input type="number" step="0.01" placeholder="max" value={pnlMax} onChange={e => setPnlMax(e.target.value)} style={{ ...inputStyle, width: 60 }} />
        </div>

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* Trades range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Trades</span>
          <input type="number" min="0" placeholder="min" value={tradesMin} onChange={e => setTradesMin(e.target.value)} style={{ ...inputStyle, width: 48 }} />
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>→</span>
          <input type="number" min="0" placeholder="max" value={tradesMax} onChange={e => setTradesMax(e.target.value)} style={{ ...inputStyle, width: 48 }} />
        </div>

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* Outcome toggle */}
        <div style={{ display: 'flex', gap: 4 }}>
          {(['win', 'loss', 'all'] as const).map(o => (
            <button
              key={o}
              onClick={() => setOutcome(o)}
              style={{
                padding: '4px 10px',
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 500,
                cursor: 'pointer',
                border: '1px solid',
                borderColor: outcome === o ? 'var(--accent)' : 'var(--border-default)',
                background: outcome === o ? 'rgba(124,58,237,0.15)' : 'transparent',
                color: outcome === o ? 'var(--accent-light)' : 'var(--text-muted)',
              }}
            >
              {o.charAt(0).toUpperCase() + o.slice(1)}
            </button>
          ))}
        </div>

        {/* Apply + Reset */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            onClick={handleApply}
            disabled={loading}
            style={{
              padding: '5px 14px',
              borderRadius: 4,
              fontSize: 12,
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              border: '1px solid var(--accent)',
              background: 'var(--accent)',
              color: '#fff',
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? 'Loading…' : 'Apply'}
          </button>
          <button
            onClick={handleReset}
            style={{
              padding: '5px 10px',
              borderRadius: 4,
              fontSize: 12,
              cursor: 'pointer',
              border: '1px solid var(--border-default)',
              background: 'transparent',
              color: 'var(--text-muted)',
            }}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>Error: {error}</div>
      )}

      {/* Results table */}
      {fetched && !loading && (
        sorted.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', textAlign: 'center', paddingTop: 60, fontSize: 14 }}>
            No games match the current filters
          </div>
        ) : (
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-elevated)' }}>
                  <th onClick={() => handleSort('date')} style={thStyle('date')}>
                    Date{sortIndicator('date')}
                  </th>
                  <th style={{ textAlign: 'left', padding: '8px 12px', color: 'var(--text-muted)', fontWeight: 500, fontSize: 11 }}>Matchup</th>
                  <th style={{ textAlign: 'left', padding: '8px 12px', color: 'var(--text-muted)', fontWeight: 500, fontSize: 11 }}>Status</th>
                  <th onClick={() => handleSort('pregame_win_probability')} style={thStyle('pregame_win_probability', 'right')}>
                    Pre-game{sortIndicator('pregame_win_probability')}
                  </th>
                  <th onClick={() => handleSort('trade_count')} style={thStyle('trade_count', 'right')}>
                    Trades{sortIndicator('trade_count')}
                  </th>
                  <th onClick={() => handleSort('pnl')} style={thStyle('pnl', 'right')}>
                    P&amp;L{sortIndicator('pnl')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((g, i) => (
                  <tr
                    key={i}
                    onClick={() => g.ticker && navigate(`/live/${g.ticker}`)}
                    style={{ borderTop: '1px solid var(--border-subtle)', cursor: g.ticker ? 'pointer' : 'default' }}
                    onMouseEnter={e => { if (g.ticker) (e.currentTarget as HTMLElement).style.background = 'var(--bg-elevated)' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '' }}
                  >
                    <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                      {new Date(g.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </td>
                    <td style={{ padding: '8px 12px', color: 'var(--text-primary)' }}>
                      {g.away_team} <span style={{ color: 'var(--text-muted)' }}>@</span> <strong>{g.home_team}</strong>
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <StatusPill status={g.status as any} />
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: 'var(--text-muted)' }}>
                      {g.pregame_win_probability != null ? `${g.pregame_win_probability.toFixed(1)}¢` : '—'}
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: 'var(--text-secondary)' }}>
                      {g.trade_count}
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 600 }}>
                      {g.status === 'done' ? (
                        <span style={{ color: g.pnl > 0 ? 'var(--green)' : g.pnl < 0 ? 'var(--red)' : 'var(--text-muted)' }}>
                          {g.pnl >= 0 ? '+' : ''}${g.pnl.toFixed(2)}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11, borderTop: '1px solid var(--border-subtle)' }}>
              {sorted.length} game{sorted.length !== 1 ? 's' : ''}
            </div>
          </div>
        )
      )}

      {/* First-load prompt */}
      {!fetched && !loading && (
        <div style={{ color: 'var(--text-muted)', textAlign: 'center', paddingTop: 60, fontSize: 14 }}>
          Set filters above and click Apply to load results
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Build and verify**

```bash
cd dashboard && npm run build
```

Open `http://localhost:8080/results`. Verify:
- Filter bar renders on one row
- Clicking Apply fetches and populates the table; clicking Reset clears it
- Summary stats appear after first fetch; Win Rate / Avg P&L only count `done` games
- Column headers sort the table; active sort column is highlighted in purple
- Clicking a row navigates to `/live/{ticker}`
- P&L shows `—` for non-done games (no_market, skipped)
- Enter key in Team field triggers Apply

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/ResultsPage.tsx
git commit -m "feat: replace ResultsPage with flat filterable table and Apply button"
```

---

## Task 8: Final build and end-to-end verification

- [ ] **Step 1: Full rebuild**

```bash
cd dashboard && npm run build
```

- [ ] **Step 2: Restart API server**

```bash
# From repo root
cd Scripts && uvicorn dashboard_api:app --host 0.0.0.0 --port 8080
```

- [ ] **Step 3: End-to-end checklist**

- [ ] Live game detail: green up arrows at buy price, red down arrows at sell price on chart
- [ ] Live game detail: "Trade History (N)" header collapses/expands the table
- [ ] Live game detail: Time column shows `HH:MM` for new trades, `—` for old ones
- [ ] Backtest game detail: same arrows and collapsible table
- [ ] Results: Apply with no filters returns all games sorted by date desc
- [ ] Results: Date From/To filter returns only games in range
- [ ] Results: Team filter (e.g. `HOU`) returns only HOU games
- [ ] Results: P&L min/max filter works
- [ ] Results: Trades min/max filter works
- [ ] Results: Win shows only done + pnl > 0; Loss shows only done + pnl ≤ 0
- [ ] Results: Reset clears all filters and table
- [ ] Results: Summary Total P&L, Win Rate, Avg P&L reflect only `done` games
- [ ] Results: Column sort (Date, Trades, P&L, Pre-game) works correctly
- [ ] Results: Clicking a game row navigates to its detail page
