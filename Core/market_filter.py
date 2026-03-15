from abc import ABC, abstractmethod
from typing import List
from Infrastructure.market import Market

class MarketFilter(ABC):
    """Abstract base for market filtering."""

    @abstractmethod
    def filter(self, markets: List[Market]) -> List[Market]:
        """Return filtered subset of markets."""
        pass

class SeriesMarketFilter(MarketFilter):
    """Filter by series ticker."""

    def __init__(self, series_tickers: List[str]):
        self.series_tickers = series_tickers

    def filter(self, markets: List[Market]) -> List[Market]:
        return [m for m in markets if m.series_ticker in self.series_tickers]

class StatusMarketFilter(MarketFilter):
    """Filter by market status."""

    def __init__(self, status: str):
        self.status = status

    def filter(self, markets: List[Market]) -> List[Market]:
        return [m for m in markets if m.status == self.status]

class CompositeMarketFilter(MarketFilter):
    """Combine multiple filters with AND logic."""

    def __init__(self, *filters: MarketFilter):
        self.filters = filters

    def filter(self, markets: List[Market]) -> List[Market]:
        result = markets
        for f in self.filters:
            result = f.filter(result)
        return result
