# Live Trading Implementation Plan

**Target date: 2026-04-01** (1 week from 2026-03-25)

## Background

Backtesting the MeanReversionStrategy (v2.1.0) across the full 2025 MLB season (1,930 markets) shows:
- **ROI: +5.83%** per game
- **Win rate: 86.7%** (1,673 wins / 251 losses / 6 no-trade)
- Median ROI per game: +7.16%, std dev: $4.06

Strategy fades market overreactions: when the Kalshi price moves >5 pts more than the model
over a 10-minute rolling window, trade against the direction of the move.

---

## Milestone Schedule

| Day | Milestone | Status |
|-----|-----------|--------|
| Wed Mar 25 | Plan finalized, repo surveyed | ✅ Done |
| Thu Mar 26 | Live data infrastructure working (game poller + Kalshi price feed) | ✅ Done |
| Fri Mar 27 | LiveTradingEngine running in paper mode, multi-game support | ✅ Done |
| Sat Mar 28 | Dashboard v1 live (game state + model vs market chart) | ⬜ Pending |
| Sun Mar 29 | Paper trading validation day 1 | ⬜ Pending |
| Mon Mar 30 | Paper trading validation day 2 + risk management wired in | ⬜ Pending |
| Tue Mar 31 | Auto-execution enabled, final pre-flight checks | ⬜ Pending |
| Wed Apr 1  | **Go live with real money** | ⬜ Pending |

---

## Todo List

### 1. Live Data Infrastructure
- [x] **Live game poller** — statsapi polled every 30s per game with 30s timeout (ThreadPoolExecutor) to guard against hanging game IDs
- [x] **Live Kalshi price feed** — WebSocket `orderbook_delta` subscription + REST refresh every tick (REST is authoritative; WebSocket provides real-time supplementary data)
- [x] **Market discovery** — 3-tier fallback: direct ticker lookup → series search (handles `{YYMMMDD}{HHMM}` time component in 2026 tickers) → date-agnostic team search with closest-date tie-breaking
- [x] **Pregame win probability** — confirmed working: fetches first-10-min Kalshi candlestick at game start (e.g. 46.5% for NYY@SF on Mar 25)

### 2. Live Trading Engine
- [x] **LiveTradingEngine** — `Core/live_engine.py`; real-clock 30s poll loop identical in shape to BacktestEngine
- [x] **Order placement** — `Infrastructure/order_executor.py`; paper mode logs `[PAPER]` + updates portfolio; live mode POSTs to `/trade-api/v2/portfolio/orders`, retries once on transient failure, logs slippage
- [ ] **Position reconciliation** — on startup, fetch live Kalshi portfolio and sync positions (currently restores from local state file only; doesn't cross-check against actual Kalshi account)
- [x] **Multi-game handling** — Scheduler arms a separate LiveGameEngine thread per game; all share one WebSocket connection

### 3. Risk Management
- [x] **Per-game position limits** — ±10 contracts enforced in `BaseMLBStrategy._kelly_contracts()`
- [x] **Daily loss limit** — `Scheduler._check_daily_loss_limit()` halts all engines if daily P&L < −$50
- [ ] **Max concurrent games** — no explicit cap yet (11 games ran in parallel on Mar 26 without issue)
- [ ] **Pre-game checklist** — market existence confirmed at arm time; spread check not yet enforced (strategy degrades if spread > 10¢)

### 4. Dashboard
- [ ] **Game state panel** — live scoreboard: inning, outs, runners, score, current pitcher
- [ ] **Model vs market chart** — real-time plot of `model_prob` vs Kalshi mid-price per active game
- [ ] **Signal history** — when signals fired, entry/exit prices, current P&L per game
- [ ] **Portfolio summary** — total cash, open positions, today's realized P&L
- [ ] **Tech:** Streamlit (fastest to build, good for solo use)

### 5. Automatic Execution
- [x] **Paper trading mode** — default (`AUTO_EXECUTE=false`); logs signals + hypothetical fills without submitting
- [x] **Auto-execute toggle** — `AUTO_EXECUTE=true` env var switches to live order submission
- [x] **Order logging** — every order attempt logged with side/qty/price; API response parsed for fill price
- [x] **Slippage tracking** — `LiveOrderExecutor` compares intended limit price vs API fill price, warns if > 0.5¢

### 6. Scheduler / Orchestration
- [x] **Daily game schedule loader** — `Scheduler._load_todays_schedule()` pulls MLB schedule via statsapi, discovers Kalshi tickers for each game
- [x] **Start/stop windows** — engines armed 5 min before first pitch; finalized after game resolves
- [x] **Crash recovery** — `Scheduler` reloads `live_state/scheduler_{date}.json` on restart; `LiveGameEngine` reloads `live_state/game_{ticker}.json`; running games are re-armed immediately

### 7. Validation Before Going Live
- [ ] **Paper trade 2+ days** — 1 game validated end-to-end (NYY@SF Mar 25); full 11-game day starting Mar 26
- [x] **Verify pregame prob** — confirmed: `pregame_winProbability=46.5%` fetched correctly in real-time
- [ ] **Spread sanity check** — live spreads seen: 1¢ in a blowout (0-7 in 8th); need to observe normal-game spreads
- [ ] **Account funding** — decide starting bankroll per game (Kelly sizing assumes $100/game starting cash)

---

## Key Implementation Notes

### File locations for new code
```
Core/
  live_engine.py        # LiveGameEngine (mirrors engine.py for live clock)
  scheduler.py          # Scheduler: daily orchestrator, WebSocket setup, crash recovery
Infrastructure/
  order_executor.py     # LiveOrderExecutor: paper + live order routing
  state.py              # TradingState + Orderbook: WebSocket orderbook state
Scripts/
  run_live.py           # Entry point: scheduler runner
  run_one_game.py       # Single-game test runner (debugging / ad-hoc)
  dashboard.py          # Streamlit dashboard (not yet built)
```

### Bugs found and fixed during live testing (Mar 25–26)
- **Kalshi API v2 field names**: Market returns `yes_bid_dollars`/`yes_ask_dollars`, not `yes_bid`/`yes_ask` — fixed in `Infrastructure/market.py`
- **WebSocket snapshot format**: API sends `yes_dollars_fp`/`no_dollars_fp` with `["0.0700", "4666.00"]` string pairs, not integer-cent arrays — fixed in `Infrastructure/state.py`
- **WebSocket delta format**: API sends `{price_dollars, delta_fp, side}` flat dict, not the old `[[price, qty]]` array — fixed in `Infrastructure/state.py`
- **Stale WebSocket orderbook**: Local book can drift over a long game (partial fills leave stale qty at old price levels); fixed by refreshing Market from REST every tick in `live_engine.py`
- **`bid=0` resolution bug**: `if bid and ask:` treated 0.0¢ bid as falsy, skipping position close at game end — fixed to `if bid is not None and ask is not None:`
- **Ticker date format**: 2026 tickers use `{YY}{MMMDD}{HHMM}` (e.g. `26MAR252005`), not the old `{DDMMMYY}` format — direct lookup always fails; fallback series search handles this correctly
- **Player challenge status**: statsapi briefly returns `"Player challenge: Pitch Result"` during replay reviews — engine handles gracefully (catches exception, uses last known state)

### MeanReversionStrategy parameters (validated in backtest)
- Window: 10 minutes
- Overreaction threshold: 5 pts
- Kelly fraction: 25%
- Position limits: ±10 contracts
- Profit target: +35¢, stop loss: −25¢

### Known risks / open questions
- **Spread friction**: Backtest used mid-price for signal but traded at bid/ask. Live spreads may be wider during thin periods (confirmed: 1¢ spread in blowout game).
- **Pregame prob availability**: Only available from 2025 season onward. Strategy still functions if `pregame_winProbability == -1` (model runs without alpha-decay blending).
- **Kalshi API rate limits**: 100ms rate limit already implemented in `KalshiHttpClient`. With 15 concurrent games, polling every 30s + REST refresh per tick is well within limits.
- **Statsapi reliability**: Game 776709 (Aug 17, MIL-CIN) caused an indefinite hang in backtesting. Added 30s timeout via ThreadPoolExecutor. Also handles transient statuses like "Player challenge".
- **Position reconciliation gap**: On restart, portfolio is restored from local state file. If the process crashed mid-order, Kalshi may hold positions not reflected locally. Manual reconciliation needed before going live.

### Suggested starting bankroll
- Start with $10/game (1/10th of backtest scale) to validate live execution
- Scale up after 1-2 weeks of live validation
- At $100/game scale, expected EV ≈ $5.83/game × N_games/day
