"""
DomainAdapter: interface between LiveGameEngine and market-specific event data.

LiveGameEngine uses this interface for everything that varies by market type:
  - fetching live state (statsapi for MLB, some other feed for NFL, etc.)
  - deciding whether the market is tradeable right now
  - deciding when the event has concluded
  - surfacing auxiliary data for the Context passed to strategies
  - fetching pre-event market opening prices

Each market type provides a concrete implementation.
"""

from abc import ABC, abstractmethod
from typing import Any


class DomainAdapter(ABC):
    """
    Adapts a live event to the interface expected by LiveGameEngine.

    Implementations encapsulate all sport/market-specific knowledge so
    LiveGameEngine stays market-agnostic.
    """

    @abstractmethod
    def update(self) -> None:
        """
        Fetch and apply the latest event state from the upstream source
        (e.g. statsapi, a REST feed, a push notification).

        Called every poll cycle. May be a no-op if the state is already fresh.
        Implementations should not raise; swallow errors and keep the last-known state.
        """
        ...

    @abstractmethod
    def build_auxiliary_data(self) -> dict[str, Any]:
        """
        Return the auxiliary_data dict that will be included in the Context
        passed to strategies on every tick.
        """
        ...

    @abstractmethod
    def is_tradeable(self) -> bool:
        """
        Return True when the market is in an active tradeable state.
        The engine skips the strategy call when this returns False.
        """
        ...

    @abstractmethod
    def is_complete(self) -> bool:
        """
        Return True when the event has concluded and the market will resolve.
        The engine calls _resolve() and exits the loop when this returns True.
        """
        ...

    @abstractmethod
    def get_outcome(self) -> bool:
        """
        Return the binary outcome: True if YES wins, False if NO wins.
        Only called after is_complete() returns True.
        """
        ...

    @abstractmethod
    def description(self) -> str:
        """
        Short human-readable description for log messages
        (e.g. "NYY @ BOS", "Chiefs vs Eagles").
        """
        ...

    # ------------------------------------------------------------------
    # Optional hooks — override when the market type supports them
    # ------------------------------------------------------------------

    def fetch_pregame_probability(self, market, http_client) -> None:
        """
        Fetch the pre-event Kalshi market opening price, if applicable.
        Called once when the event first transitions to a tradeable state.
        Default implementation is a no-op for markets that don't use it.
        """

    @property
    def pregame_probability_fetched(self) -> bool:
        """
        Return True once fetch_pregame_probability() has been called (or is
        not needed). The engine uses this to avoid re-fetching every tick.
        Default: True (no pre-game probability needed).
        """
        return True
