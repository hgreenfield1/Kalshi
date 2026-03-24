# Kalshi Baseball Trading Bot

A systematic trading bot for MLB baseball markets on [Kalshi](https://kalshi.com). Trades binary YES/NO contracts on "Will the home team win?" using a trained machine learning model and Kalshi market prices.

## How It Works

### The Core Idea

For any in-progress game, the bot has two probability estimates for the home team winning:

1. **Pre-game probability** — pulled from the Kalshi market price at first pitch (what the crowd thinks before the game starts)
2. **Live probability** — output of an ML model trained on 10 years of MLB Statcast pitch data

These are blended together using an alpha-decay weighting: early in the game, the pre-game market price dominates; as the game progresses and the model gains conviction, the live model takes over. The strategy then compares this blended probability against the current market price to find a tradeable edge.

### Win Probability Model

The live model is an XGBoost classifier trained on ~7 million pitches from 2015–2023 (via pybaseball). For each pitch in history, the model knows:

- Current inning, half-inning, outs
- Runners on base
- Score differential
- Ball/strike count
- Pitch count for the current pitcher in this game
- Starting pitcher quality (K% and BB% from the **previous** season — no look-ahead)

...and whether the home team ultimately won. At inference time it outputs P(home team wins) given the current game state.

The model is evaluated on 2024 data (held out from training). Typical Brier score ~0.157 (baseline 0.25).

### Trading Strategies

**FavoriteLongShot** — exploits the favorite-longshot bias. When the model has strong conviction (≥60% or ≤40%) and the market hasn't priced it in (≥5¢ edge), the bot takes a position.

**MeanReversion** — fades market overreactions. Tracks a 10-minute rolling window; when the market price moves significantly more than the model's probability, bet against the move.

Both strategies use fractional Kelly sizing (25% Kelly) and auto-exit on profit target (+35¢), stop loss (−25¢), or model reversal.

## Project Structure

```
Markets/Baseball/        Core baseball logic
  domain.py              BaseballGame: game state + live API integration
  data_loader.py         Loads/caches game data, reconstructs state at any past timestamp
  strategies.py          FavoriteLongShot and MeanReversion strategies
  prediction.py          Alpha-decay blending of pre-game and live probabilities
  game_state.py          GameState dataclass + extensible FeatureProvider system
  win_prob_model.py      ML model loader and inference

Core/                    Market-agnostic backtesting engine
Scripts/                 CLI scripts (train, backtest, analyze, calibrate)
Infrastructure/          Kalshi API clients
```

## Quickstart

### 1. Install dependencies

```bash
pip install statsapi pybaseball xgboost scikit-learn joblib pandas numpy
```

### 2. Train the win probability model

Downloads Statcast data (~700k pitches/season, 2015–2023) and trains the model. Takes ~30–60 minutes on first run; data is cached to parquet for subsequent runs.

```bash
python Scripts/train_win_prob_model.py --train-years 2015-2023 --test-year 2024 --cache-dir D:/Data/statcast
```

This saves `Markets/Baseball/win_prob_model.pkl`.

### 3. (Optional) Calibrate the model

Evaluates prediction accuracy on held-out data. Outputs a reliability table and stratified Brier scores by inning and score differential.

```bash
python Scripts/calibrate_win_prob_model.py --year 2024 --cache-dir D:/Data/statcast
python Scripts/calibrate_win_prob_model.py --year 2024 --plot calibration.png
```

### 4. Run a backtest

Replays historical Kalshi markets minute-by-minute against real MLB game data. Requires Kalshi API credentials.

```bash
python Scripts/run_backtest.py
# Prompts: select strategy, select market range
```

### 5. Analyze results

```bash
python Scripts/analyze.py
# Reads backtest_predictions.db and prints P&L, ROI, Brier score per strategy
```

## Model Performance

| Metric | Value |
|---|---|
| Brier score (2024 hold-out) | ~0.157 |
| Baseline (always predict 0.5) | 0.250 |
| ROC-AUC | ~0.82 |

Stratified Brier by inning:

| Innings | Brier |
|---|---|
| 1–3 | ~0.218 (high uncertainty) |
| 4–6 | ~0.157 |
| 7–9 | ~0.091 (low uncertainty) |
| Extra | ~0.186 |

## Extending the Model

The model uses a `FeatureProvider` plugin system. To add a new signal (e.g. bullpen ERA, batter handedness, weather):

1. Add a `FeatureProvider` subclass in `Markets/Baseball/game_state.py`
2. Register it in `PROVIDER_REGISTRY`
3. Add the new fields to `GameState` with fallback defaults
4. Populate the fields in `domain.py` from the live MLB API
5. Compute and join them in `train_win_prob_model.py`
6. Retrain

## Data Sources

- **Kalshi API** — market prices, candlestick data, order execution
- **MLB Stats API** (`statsapi`) — live and historical game state with per-pitch timestamps
- **pybaseball / Statcast** — pitch-level historical data for model training

## References

- Kalshi API client derived from [nikhilnd/kalshi-market-making](https://github.com/nikhilnd/kalshi-market-making)
- MLB Stats API: [toddrob99/MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI/wiki)
