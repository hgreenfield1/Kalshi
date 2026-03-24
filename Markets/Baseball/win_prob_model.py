"""
Win probability model for baseball games.

Loads a pre-trained gradient boosting model and predicts P(home team wins)
from a GameState. Features are assembled by one or more FeatureProviders;
the list used during training is saved in the model's metadata and
reconstructed on load, so old single-provider models still work.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import joblib

from Markets.Baseball.game_state import (
    GameState,
    FeatureProvider,
    GameStateFeatureProvider,
    PROVIDER_REGISTRY,
)

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / 'win_prob_model.pkl'

# Maps runner_index (1-8 encoding in BaseballGame) to individual base flags.
_RUNNER_FLAGS: dict[int, Tuple[bool, bool, bool]] = {
    0: (False, False, False),
    1: (False, False, False),
    2: (True,  False, False),
    3: (False, True,  False),
    4: (True,  True,  False),
    5: (False, False, True),
    6: (True,  False, True),
    7: (False, True,  True),
    8: (True,  True,  True),
}


def runner_index_to_flags(runner_index: int) -> Tuple[bool, bool, bool]:
    """Convert the BaseballGame runner_index encoding to (on_1b, on_2b, on_3b)."""
    return _RUNNER_FLAGS.get(int(runner_index), (False, False, False))


class StatcastWinProbModel:
    """
    Trained gradient boosting model for in-game baseball win probability.

    Input:  GameState (pure on-field game state, no market data)
    Output: P(home team wins) as a float in [0, 1]

    Feature providers are reconstructed from the model's saved metadata,
    so the correct feature set is always used regardless of which version
    of the code loaded the model.
    """

    def __init__(self, model_path: Optional[Path] = None):
        path = Path(model_path or MODEL_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"Win probability model not found at {path}. "
                "Run Scripts/train_win_prob_model.py to train it first."
            )

        payload = joblib.load(path)
        self._model    = payload['model']
        self._metadata = payload.get('metadata', {})
        self._feature_cols: list[str] = self._metadata.get(
            'feature_cols', GameStateFeatureProvider.FEATURE_NAMES
        )

        # Reconstruct providers from saved metadata; fall back to game-state only
        provider_names: list[str] = self._metadata.get(
            'providers', ['GameStateFeatureProvider']
        )
        self._providers: list[FeatureProvider] = []
        for name in provider_names:
            cls = PROVIDER_REGISTRY.get(name)
            if cls is None:
                log.warning("Unknown provider '%s' in model metadata — skipping", name)
            else:
                self._providers.append(cls())

        if not self._providers:
            log.warning("No providers loaded; falling back to GameStateFeatureProvider")
            self._providers = [GameStateFeatureProvider()]

        log.info(
            "Loaded win probability model: %s  years=%s  pitches=%s  providers=%s",
            self._metadata.get('model_class', '?'),
            self._metadata.get('train_years', '?'),
            f"{self._metadata.get('train_pitches', 0):,}",
            provider_names,
        )

    @property
    def metadata(self) -> dict:
        return self._metadata

    @property
    def feature_cols(self) -> list[str]:
        return self._feature_cols

    def predict(self, state: GameState) -> float:
        """Return P(home team wins) in [0, 1] for the given GameState."""
        features: dict[str, float] = {}
        for provider in self._providers:
            features.update(provider.get_features(state))

        X = pd.DataFrame([features], columns=self._feature_cols)
        return float(self._model.predict_proba(X)[0, 1])

    def predict_from_game(self, game) -> float:
        """
        Convenience wrapper accepting a BaseballGame object.
        Calls game.to_game_state() if available, otherwise extracts attributes.
        """
        if hasattr(game, 'to_game_state'):
            return self.predict(game.to_game_state())

        on_1b, on_2b, on_3b = runner_index_to_flags(game.runner_index)
        return self.predict(GameState(
            inning=game.inning,
            is_top_inning=game.isTopInning,
            outs=game.outs,
            on_1b=on_1b, on_2b=on_2b, on_3b=on_3b,
            score_diff=game.net_score,
            balls=game.balls,
            strikes=game.strikes,
        ))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[StatcastWinProbModel] = None
_load_attempted = False


def get_win_prob_model() -> Optional[StatcastWinProbModel]:
    """
    Return the shared model, loading it on first call.
    Returns None if the model file doesn't exist yet (falls back to lookup table).
    """
    global _instance, _load_attempted
    if _load_attempted:
        return _instance
    _load_attempted = True
    try:
        _instance = StatcastWinProbModel()
    except FileNotFoundError:
        log.warning(
            "Statcast win probability model not found — falling back to legacy "
            "lookup table. Run Scripts/train_win_prob_model.py to train it."
        )
        _instance = None
    return _instance
