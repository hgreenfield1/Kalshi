from abc import ABC, abstractmethod
from typing import Dict, Any, List
import logging

class BaseDataLoader(ABC):
    """Abstract base for loading auxiliary data with lookahead protection."""

    def __init__(self, market, http_client):
        self.market = market
        self.http_client = http_client
        self._cache = {}

    @abstractmethod
    def load(self, timestamps: List[str]) -> None:
        """
        Pre-load all data for given timestamps.
        Called ONCE before backtest loop.
        Results stored in self._cache.
        """
        pass

    @abstractmethod
    def at_timestep(self, timestamp: str) -> Dict[str, Any]:
        """
        Return data available at this timestamp.
        CRITICAL: Must enforce lookahead protection.
        Only return data with timestamp <= current timestamp.
        """
        pass
