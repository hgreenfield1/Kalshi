"""
MarketDiscovery: interface for resolving a scheduled game/event to a Kalshi ticker.

Each market type (MLB, NFL, elections, …) provides its own implementation.
The Scheduler calls discover() for each event and never needs to know how
the ticker was resolved.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class MarketDiscovery(ABC):
    """
    Resolves a scheduled event to a Kalshi market ticker.

    Implementations are responsible for all market-specific knowledge:
    ticker format, API search strategy, team/event name mapping, etc.
    """

    @abstractmethod
    def discover(
        self,
        home_team: str,
        away_team: str,
        game_date: str,
        scheduled_start_utc: datetime,
        game_num: int,
        http_client,
    ) -> Optional[str]:
        """
        Return the Kalshi market ticker for this event, or None if no market
        is found.

        Args:
            home_team:            Market-specific home team identifier
                                  (e.g. Kalshi 3-letter abbreviation for MLB)
            away_team:            Market-specific away team identifier
            game_date:            Calendar date of the game in 'YYYY-MM-DD' format
                                  (US local date as reported by the schedule source)
            scheduled_start_utc:  First-pitch / event-start time in UTC
            game_num:             1 for regular games, 2 for doubleheader game 2
            http_client:          KalshiHttpClient instance for API calls
        """
        ...
