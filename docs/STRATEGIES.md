# Strategy Backlog

Tracks potential strategies and improvements to research and implement.

---

## Infrastructure Improvements (work on these first)

### 1. Signal State Tracking ✅ Implemented (BaseMLBStrategy)
Replaced time-based cooldown. `_active_signal` tracks current direction; orders only fire on `None → 'long'/'short'` transitions. Resets on early exit or resolution.

### 2. Bet Sizing (Kelly Criterion) ✅ Implemented (BaseMLBStrategy)
Fractional Kelly (0.25x). Buy: `f = (model - ask) / (100 - ask)`. Short: `f = (bid - model) / bid`. Scales contracts by Kelly fraction × max position size, capped by available cash.

### 3. Position Management (early exit) ✅ Implemented (BaseMLBStrategy)
Three exit conditions: (1) profit target: position up 35+ points, (2) stop loss: position down 25+ points, (3) model reversal: model crosses 50% against position direction.

### 4. Win Probability Model Improvements
**Problem:** Current model uses generic league-average situational tables with no pitcher/batter identity.
**Key gaps:**
- No pitcher quality (ERA, WHIP, FIP)
- No batter quality vs. pitcher matchup
- No team offensive/defensive ratings (wRC+, bullpen ERA)
- Alpha decay parameters not empirically calibrated
- No extra-innings handling
**Solution:** Incorporate pitcher ERA/FIP as a multiplier on situational win probability. Calibrate alpha decay against historical outcomes in the backtest DB.
**Priority:** High — improves signal quality for all model-based strategies.

### 5. Backtest Visualization Dashboard
**Problem:** Results are text-only summaries. Hard to spot patterns, outliers, or regime shifts.
**Solution:** Build an interactive dashboard showing: P&L curve per strategy, trade scatter (entry price vs model prob), win rate by inning/score differential, signal frequency heatmap.
**Priority:** Medium — useful for diagnosing model and strategy quality.

### 4. Win Probability Model Improvements
**Problem:** Current model uses generic league-average situational tables with no pitcher/batter identity.
**Key gaps:**
- No pitcher quality (ERA, WHIP, FIP)
- No batter quality vs. pitcher matchup
- No team offensive/defensive ratings (wRC+, bullpen ERA)
- Alpha decay parameters not empirically calibrated
- No extra-innings handling
**Solution:** Incorporate pitcher ERA/FIP as a multiplier on situational win probability. Calibrate alpha decay against historical outcomes in the backtest DB.
**Priority:** High — improves signal quality for all model-based strategies.

---

## Strategies To Implement

### Strategy 1: Favorite-Longshot Bias ✅ Implemented (v1.0.0)
Exploits systematic overpricing of underdogs. Trades when model has strong conviction (>60%) and market price hasn't caught up.

### Strategy 2: Mean Reversion After Overreaction ✅ Implemented (v2.0.0)
Fades market overreactions. Trades when price moves significantly more than model suggests over a rolling window.

### Strategy 3: Pre-Game Pitcher Momentum
**Thesis:** Starting pitcher quality is the single biggest predictor of game outcome. Markets often misprice games when a high-ERA pitcher is starting vs. an ace.
**Data needed:**
- Starting pitcher for each game (from MLB Stats API `game` endpoint — already cached)
- Pitcher season stats: ERA, WHIP, FIP, recent form (last 3 starts)
- Source: `statsapi.get('game', ...)` → `gameData.probablePitchers` (in cached game files)
**Signal:** Adjust model win probability by pitcher quality differential. If model + pitcher adjustment diverges significantly from market price, trade before first pitch and hold into early innings.
**Notes:** Can leverage existing game data cache — pitcher info is already in `{game_id}.json.gz`.
**Priority:** Next to implement after infrastructure improvements.

### Strategy 4: In-Play Market Lag
**Thesis:** Market prices lag in-game events. After a scoring play, the market is slow to reprice.
**Data needed:** Play-by-play event type from `allPlays` (already in cache). Detect scoring plays, big momentum swings.
**Signal:** After a scoring play or high-captivating-index event, check if market price has moved less than model's updated probability. Trade the gap.
**Notes:** `captivatingIndex` and `isScoringPlay` are already available in cached play data.

### Strategy 5: Spread Capture / Market Making
**Thesis:** Consistently being on the right side of the bid-ask spread is profitable independent of directional bets.
**Data needed:** Order book depth (requires Kalshi API access beyond candlesticks).
**Notes:** May require live trading infrastructure rather than backtesting. Lower priority until live system is ready.
