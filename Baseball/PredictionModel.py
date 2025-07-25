import logging
import math
from abc import ABC, abstractmethod
from Baseball.BaseballGame import BaseballGame


class PredictionModel(ABC):
    """Abstract base class for prediction models."""
    
    def __init__(self):
        self._version = "1.0.0"
    
    @property
    def version(self) -> str:
        return self._version
    
    @abstractmethod
    def calculate_expected_win_prob(self, game: BaseballGame) -> float:
        """Calculate expected win probability for a given game state."""
        pass


class AlphaDecayPredictionModel(PredictionModel):
    """Prediction model using exponential decay weighting between pre-game and live probabilities."""
    
    def __init__(self, alpha_t: float = 6, alpha_prob: float = 12):
        super().__init__()
        self._version = "1.1.0"
        self.alpha_t = alpha_t  # Tunes the decay of pre-game probabilities as game progresses
        self.alpha_prob = alpha_prob  # Tunes the weighting of live vs pre-game probabilities as live prob moves away from 0.5
    
    def calculate_expected_win_prob(self, game: BaseballGame) -> float:
        t = game.pctPlayed
        P_pre = game.pregame_winProbability
        P_live = game.winProbability

        if P_live == -1:
            logging.warning("Live win probability is not available.")
            return None

        # Standard exponential decay weight
        base_weight = math.exp(-self.alpha_t * t)
        # Confidence factor: 0 at 0.5, 1 at 0 or 1 (scales up live weight as it moves away from 0.5)
        confidence = 1 - math.exp(-self.alpha_prob * abs(P_live - 50)/100)
        # Adjusted live weight
        live_weight = (1 - base_weight) * confidence
        # Adjusted pre-game weight
        pre_weight = 1 - live_weight

        # Normalize weights to sum to 1 (optional, but recommended)
        total = pre_weight + live_weight
        pre_weight /= total
        live_weight /= total

        return round(pre_weight * P_pre + live_weight * P_live, 2)