---
name: debug-live
description: Debug and inspect the live trading system. Use when the user reports a problem with live trading, a game not being discovered, a position stuck, an unexpected loss, or when they want to inspect current live state.
version: 1.0.0
---

# Debug Live Trading

Diagnose issues with the live trading runner.

## Step 1 — Check if the runner is alive

```bash
tail -20 C:/Users/henry/Kalshi/live_trading.log
```

Look for:
- `[SCHEDULER]` lines — scheduler heartbeat (should appear every 30s)
- `ERROR` or `EXCEPTION` — crash or unhandled error
- Last timestamp — if > 2 min ago, the process may have died

## Step 2 — Check the scheduler state file

```bash
cat C:/Users/henry/Kalshi/live_state/scheduler_$(date +%Y-%m-%d).json
```

This shows all games the scheduler knows about today: ticker, status (armed/running/finished), engine state.

If a game is missing here, it was never discovered — see "Game not discovered" below.

## Step 3 — Check individual game state

```bash
cat C:/Users/henry/Kalshi/live_state/game_{TICKER}.json
```

Replace `{TICKER}` with the market ticker (e.g. `KXMLBGAME-31MAR26NYYNYY-NYY`). Shows:
- Current position (YES/NO shares, avg cost)
- Last signal fired
- Model win probability at last tick
- Kalshi bid/ask at last tick
- P&L

## Step 4 — Check the dashboard API (if dashboard is running)

```bash
curl -s http://localhost:8080/api/live/summary
curl -s http://localhost:8080/api/live/games
```

`/api/live/games` lists all active engines with position and P&L.

## Common failure modes

### Game not discovered
The scheduler uses a 3-tier ticker lookup. If all 3 fail, the game is silently skipped.

**Fix:** Check `live_trading.log` for `[DISCOVERY]` lines around first-pitch time (5 min before). Look for `No market found for {game}`. Usually means the Kalshi ticker format differed from expected — may need to add a ticker alias or handle a doubleheader suffix (`G1`/`G2`).

### `pregame_winProbability == -1`
Expected for pre-2025 seasons in backtesting. In live trading (2025+), this means the pre-game Kalshi price was not fetched in the first 10 minutes of the game.

**Fix:** Check if the engine armed late. Scheduler arms engines 5 min before first pitch — if the machine was asleep or the process started late, the pre-game window is missed. The `AlphaDecayPredictionModel` will fall back to ML-only (no blending), which is still valid.

### Position stuck / not closing
Positions close at game resolution or when the early-exit conditions fire (profit target +35¢, stop loss −25¢, model reversal). If a position is open after the game ended:

1. Check `AUTO_EXECUTE` — if `false` (paper mode), no real orders were sent.
2. Check `live_trading.log` for `[RESOLUTION]` — did the resolution handler fire?
3. Check Kalshi API directly for actual position.

### Daily loss limit hit
The scheduler enforces a daily loss limit across all games. Once hit, no new positions are opened for the rest of the day.

**Check:** `live_state/scheduler_{date}.json` → `daily_pnl` field. If it exceeds the limit, the `halt` flag will be `true`.

### Auth errors on startup
```
401 Unauthorized
```
Key ID or PEM file mismatch. Verify `PROD_KEYID` in `.env` matches the key shown in Kalshi API dashboard settings.

## Restarting safely

Before restarting, check if any positions are open:
```bash
grep "POSITION" C:/Users/henry/Kalshi/live_trading.log | tail -20
```

If positions are open in live mode, closing them manually on Kalshi before restarting is safer than letting the new process reconcile — reconciliation reads the state file, which may be stale.

```bash
# Kill existing process
pkill -f run_live.py

# Restart in paper mode first to verify state loads correctly
cd C:/Users/henry/Kalshi && nohup python Scripts/run_live.py > live_trading.log 2>&1 &
tail -f live_trading.log
```
