# SignalAnalysis TODO

## Statistical Analysis of Backtest Results

Build a system to statistically analyze how well the prediction model's output (`predicted_price`) forecasts future market prices (`bid`, `ask`, `mid`).

### What this should do

- Pull prediction data from `backtest_predictions.db` (the unified backtest database)
- For each timestep, pair the model's predicted price with actual future market prices at multiple time horizons (e.g. 1, 2, 5, 10, 15, 30 minutes ahead)
- Compute statistical measures of predictive power:
  - Pearson correlation between predicted price and future bid/ask/mid
  - P-values for significance testing
  - R-squared (explained variance)
  - Mean Absolute Error (MAE) at each time horizon
- Break results down by prediction model version to track improvement over time
- Generate visualizations: correlation vs time horizon, R² vs time horizon, p-value significance plots

### Notes from prior attempt

The old `SignalAnalysis/` code was on the right track. Key ideas to carry forward:
- Group data by `game_id` before computing lagged pairs (don't leak across games)
- Skip rows with `None` prices or non-ISO timestamps (e.g. `"FINAL"` markers)
- Use `prediction_model_version` as a filter so model versions can be compared independently
- The analysis should read directly from `Core/database.py` (`BacktestDatabase`) rather than a separate signal DB

### Integration point

This belongs in `Scripts/` alongside `Scripts/analyze.py`, using `Core/database.py` as the data source.

---

## Timestamp Alignment in Backtest Engine

The current approach rounds each MLB event timestamp up to the next minute ceiling to align with Kalshi 1-minute candlesticks. This causes two issues:

1. **Many-to-one price mapping**: Multiple MLB events within the same minute all map to the same candlestick close price, so the strategy can open/flip positions multiple times at the identical price — inflating trade count and distorting P&L.
2. **Ceiling rounding lookahead**: Using the close of the minute containing the event means the price has already had up to 60 seconds to react to the event.

### Recommended fix

Before the engine's timestep loop, collapse consecutive MLB timestamps that share the same game state (inning, outs, runners, score). If the state hasn't changed, there's no signal and no reason to re-evaluate. This directly solves issue #1 without requiring higher-resolution price data.

### Location

`Core/engine.py` — `run_single_market`, between timestamp fetch and the main loop. The deduplication logic should live in `Markets/Baseball/data_loader.py` or a new helper, since the state comparison is baseball-specific.
