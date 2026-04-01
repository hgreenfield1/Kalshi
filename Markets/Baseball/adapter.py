"""
BaseballDomainAdapter: bridges LiveGameEngine and BaseballGame.

Implements the DomainAdapter interface so LiveGameEngine has no direct
dependency on BaseballGame or any MLB-specific code.
"""

from typing import Any

from Core.domain_adapter import DomainAdapter
from Markets.Baseball.domain import BaseballGame

_TERMINAL_STATUSES = {'Final', 'Game Over', 'Completed Early'}
_TRADEABLE_STATUS = 'In Progress'


class BaseballDomainAdapter(DomainAdapter):
    """DomainAdapter implementation for MLB baseball games."""

    def __init__(self, game: BaseballGame):
        self._game = game
        self._pregame_fetched = False

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Delegate to BaseballGame.update_status() (called with timeout in engine)."""
        self._game.update_status()

    def build_auxiliary_data(self) -> dict[str, Any]:
        return {'game': self._game}

    def is_tradeable(self) -> bool:
        return self._game.status == _TRADEABLE_STATUS

    def is_complete(self) -> bool:
        return self._game.status in _TERMINAL_STATUSES

    def get_outcome(self) -> bool:
        return self._game.home_score > self._game.away_score

    def description(self) -> str:
        return f'{self._game.away_team_abv} @ {self._game.home_team_abv}'

    # ------------------------------------------------------------------
    # Pre-game probability hook
    # ------------------------------------------------------------------

    def fetch_pregame_probability(self, market, http_client) -> None:
        # Always mark as fetched (even on failure) so the engine doesn't retry
        # every tick. update_pregame_win_probability falls back to a statistical
        # estimate internally, so a failure here leaves pregame_winProbability at -1
        # and the prediction model will substitute 50%.
        try:
            self._game.update_pregame_win_probability(market, http_client)
        finally:
            self._pregame_fetched = True

    @property
    def pregame_probability_fetched(self) -> bool:
        return self._pregame_fetched

    # ------------------------------------------------------------------
    # Pass-through properties used by Scheduler for logging
    # ------------------------------------------------------------------

    @property
    def home_team_abv(self) -> str:
        return self._game.home_team_abv

    @property
    def away_team_abv(self) -> str:
        return self._game.away_team_abv

    @property
    def home_score(self) -> int:
        return self._game.home_score

    @property
    def away_score(self) -> int:
        return self._game.away_score

    @property
    def status(self) -> str:
        return self._game.status

    @property
    def game(self) -> BaseballGame:
        """Direct access to the underlying BaseballGame, for code that still needs it."""
        return self._game
