---
name: add-feature-signal
description: Add a new feature signal to the ML win probability model. Use when the user wants to add a new input feature, signal, or predictor to the StatcastWinProbModel.
version: 1.0.0
---

# Add Feature Signal

Add a new feature signal to the `StatcastWinProbModel` XGBoost classifier.

## Checklist (do all 6 steps in order)

### Step 1 — Create a `FeatureProvider` subclass in `Markets/Baseball/game_state.py`

```python
class MyFeatureProvider(FeatureProvider):
    @property
    def feature_names(self) -> list[str]:
        return ["my_feature"]

    def get_features(self, state: GameState) -> dict[str, float]:
        return {"my_feature": state.my_field}

    def get_features_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        # Vectorized version — must match get_features exactly
        return df[["my_column"]].rename(columns={"my_column": "my_feature"})
```

Both `get_features` and `get_features_batch` are required. The batch version is used during training; the single version is used at inference time. They must produce identical values.

### Step 2 — Register in `PROVIDER_REGISTRY` (bottom of `game_state.py`)

```python
PROVIDER_REGISTRY: list[FeatureProvider] = [
    GameStateFeatureProvider(),
    PitcherFeatureProvider(),
    MyFeatureProvider(),   # <-- add here
]
```

### Step 3 — Add new fields to `GameState` dataclass (in `game_state.py`)

```python
@dataclass
class GameState:
    # ... existing fields ...
    my_field: float = 0.0   # sensible default: league average or 0
```

Default must be a valid fallback — it's used when data is unavailable.

### Step 4 — Populate the field in the live path (`Markets/Baseball/domain.py`)

Update `BaseballGame.__init__()`, `to_game_state()`, and wherever the live API response is parsed to assign the new field from live MLB API data.

### Step 5 — Compute the column in the training script (`Scripts/train_win_prob_model.py`)

Add a pandas operation to compute the new column from the Statcast DataFrame before training. Join it into the feature matrix.

### Step 6 — Retrain the model

```bash
python Scripts/train_win_prob_model.py --train-years 2015-2023 --test-year 2024 --cache-dir D:/Data/statcast
python Scripts/calibrate_win_prob_model.py --year 2024 --plot calibration.png
```

The new `.pkl` file replaces `Markets/Baseball/win_prob_model.pkl`.

## Critical rules

**Look-ahead bias:** Pitcher stats (`PitcherFeatureProvider`) use ONLY previous-season data. Never use current-season stats — they would not be available at game time in a live setting. If adding pitcher-based features, source them from the prior year's Statcast data.

**Rookie fallbacks:** First-year pitchers have no prior-season data. Use league averages as defaults:
- K% = 0.222
- BB% = 0.083

**`GameState` is pure on-field state:** Do not add market data (prices, spreads) to `GameState`. Market signals belong in the strategy layer, not the model input.
