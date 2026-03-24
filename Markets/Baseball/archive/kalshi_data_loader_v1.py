import logging
from Core.data_loader import BaseDataLoader
import Utils.date_helpers as date_helpers


class KalshiDataLoader(BaseDataLoader):
    """
    Minimal data loader for Kalshi-price-only strategies.
    Generates timestamps from market open/close time.
    Makes no MLB Stats API calls.
    """

    def __init__(self, market, http_client, **kwargs):
        super().__init__(market, http_client)
        self._timestamps = []

    def get_timestamps(self) -> list:
        if self._timestamps:
            return self._timestamps

        open_time = getattr(self.market, 'open_time', None)
        close_time = getattr(self.market, 'close_time', None)

        if not open_time or not close_time:
            logging.error(f"Market {self.market.ticker} missing open_time or close_time")
            return []

        start = date_helpers.convert_utc_to_game_timestamp(open_time)
        end = date_helpers.convert_utc_to_game_timestamp(close_time)
        self._timestamps = date_helpers.get_backtest_timestamps(start, end)
        return self._timestamps

    def load(self, timestamps: list):
        """No-op — no auxiliary data to load."""
        pass

    def at_timestep(self, timestamp: str):
        """No auxiliary data — strategy uses only Kalshi prices from context."""
        return None

    def get_outcome(self) -> bool:
        """Return True if YES settled."""
        return getattr(self.market, 'result', None) == 'yes'
