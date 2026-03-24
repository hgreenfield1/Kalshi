"""
Game state representation and feature providers for the win probability model.

GameState is the canonical input to the model — a plain dataclass that can be
constructed from either a live BaseballGame (via game.to_game_state()) or from
historical pybaseball Statcast data (via GameState.from_statcast_row(row)).

FeatureProvider is the extension point for adding new signals. Each provider
computes one conceptual group of features from a GameState. To add a new signal:
  1. Create a new FeatureProvider subclass.
  2. Register it in train_win_prob_model.py and win_prob_model.py.
  3. Retrain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# League-average K% and BB% (2015-2024 Statcast era) used as fallback
# when a pitcher has no prior-season data (rookies, first Statcast year).
LEAGUE_AVG_K_PCT  = 0.222
LEAGUE_AVG_BB_PCT = 0.083


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    """
    Minimal game state for win probability prediction.

    Can be constructed from a live BaseballGame object or from a row of
    historical pybaseball Statcast data. Contains no Kalshi market data.

    Pitcher fields default to league averages so the model degrades
    gracefully when external stats are unavailable (pre-game, backtest
    without a stats table, rookie pitchers, etc.).
    """
    # Core game state — always available
    inning: int          # current inning (1-based; 10+ = extra innings)
    is_top_inning: bool  # True = top half, away team batting
    outs: int            # outs in current half-inning (0-2)
    on_1b: bool
    on_2b: bool
    on_3b: bool
    score_diff: int      # home_score - away_score
    balls: int = 0
    strikes: int = 0

    # Pitcher features — populated from external data when available
    pitcher_pitch_count: int = 0             # pitches current pitcher has thrown in this game
    home_sp_k_pct:  float = LEAGUE_AVG_K_PCT  # home starter previous-season K%
    home_sp_bb_pct: float = LEAGUE_AVG_BB_PCT # home starter previous-season BB%
    away_sp_k_pct:  float = LEAGUE_AVG_K_PCT
    away_sp_bb_pct: float = LEAGUE_AVG_BB_PCT

    @classmethod
    def from_statcast_row(cls, row) -> GameState:
        """
        Construct from a pybaseball Statcast row (pd.Series or dict).
        Pitcher fields are read if the columns exist, otherwise use defaults.
        """
        return cls(
            inning=int(row['inning']),
            is_top_inning=str(row['inning_topbot']).startswith('T'),
            outs=int(row['outs_when_up']),
            on_1b=pd.notna(row['on_1b']),
            on_2b=pd.notna(row['on_2b']),
            on_3b=pd.notna(row['on_3b']),
            score_diff=int(row['home_score']) - int(row['away_score']),
            balls=int(row['balls']),
            strikes=int(row['strikes']),
            pitcher_pitch_count=int(row['pitcher_pitch_count']) if 'pitcher_pitch_count' in row else 0,
            home_sp_k_pct=float(row['home_sp_k_pct'])   if 'home_sp_k_pct'  in row and pd.notna(row['home_sp_k_pct'])  else LEAGUE_AVG_K_PCT,
            home_sp_bb_pct=float(row['home_sp_bb_pct']) if 'home_sp_bb_pct' in row and pd.notna(row['home_sp_bb_pct']) else LEAGUE_AVG_BB_PCT,
            away_sp_k_pct=float(row['away_sp_k_pct'])   if 'away_sp_k_pct'  in row and pd.notna(row['away_sp_k_pct'])  else LEAGUE_AVG_K_PCT,
            away_sp_bb_pct=float(row['away_sp_bb_pct']) if 'away_sp_bb_pct' in row and pd.notna(row['away_sp_bb_pct']) else LEAGUE_AVG_BB_PCT,
        )


# ---------------------------------------------------------------------------
# FeatureProvider ABC
# ---------------------------------------------------------------------------

class FeatureProvider(ABC):
    """
    Computes a group of model features from a GameState.

    Subclasses must implement both a single-state method (used during live
    inference) and a vectorized batch method (used during training).
    """

    @abstractmethod
    def get_features(self, state: GameState) -> dict[str, float]:
        """Compute features for one game state. Returns {name: value}."""
        ...

    @abstractmethod
    def get_features_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Vectorized feature computation over a raw Statcast DataFrame.
        Returns a DataFrame whose columns match feature_names, same index as df.
        """
        ...

    @property
    @abstractmethod
    def feature_names(self) -> list[str]:
        """Ordered list of feature names this provider returns."""
        ...


# ---------------------------------------------------------------------------
# GameStateFeatureProvider — core on-field state, always available
# ---------------------------------------------------------------------------

class GameStateFeatureProvider(FeatureProvider):
    """
    Core baseball game state features, derivable from live API and pybaseball.

    Features:
        inning           - 1-9 (extra innings capped at 9)
        is_extra_innings - 1 if inning > 9
        is_bottom        - 1 = home batting, 0 = away batting
        outs             - 0-2
        on_1b/2b/3b      - runner presence flags
        score_diff       - home minus away, clipped to [-10, 10]
        balls            - 0-3
        strikes          - 0-2
    """

    FEATURE_NAMES = [
        'inning', 'is_extra_innings', 'is_bottom',
        'outs', 'on_1b', 'on_2b', 'on_3b',
        'score_diff', 'balls', 'strikes',
    ]

    def get_features(self, state: GameState) -> dict[str, float]:
        return {
            'inning':           float(min(state.inning, 9)),
            'is_extra_innings': float(state.inning > 9),
            'is_bottom':        float(not state.is_top_inning),
            'outs':             float(state.outs),
            'on_1b':            float(state.on_1b),
            'on_2b':            float(state.on_2b),
            'on_3b':            float(state.on_3b),
            'score_diff':       float(np.clip(state.score_diff, -10, 10)),
            'balls':            float(state.balls),
            'strikes':          float(state.strikes),
        }

    def get_features_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        raw_inning = df['inning'].clip(lower=1)
        result = pd.DataFrame(index=df.index)
        result['inning']           = raw_inning.clip(upper=9).astype(int)
        result['is_extra_innings'] = (raw_inning > 9).astype(int)
        result['is_bottom']        = (df['inning_topbot'] == 'Bot').astype(int)
        result['outs']             = df['outs_when_up'].clip(0, 2).astype(int)
        result['on_1b']            = df['on_1b'].notna().astype(int)
        result['on_2b']            = df['on_2b'].notna().astype(int)
        result['on_3b']            = df['on_3b'].notna().astype(int)
        result['score_diff']       = (df['home_score'] - df['away_score']).clip(-10, 10).astype(int)
        result['balls']            = df['balls'].clip(0, 3).astype(int)
        result['strikes']          = df['strikes'].clip(0, 2).astype(int)
        return result[self.FEATURE_NAMES]

    @property
    def feature_names(self) -> list[str]:
        return self.FEATURE_NAMES


# ---------------------------------------------------------------------------
# PitcherFeatureProvider — pitch count + starting pitcher quality
# ---------------------------------------------------------------------------

class PitcherFeatureProvider(FeatureProvider):
    """
    Pitcher-level features: current pitch count and starting pitcher quality.

    Pitch count:
        How many pitches the current pitcher has thrown in this game before
        this plate appearance. Captures fatigue; the model learns the nonlinear
        degradation curve. Capped at 130 to avoid extreme-outlier leverage.

    Starter K% and BB%:
        Previous season's strikeout and walk rates for each team's starting
        pitcher, computed entirely from prior-year Statcast data.

        Critically: only PREVIOUS season stats are used — never the current
        season — so there is no look-ahead bias even for the first game of
        the year. New pitchers or seasons without prior Statcast data (2015)
        fall back to league averages.

    Batch method reads pre-joined columns; the training pipeline is
    responsible for computing and joining these columns before calling
    get_features_batch().
    """

    FEATURE_NAMES = [
        'pitcher_pitch_count',
        'home_sp_k_pct',
        'home_sp_bb_pct',
        'away_sp_k_pct',
        'away_sp_bb_pct',
    ]

    def get_features(self, state: GameState) -> dict[str, float]:
        return {
            'pitcher_pitch_count': float(min(state.pitcher_pitch_count, 130)),
            'home_sp_k_pct':       float(state.home_sp_k_pct),
            'home_sp_bb_pct':      float(state.home_sp_bb_pct),
            'away_sp_k_pct':       float(state.away_sp_k_pct),
            'away_sp_bb_pct':      float(state.away_sp_bb_pct),
        }

    def get_features_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result['pitcher_pitch_count'] = df['pitcher_pitch_count'].clip(0, 130).fillna(0).astype(float)
        result['home_sp_k_pct']       = df['home_sp_k_pct'].fillna(LEAGUE_AVG_K_PCT).astype(float)
        result['home_sp_bb_pct']      = df['home_sp_bb_pct'].fillna(LEAGUE_AVG_BB_PCT).astype(float)
        result['away_sp_k_pct']       = df['away_sp_k_pct'].fillna(LEAGUE_AVG_K_PCT).astype(float)
        result['away_sp_bb_pct']      = df['away_sp_bb_pct'].fillna(LEAGUE_AVG_BB_PCT).astype(float)
        return result[self.FEATURE_NAMES]

    @property
    def feature_names(self) -> list[str]:
        return self.FEATURE_NAMES


# ---------------------------------------------------------------------------
# Registry — maps saved names back to provider classes
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: dict[str, type[FeatureProvider]] = {
    'GameStateFeatureProvider': GameStateFeatureProvider,
    'PitcherFeatureProvider':   PitcherFeatureProvider,
}
