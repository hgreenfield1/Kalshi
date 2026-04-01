---
name: backtest
description: Run a backtest and analyze results. Use when the user wants to test a strategy, run a backtest, check P&L or Brier scores, or compare strategy performance.
version: 1.0.0
---

# Backtest

Run a strategy backtest and analyze the results.

## Full workflow

Backtesting is always two steps:

```bash
# Step 1: Run backtest (writes trades to backtest_predictions.db)
cd C:/Users/henry/Kalshi && python Scripts/run_backtest.py

# Step 2: Analyze results
python Scripts/analyze.py
```

Never skip step 2 — the backtest script does not print P&L summaries itself.

## Scoping the backtest

For quick validation (parameter tweak, sanity check), use a small market slice — the script prompts for start/end index. 20–50 markets is usually enough. Full backtests use all available markets (1,900+) and take much longer.

**Strategy numbers (interactive prompt):**
- `1` — FavoriteLongShotStrategy
- `2` — MeanReversionStrategy
- `3` — InningAdjustedEdgeStrategy (if implemented)
- `all` — run all strategies back-to-back

## Interpreting analyze.py output

| Metric | What "good" looks like |
|--------|------------------------|
| Brier score | < 0.20 (lower = better calibration) |
| ROI | > 0% (positive is profitable) |
| Win rate | > 50% (for directional strategies) |
| Total P&L | Positive after slippage |

If Brier score is high (> 0.25) but ROI is positive, the model is miscalibrated but the strategy edge is real. Investigate inning-level breakdown.

## Log location

Backtest logs: `logs/backtest_*.log` (timestamped). Check here for errors if the database is empty after a run.

## Common issues

- **Empty results in analyze.py** — backtest probably crashed mid-run. Check `logs/backtest_*.log`.
- **`pregame_winProbability == -1`** — expected for pre-2025 games; strategies must handle this gracefully (see `AlphaDecayPredictionModel`).
- **Cache miss slowing things down** — run `python Scripts/build_game_cache.py` first to pre-fetch MLB game data.
