---
name: new-strategy
description: Add a new trading strategy to the backtesting and live trading system. Use when the user wants to implement a new strategy, trading logic, or signal approach.
version: 1.0.0
---

# New Strategy

Add a new trading strategy that works in both backtest and live trading.

## Inheritance chain

```
BaseStrategy (Core/strategy.py)
    └── BaseMLBStrategy (Markets/Baseball/strategies.py)
            ├── FavoriteLongShotStrategy
            ├── MeanReversionStrategy
            └── YourNewStrategy   ← add here
```

Always inherit from `BaseMLBStrategy`, not `BaseStrategy` directly. `BaseMLBStrategy` provides Kelly sizing, signal-transition gating (no churn), and early exit logic for free.

## Required methods

```python
class YourNewStrategy(BaseMLBStrategy):

    def get_data_requirements(self) -> list[DataRequirement]:
        # Return [DataRequirement.BASEBALL] — same for all MLB strategies
        return [DataRequirement.BASEBALL]

    def on_timestep(self, context: Context) -> list[Order]:
        # Core logic. Called at every pitch event.
        # context.game       — BaseballGame (live state)
        # context.market     — Market (bid/ask/last price)
        # context.portfolio  — Portfolio (current positions, cash)
        # context.timestamp  — datetime of this tick

        win_prob = self.prediction_model.calculate_expected_win_prob(context.game)
        market_price = context.market.last_price  # in cents [0, 100]

        # ... your signal logic ...

        return self._build_orders(context, signal)  # use helper from BaseMLBStrategy

    def on_resolution(self, context: Context, outcome: str) -> None:
        # Called when game resolves. outcome is 'YES' or 'NO'.
        # Cleanup only — BaseMLBStrategy handles position closing.
        pass
```

## What `BaseMLBStrategy` provides (do NOT re-implement)

- **Kelly sizing** — `_kelly_size()` returns fractional Kelly position size (25% fraction)
- **Signal-transition gating** — ignores signal flips within the same inning to prevent churn
- **Early exit** — auto-closes positions at profit target (+35¢), stop loss (−25¢), or model reversal
- **`_build_orders()`** — converts a signal direction into properly sized `Order` objects
- **`prediction_model`** — pre-initialized `AlphaDecayPredictionModel` instance

## Register the strategy in the backtest CLI

In `Scripts/run_backtest.py`, find the strategy selection block and add your strategy:

```python
STRATEGIES = {
    "1": FavoriteLongShotStrategy,
    "2": MeanReversionStrategy,
    "3": YourNewStrategy,     # <-- add here
    "all": [FavoriteLongShotStrategy, MeanReversionStrategy, YourNewStrategy],
}
```

## Register for live trading

In `Scripts/run_live.py`, find where the strategy is instantiated and add a flag or config option to select your new strategy.

## Testing before full backtest

Run on a small slice first (20–30 markets) to verify:
1. No exceptions thrown during `on_timestep`
2. Orders are being generated (check `logs/backtest_*.log`)
3. `analyze.py` shows non-zero trade count

Then run the full backtest and compare Brier score and ROI against `MeanReversionStrategy` baseline (+5.83% ROI, Brier ~0.18).
