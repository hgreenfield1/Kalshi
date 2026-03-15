from Core.data_loader import BaseDataLoader
from Markets.Baseball.domain import BaseballGame, market_to_game
import statsapi
import logging
from multiprocessing import cpu_count
from concurrent.futures import ProcessPoolExecutor, TimeoutError, as_completed
import Utils.date_helpers as date_helpers

def fetch_game_data(args):
    """Fetch game data for single timestamp (multiprocessing worker)."""
    game_id, timestamp = args
    try:
        timestamp_formatted = date_helpers.convert_utc_to_game_timestamp(timestamp)
        game_data = statsapi.get('game', {'gamePk': game_id, 'timecode': timestamp_formatted})
        return (timestamp, game_data)
    except Exception as e:
        logging.error(f"Error fetching data for game {game_id} at {timestamp}: {e}")
        return (timestamp, None)

class BaseballDataLoader(BaseDataLoader):
    """Loads baseball game data using MLB Stats API."""

    def __init__(self, market, http_client, **kwargs):
        super().__init__(market, http_client)
        # Parse market to get game
        self.game = market_to_game(market)
        self._timestamps = []

    def get_timestamps(self) -> list:
        """Get timestamps for this game."""
        if self._timestamps:
            return self._timestamps

        # Get game timestamps from statsapi
        try:
            timestamps_data = statsapi.get('game_timestamps', {'gamePk': self.game.game_id})
            timestamps = [ts for ts in timestamps_data if ts]
            self._timestamps = timestamps
            return timestamps
        except Exception as e:
            logging.error(f"Error fetching timestamps for game {self.game.game_id}: {e}")
            return []

    def load(self, timestamps: list):
        """Pre-load all game data using multiprocessing."""
        logging.info(f"Pre-loading baseball data for game {self.game.game_id}")

        args = [(self.game.game_id, ts) for ts in timestamps]

        with ProcessPoolExecutor(max_workers=min(cpu_count(), len(timestamps))) as executor:
            future_to_ts = {executor.submit(fetch_game_data, arg): arg[1] for arg in args}

            for future in as_completed(future_to_ts, timeout=300):
                timestamp = future_to_ts[future]
                try:
                    result_ts, data = future.result(timeout=15)
                    self._cache[result_ts] = data
                except TimeoutError:
                    logging.warning(f"Timeout fetching data at {timestamp}")
                    self._cache[timestamp] = None
                except Exception as e:
                    logging.error(f"Exception at {timestamp}: {e}")
                    self._cache[timestamp] = None

        successful = sum(1 for d in self._cache.values() if d is not None)
        logging.info(f"Loaded {successful}/{len(timestamps)} game states")

    def at_timestep(self, timestamp: str) -> dict:
        """Return game state at timestamp with lookahead protection."""
        if timestamp in self._cache and self._cache[timestamp] is not None:
            # Update game with cached data
            self.game.update_status(timestamp, self._cache)
            return {'game': self.game}
        return {'game': None}

    def get_outcome(self) -> bool:
        """Return whether home team won."""
        self.game.update_status()  # Get final state
        return self.game.net_score > 0
