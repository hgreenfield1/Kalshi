import bisect
import gzip
import json
from pathlib import Path
from Core.data_loader import BaseDataLoader
from Markets.Baseball.domain import BaseballGame, market_to_game
from Markets.Baseball.config import GAME_CACHE_DIR
import statsapi
import logging
import Utils.date_helpers as date_helpers


class BaseballDataLoader(BaseDataLoader):
    """Loads baseball game data using MLB Stats API with disk caching."""

    def __init__(self, market, http_client, pitcher_stats: dict = None, **kwargs):
        """
        Args:
            pitcher_stats: Optional dict {team_abv: {'k_pct': float, 'bb_pct': float}}
                           for starting pitcher quality. Loaded into game on first load().
        """
        super().__init__(market, http_client)
        self.game = self._load_game_info(market)
        self._pitcher_stats = pitcher_stats or {}
        self._timestamps = []
        # Each entry: (start_unix, play, start_outs, start_home_score, start_away_score, pitcher_pitch_count)
        self._play_index = []
        self._game_end_unix = None

    def _load_game_info(self, market) -> BaseballGame:
        """Load game info from cache or resolve via statsapi.schedule()."""
        cache_file = GAME_CACHE_DIR / f"game_info_{market.ticker}.json"

        if cache_file.exists():
            with open(cache_file, 'r') as f:
                info = json.load(f)
            return BaseballGame(
                info['game_id'], info['home_team'], info['away_team'],
                info['game_date'], info['game_datetime'], info['status']
            )

        game = market_to_game(market)
        if game:
            try:
                GAME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with open(cache_file, 'w') as f:
                    json.dump({
                        'game_id': game.game_id,
                        'home_team': game.home_team_abv,
                        'away_team': game.away_team_abv,
                        'game_date': game.game_date,
                        'game_datetime': game.start_time,
                        'status': game.status
                    }, f)
            except Exception as e:
                logging.warning(f"Could not cache game info for {market.ticker}: {e}")
        return game

    def get_timestamps(self) -> list:
        """Get timestamps for this game, using disk cache if available."""
        if self._timestamps:
            return self._timestamps

        cache_file = GAME_CACHE_DIR / f"{self.game.game_id}_timestamps.json.gz"

        if cache_file.exists():
            with gzip.open(cache_file, 'rt', encoding='utf-8') as f:
                self._timestamps = json.load(f)
            return self._timestamps

        try:
            timestamps_data = statsapi.get('game_timestamps', {'gamePk': self.game.game_id})
            self._timestamps = [ts for ts in timestamps_data if ts]
        except Exception as e:
            logging.error(f"Error fetching timestamps for game {self.game.game_id}: {e}")
            return []

        try:
            with gzip.open(cache_file, 'wt', encoding='utf-8') as f:
                json.dump(self._timestamps, f)
        except Exception as e:
            logging.warning(f"Could not cache timestamps for game {self.game.game_id}: {e}")

        return self._timestamps

    def load(self, timestamps: list):
        """Load game data via disk cache (single API call fallback)."""
        logging.info(f"Pre-loading baseball data for game {self.game.game_id}")

        # Set pregame win probability from market prices
        try:
            self.game.update_pregame_win_probability(self.market, self.http_client)
            logging.info(f"Pregame win probability: {self.game.pregame_winProbability:.1f}")
        except Exception as e:
            logging.warning(f"Could not get pregame win probability: {e}")

        game_data = self._load_game_data()
        all_plays = game_data['liveData']['plays']['allPlays']

        # Load starter quality stats if provided
        if self._pitcher_stats:
            self.game.load_starter_stats(self._pitcher_stats)

        # v1: process atBat plays only
        at_bats = [p for p in all_plays if p.get('result', {}).get('type') == 'atBat']

        # Pre-compute cumulative pitch counts per pitcher across the game.
        # pitch_count_before[i] = pitches thrown by play[i]'s pitcher before this at-bat.
        pitcher_cumulative: dict[int, int] = {}  # pitcher_id -> cumulative pitch count
        pitch_count_before: list[int] = []
        for play in at_bats:
            pitcher_id = play.get('matchup', {}).get('pitcher', {}).get('id')
            current_count = pitcher_cumulative.get(pitcher_id, 0)
            pitch_count_before.append(current_count)
            # Count pitches in this at-bat
            n_pitches = sum(
                1 for e in play.get('playEvents', [])
                if e.get('type') == 'pitch'
            )
            if pitcher_id is not None:
                pitcher_cumulative[pitcher_id] = current_count + n_pitches

        # Build play index with pre-computed start-of-play state
        raw_index = []
        for i, play in enumerate(at_bats):
            start_time = play['about'].get('startTime')
            if not start_time:
                continue

            if i == 0:
                start_outs = 0
                start_home_score = 0
                start_away_score = 0
            else:
                prev = at_bats[i - 1]
                same_half = (
                    prev['about']['inning'] == play['about']['inning']
                    and prev['about']['isTopInning'] == play['about']['isTopInning']
                )
                start_outs = prev['count']['outs'] if same_half else 0
                start_home_score = prev['result']['homeScore']
                start_away_score = prev['result']['awayScore']

            ts_unix = date_helpers.game_timestamp_to_unix(start_time)
            raw_index.append((ts_unix, play, start_outs, start_home_score, start_away_score, pitch_count_before[i]))

        self._play_index = sorted(raw_index, key=lambda x: x[0])

        if self._play_index:
            last_play = self._play_index[-1][1]
            end_time = last_play['about'].get('endTime')
            self._game_end_unix = (
                date_helpers.game_timestamp_to_unix(end_time) if end_time
                else self._play_index[-1][0] + 300
            )

        logging.info(f"Loaded {len(self._play_index)} plays for game {self.game.game_id}")

    def at_timestep(self, timestamp: str):
        """Return game object reflecting state at the given timestamp."""
        if not self._play_index:
            return None

        ts_unix = date_helpers.game_timestamp_to_unix(timestamp)

        if self._game_end_unix and ts_unix >= self._game_end_unix:
            _, last_play, _, last_home, last_away, _ = self._play_index[-1]
            self.game.update_from_play(last_play, last_play['count']['outs'], last_home, last_away, is_final=True)
            return self.game

        keys = [entry[0] for entry in self._play_index]
        idx = bisect.bisect_right(keys, ts_unix) - 1

        if idx < 0:
            self.game.set_pregame_state()
            return self.game

        _, play, start_outs, start_home, start_away, pitch_count = self._play_index[idx]
        self.game.update_from_play(play, start_outs, start_home, start_away, pitcher_pitch_count=pitch_count)
        return self.game

    def _load_game_data(self) -> dict:
        """Load final game state from disk cache, fetching from API on cache miss."""
        cache_file = GAME_CACHE_DIR / f"{self.game.game_id}.json.gz"

        if cache_file.exists():
            with gzip.open(cache_file, 'rt', encoding='utf-8') as f:
                return json.load(f)

        game_data = statsapi.get('game', {'gamePk': self.game.game_id})

        try:
            GAME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with gzip.open(cache_file, 'wt', encoding='utf-8') as f:
                json.dump(game_data, f)
        except Exception as e:
            logging.warning(f"Could not write cache for game {self.game.game_id}: {e}")

        return game_data

    def get_outcome(self) -> bool:
        """Return whether home team won, using cached game data."""
        game_data = self._load_game_data()
        home = game_data['liveData']['linescore']['teams']['home']['runs']
        away = game_data['liveData']['linescore']['teams']['away']['runs']
        return home > away
