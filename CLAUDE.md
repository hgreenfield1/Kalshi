# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

A Kalshi prediction market trading bot for MLB baseball. The market question is always "Will the home team win?" (YES/NO binary contract, series ticker: `KXMLBGAME`). Two modes: **backtesting** against historical data and **live trading**.

## Repository Layout

```
Markets/Baseball/        # All baseball-specific logic (active codebase)
  domain.py              # BaseballGame: game state, live API updates, pitcher stats
  data_loader.py         # BaseballDataLoader: caches MLB data, reconstructs state at any timestamp
  strategies.py          # FavoriteLongShotStrategy, MeanReversionStrategy
  prediction.py          # AlphaDecayPredictionModel: blends pre-game and live probabilities
  game_state.py          # GameState dataclass + FeatureProvider system for the ML model
  win_prob_model.py      # StatcastWinProbModel: loads .pkl, runs inference
  utils.py               # Legacy win probability lookup table (fallback only)
  config.py              # SERIES_TICKER, GAME_CACHE_DIR, position limits

Core/                    # Market-agnostic backtesting engine
  engine.py              # BacktestEngine: orchestrates the timestep loop
  strategy.py            # BaseStrategy ABC, Order, DataRequirement
  portfolio.py           # Portfolio: cash, positions, trade history
  execution.py           # SimpleExecutionModel
  context.py             # Context object passed to strategy.on_timestep()
  database.py            # BacktestDatabase: SQLite persistence

Infrastructure/
  Clients/               # HTTP client for Kalshi REST API
  market.py              # Market dataclass (parsed from Kalshi API response)

Scripts/
  run_backtest.py        # Interactive backtest CLI
  analyze.py             # Reads backtest_predictions.db, prints P&L / Brier score
  train_win_prob_model.py  # Downloads Statcast data, trains XGBoost model, saves .pkl
  calibrate_win_prob_model.py  # Evaluates model calibration against realized outcomes
  build_game_cache.py    # Pre-fetches MLB game data to disk cache

Utils/
  date_helpers.py        # Timestamp conversions (UTC, unix, MLB timecode format)

Baseball/                # OLD codebase — do not modify, kept for reference only
```

## Key Data Paths

- **Win probability model**: `Markets/Baseball/win_prob_model.pkl`
- **Statcast cache**: `D:/Data/statcast/statcast_{year}.parquet`, `pitcher_stats_{year}.parquet`
- **Game data cache**: `D:/Code/Kalshi/Baseball/` (configured in `config.py` as `GAME_CACHE_DIR`)
- **Backtest results**: `backtest_predictions.db` (SQLite, project root)

## Win Probability System

### ML Model (primary)
`StatcastWinProbModel` in `win_prob_model.py` — XGBoost classifier trained on Statcast pitch data.

- **Input**: `GameState` dataclass (pure on-field state, no market data)
- **Output**: P(home team wins) in [0, 1]
- **Features** (via `FeatureProvider` system in `game_state.py`):
  - `GameStateFeatureProvider`: inning, is_extra_innings, is_bottom, outs, on_1b/2b/3b, score_diff, balls, strikes
  - `PitcherFeatureProvider`: pitcher_pitch_count (capped 130), home/away_sp_k_pct, home/away_sp_bb_pct
- **Look-ahead bias**: pitcher stats use ONLY previous-season data; rookies/first-year get league averages (K%=0.222, BB%=0.083)
- **Fallback**: if `.pkl` not found, falls back to legacy lookup table (`utils.py`)

### Alpha Decay Blending (`prediction.py`)
The strategy never uses raw model output directly — it uses `AlphaDecayPredictionModel.calculate_expected_win_prob(game)`:
- `P_pre` = pre-game Kalshi market price (fetched first 10 min of game)
- `P_live` = ML model output
- Early in game: `P_pre` dominates. As game progresses AND model conviction grows, `P_live` takes over.
- Params: `alpha_t=6` (time decay), `alpha_prob=12` (conviction scaling)
- **Pre-game price only available from 2025 season** — strategies must handle `pregame_winProbability == -1`

### GameState Construction
- From live game: `game.to_game_state()` on a `BaseballGame` object
- From historical data: `GameState.from_statcast_row(row)` from a pybaseball DataFrame row

## Adding a New Feature Signal

1. Create a `FeatureProvider` subclass in `game_state.py` implementing:
   - `get_features(state: GameState) -> dict[str, float]` — single inference
   - `get_features_batch(df: pd.DataFrame) -> pd.DataFrame` — vectorized for training
   - `feature_names` property
2. Register it in `PROVIDER_REGISTRY` at the bottom of `game_state.py`
3. Add new fields to `GameState` with sensible defaults (league avg or 0)
4. Update `BaseballGame.__init__()`, `to_game_state()`, and wherever the live API data is read in `domain.py`
5. Update `train_win_prob_model.py` to compute and join the new columns
6. Retrain: `python Scripts/train_win_prob_model.py --train-years 2015-2023 --test-year 2024`

## Strategy Architecture

Both strategies inherit from `BaseMLBStrategy` → `BaseStrategy`:

- `on_timestep(context)` → returns list of `Order` objects
- `on_resolution(context, outcome)` → cleanup
- `get_data_requirements()` → tells the engine which `DataLoader` to instantiate

`BaseMLBStrategy` provides: signal-transition gating (no churn), fractional Kelly sizing (25%), early exit (profit target +35¢, stop loss −25¢, model reversal).

**FavoriteLongShotStrategy**: long when model ≥60% and edge ≥5 pts; short when model ≤40% and edge ≥5 pts.

**MeanReversionStrategy**: fades when price moves >5 pts more than model over a 10-minute window.

## BacktestEngine Flow

```
run_backtest.py
  → fetch settled Kalshi markets
  → for each market:
      BaseballDataLoader.load()       # one MLB API call, disk-cached
        - parse all at-bats into play index with pre-computed state
        - compute cumulative pitch counts per pitcher
        - fetch pre-game win prob from Kalshi candlestick API
      for each timestamp (pitch event):
        data_loader.at_timestep(ts)   # reconstruct game state via bisect
        Kalshi candlestick API        # bid/ask at that minute
        strategy.on_timestep(context) # returns orders
        execution_model.execute()     # updates portfolio
      resolve: close positions, save to SQLite
```

## Market Ticker Format

`KXMLBGAME-{DDMMMYY}{TEAMS}-{HOME_TEAM}`

Example: `KXMLBGAME-23APR25NYYNYY-NYY` → April 23, 2025, NYY vs NYM, home team NYY.
Doubleheaders have `G1`/`G2` suffix in the TEAMS segment.

## Common Commands

```bash
# Train win probability model (slow — downloads ~700k pitches/season)
python Scripts/train_win_prob_model.py --train-years 2015-2023 --test-year 2024 --cache-dir D:/Data/statcast

# Calibrate model on held-out data
python Scripts/calibrate_win_prob_model.py --year 2024 --cache-dir D:/Data/statcast
python Scripts/calibrate_win_prob_model.py --year 2024 --plot calibration.png

# Run backtest (interactive: pick strategy + market range)
python Scripts/run_backtest.py

# Analyze backtest results from SQLite
python Scripts/analyze.py

# Pre-cache game data for faster backtesting
python Scripts/build_game_cache.py
```

## Key Dependencies

- `statsapi` — MLB Stats API (live game data, historical game data with timecodes)
- `pybaseball` — Statcast pitch-level data for model training
- `xgboost` — primary classifier (falls back to `sklearn.ensemble.HistGradientBoostingClassifier`)
- `joblib` — model serialization
- `pandas`, `numpy`, `scikit-learn` — data processing and evaluation
