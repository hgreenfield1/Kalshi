import statsapi
import logging
from datetime import datetime
from Infrastructure.market import Market
from Markets.Baseball.utils import mlb_teams, getProbability
from Markets.Baseball.game_state import GameState, LEAGUE_AVG_K_PCT, LEAGUE_AVG_BB_PCT
from Markets.Baseball.win_prob_model import get_win_prob_model, runner_index_to_flags
from Markets.Baseball.pregame_model import estimate as estimate_pregame_prob
from Markets.Baseball.team_stats import get_team_win_pct
import Utils.date_helpers as date_helpers


def market_to_game(market: Market):
    _, data, team1 = market.ticker.split('-')

    year = "20" + str(data[0:2])
    month_str = data[2:5]
    day_str = data[5:7]
    teams = data[7:]
    is_doubleheader_g2 = "G2" in teams
    team2 = teams.replace(team1, '', 1)
    if "G2" in team2:
        logging.warning(f"G2 of doubleheader {team1} vs {team2} found in market ticker. Removing G2 from team2.")
        team2 = team2.replace("G2", "", 1)
    if "G1" in team2:
        logging.warning(f"G1 of doubleheader {team1} vs {team2} found in market ticker. Removing G1 from team2.")
        team2 = team2.replace("G1", "", 1)
    if "2" in team2:
        logging.warning(f"G2 of doubleheader {team1} vs {team2} found in market ticker. Removing 2 from team2.")
        team2 = team2.replace("2", "", 1)

    # Convert month abbreviation to number
    date_obj = datetime.strptime(f"{day_str} {month_str} {year}", "%d %b %Y")
    date_str = datetime.strftime(date_obj, '%m/%d/%Y')

    # Get statsapi info
    schedule = statsapi.schedule(date_str)
    team1_full_name = mlb_teams[team1]
    team2_full_name = mlb_teams[team2]

    date_str_statsapi = datetime.strftime(date_obj, '%Y-%m-%d')
    for game in schedule:
        if is_doubleheader_g2:
            if game['home_name'] == team1_full_name and game['away_name'] == team2_full_name and game['game_date'] == date_str_statsapi and game['game_num'] == 2:
                return BaseballGame(game['game_id'], team1, team2, game['game_date'], game['game_datetime'], game['status'])
            if game['home_name'] == team2_full_name and game['away_name'] == team1_full_name and game['game_date'] == date_str_statsapi and game['game_num'] == 2:
                return BaseballGame(game['game_id'], team2, team1, game['game_date'], game['game_datetime'], game['status'])
        else:
            if game['home_name'] == team1_full_name and game['away_name'] == team2_full_name and game['game_date'] == date_str_statsapi:
                return BaseballGame(game['game_id'], team1, team2, game['game_date'], game['game_datetime'], game['status'])
            if game['home_name'] == team2_full_name and game['away_name'] == team1_full_name and game['game_date'] == date_str_statsapi:
                return BaseballGame(game['game_id'], team2, team1, game['game_date'], game['game_datetime'], game['status'])

    Exception("Unable to match market to statsapi baseball game.")


class BaseballGame:
    def __init__(self, game_id, home_team_abv, away_team_abv, game_date, start_time, status):
        self.game_id = game_id
        self.home_team_abv = home_team_abv
        self.home_team_full = mlb_teams[home_team_abv]
        self.away_team_abv = away_team_abv
        self.away_team_full = mlb_teams[away_team_abv]
        self.game_date = game_date
        self.start_time = start_time
        self.status = status

        self.pregame_winProbability = -1
        self.pctPlayed = 0
        self.winProbability = -1
        self.home_score = 0
        self.away_score = 0
        self.net_score = 0

        self.inning = 1
        self.isTopInning = True
        self.outs = 0
        self.balls = 0
        self.strikes = 0
        self.runner_index = 0
        self.captivating_index = 0

        # Pitcher features — populated during load or live update
        self.pitcher_pitch_count = 0
        self.home_sp_k_pct  = LEAGUE_AVG_K_PCT
        self.home_sp_bb_pct = LEAGUE_AVG_BB_PCT
        self.away_sp_k_pct  = LEAGUE_AVG_K_PCT
        self.away_sp_bb_pct = LEAGUE_AVG_BB_PCT

        # Batter-pitcher matchup features
        self.is_starter = 1
        self.current_pitcher_k_pct  = LEAGUE_AVG_K_PCT
        self.current_pitcher_bb_pct = LEAGUE_AVG_BB_PCT
        self.platoon_adv_batter = 0
        self.batting_order_pos  = 5

        # Team quality
        self.home_run_diff_per_game = 0.0
        self.away_run_diff_per_game = 0.0

    def update_status(self, timestamp=None, game_data_cache=None):
        if game_data_cache and timestamp and timestamp in game_data_cache:
            game_data = game_data_cache[timestamp]
        elif not timestamp:
            game_data = statsapi.get('game', {'gamePk': self.game_id})
        else:
            timestamp = date_helpers.convert_utc_to_game_timestamp(timestamp)
            game_data = statsapi.get('game', {'gamePk': self.game_id, 'timecode': timestamp})

        self.status = game_data['gameData']['status']['detailedState']
        if self.status == "Warmup":
            self.status = "Pre-Game"
        self.home_score = game_data['liveData']['linescore']['teams']['home']['runs']
        self.away_score = game_data['liveData']['linescore']['teams']['away']['runs']
        self.net_score = self.home_score - self.away_score

        if self.status == "In Progress":
            self.inning = game_data['liveData']['linescore']['currentInning']
            self.isTopInning = game_data['liveData']['linescore']['isTopInning']
            current_play = game_data['liveData']['plays']['currentPlay']
            self.outs = current_play['count']['outs']
            self.balls = current_play['count']['balls']
            self.strikes = current_play['count']['strikes']
            self.runner_index = self.get_runner_state(current_play['runners'])
            self.captivating_index = current_play['about']['captivatingIndex']
            self._update_pitcher_pitch_count(game_data)
            self._update_matchup_features(game_data, current_play)
            self.roll_status()
            self.winProbability = self.get_win_probability()

        elif self.status == "Delayed":
            logging.warning(f"Game {self.game_id} is delayed. Status: {self.status}")

        elif self.status == "Final":
            self.inning = 9
            self.isTopInning = False
            self.outs = 3
            self.strikes = 3

        elif self.status == "Pre-Game" or self.status == "Delayed Start":
            if self.status == "Delayed Start":
                logging.warning(f"Game {self.game_id} has a delayed start. Status: {self.status}")
            self.inning = 1
            self.isTopInning = True
            self.outs = 0
            self.strikes = 0

        else:
            raise Exception(f"Game status {self.status} is not supported.")

        self.pctPlayed = self.calc_pct_played()

    def to_game_state(self) -> GameState:
        """Convert to a GameState for model prediction."""
        on_1b, on_2b, on_3b = runner_index_to_flags(self.runner_index)
        return GameState(
            inning=self.inning,
            is_top_inning=self.isTopInning,
            outs=self.outs,
            on_1b=on_1b,
            on_2b=on_2b,
            on_3b=on_3b,
            score_diff=self.net_score,
            balls=self.balls,
            strikes=self.strikes,
            pitcher_pitch_count=self.pitcher_pitch_count,
            home_sp_k_pct=self.home_sp_k_pct,
            home_sp_bb_pct=self.home_sp_bb_pct,
            away_sp_k_pct=self.away_sp_k_pct,
            away_sp_bb_pct=self.away_sp_bb_pct,
            is_starter=self.is_starter,
            current_pitcher_k_pct=self.current_pitcher_k_pct,
            current_pitcher_bb_pct=self.current_pitcher_bb_pct,
            platoon_adv_batter=self.platoon_adv_batter,
            batting_order_pos=self.batting_order_pos,
            home_run_diff_per_game=self.home_run_diff_per_game,
            away_run_diff_per_game=self.away_run_diff_per_game,
        )

    def get_win_probability(self):
        # Try the trained Statcast model first
        model = get_win_prob_model()
        if model is not None:
            return model.predict(self.to_game_state()) * 100

        # Fall back to the legacy lookup table if the model hasn't been trained yet
        if self.isTopInning:
            homeOrVisitor = 'V'
        else:
            homeOrVisitor = 'H'
        prob = getProbability(homeOrVisitor, self.inning, self.outs, self.runner_index, self.net_score)
        if prob != -1:
            prob = prob * 100
        return prob

    def calc_pct_played(self):
        inning_pct = (self.inning - 1) / 9 + (not self.isTopInning) / (9 * 2)
        out_pct = self.outs / (9 * 2 * 3)
        strike_pct = self.strikes / (9 * 2 * 3 * 3)

        return min(inning_pct + out_pct + strike_pct, 1)

    def set_pregame_state(self):
        """Reset game state to pre-game defaults."""
        self.status = "Pre-Game"
        self.inning = 1
        self.isTopInning = True
        self.outs = 0
        self.balls = 0
        self.strikes = 0
        self.runner_index = 1  # bases empty
        self.home_score = 0
        self.away_score = 0
        self.net_score = 0
        self.winProbability = -1
        self.pctPlayed = 0

    def update_from_play(self, play, start_outs, start_home_score, start_away_score, is_final=False, pitcher_pitch_count=0):
        """Update game state from a completed play (single-fetch mode)."""
        if is_final:
            self.status = "Final"
            self.inning = 9
            self.isTopInning = False
            self.outs = 3
            self.strikes = 3
            self.balls = 0
        else:
            self.status = "In Progress"
            self.inning = play['about']['inning']
            self.isTopInning = play['about']['isTopInning']
            self.outs = start_outs
            self.balls = 0
            self.strikes = 0
            self.pitcher_pitch_count = pitcher_pitch_count
            self.captivating_index = play['about'].get('captivatingIndex', 0)
            self.runner_index = self.get_runner_state(play['runners'])
            self.roll_status()
            self.winProbability = self.get_win_probability()

        self.home_score = start_home_score
        self.away_score = start_away_score
        self.net_score = self.home_score - self.away_score
        self.pctPlayed = self.calc_pct_played()

    def _update_pitcher_pitch_count(self, game_data):
        """Extract current pitcher's pitch count from live boxscore data."""
        try:
            linescore = game_data['liveData']['linescore']
            is_top = linescore.get('isTopInning', True)
            # When top inning: away batting, home pitching
            pitching_side = 'home' if is_top else 'away'
            players = game_data['liveData']['boxscore']['teams'][pitching_side]['players']
            for player_data in players.values():
                if player_data.get('position', {}).get('abbreviation') == 'P':
                    pitching_stats = player_data.get('stats', {}).get('pitching', {})
                    if pitching_stats.get('numberOfPitches') is not None:
                        self.pitcher_pitch_count = int(pitching_stats['numberOfPitches'])
                        return
        except Exception as e:
            logging.warning(f"Could not extract pitcher pitch count: {e}")

    def _update_matchup_features(self, game_data, current_play):
        """Update is_starter, platoon advantage, and batting order position from live data."""
        try:
            linescore = game_data['liveData']['linescore']
            is_top = linescore.get('isTopInning', True)
            pitching_side = 'home' if is_top else 'away'
            batting_side  = 'away' if is_top else 'home'

            # is_starter: check if current pitcher is listed as the starting pitcher
            boxscore = game_data['liveData']['boxscore']['teams']
            pitching_players = boxscore[pitching_side]['players']
            current_pitcher_id = current_play.get('matchup', {}).get('pitcher', {}).get('id')
            for player_data in pitching_players.values():
                pid = player_data.get('person', {}).get('id')
                if pid == current_pitcher_id:
                    pos = player_data.get('position', {}).get('abbreviation', '')
                    game_pos = player_data.get('gameStatus', {}).get('isCurrentBatter', False)
                    # SP = starting pitcher designation
                    all_positions = player_data.get('allPositions', [])
                    self.is_starter = int(any(p.get('abbreviation') == 'SP' for p in all_positions))
                    break

            # Platoon advantage: batter stance vs pitcher hand
            matchup = current_play.get('matchup', {})
            batter_side  = matchup.get('batSide', {}).get('code', 'R')
            pitcher_hand = matchup.get('pitchHand', {}).get('code', 'R')
            self.platoon_adv_batter = int(batter_side != pitcher_hand or batter_side == 'S')

            # Batting order position from boxscore batting order
            batter_id = current_play.get('matchup', {}).get('batter', {}).get('id')
            batters = boxscore[batting_side]['battingOrder']
            if batter_id in batters:
                self.batting_order_pos = batters.index(batter_id) + 1
            else:
                self.batting_order_pos = 5

        except Exception as e:
            logging.warning(f"Could not update matchup features: {e}")

    def load_starter_stats(self, pitcher_stats: dict, run_diff: dict = None):
        """Load starting pitcher quality stats and optional team run differential.

        Args:
            pitcher_stats: {team_abv: {'k_pct': float, 'bb_pct': float}}
            run_diff:      {team_abv: float} — previous-season run diff per game
        """
        home = pitcher_stats.get(self.home_team_abv, {})
        self.home_sp_k_pct  = home.get('k_pct',  LEAGUE_AVG_K_PCT)
        self.home_sp_bb_pct = home.get('bb_pct', LEAGUE_AVG_BB_PCT)

        away = pitcher_stats.get(self.away_team_abv, {})
        self.away_sp_k_pct  = away.get('k_pct',  LEAGUE_AVG_K_PCT)
        self.away_sp_bb_pct = away.get('bb_pct', LEAGUE_AVG_BB_PCT)

        if run_diff:
            self.home_run_diff_per_game = run_diff.get(self.home_team_abv, 0.0)
            self.away_run_diff_per_game = run_diff.get(self.away_team_abv, 0.0)

    def update_pregame_win_probability(self, market, http_client):
        start_unix = date_helpers.game_timestamp_to_unix(self.start_time)
        end_unix = date_helpers.game_timestamp_to_unix(
            date_helpers.add_minutes_to_timestamp(self.start_time, 10)
        )
        candlestick = http_client.get_market_candelstick(
            market.ticker, market.series_ticker, start_unix, end_unix, 1
        )

        if candlestick.get('candlesticks'):
            last = candlestick['candlesticks'][-1]
            bid = last.get('yes_bid', {}).get('close_dollars')
            ask = last.get('yes_ask', {}).get('close_dollars')

            if bid is not None and ask is not None:
                self.pregame_winProbability = (float(bid) + float(ask)) / 2 * 100
                return
            elif bid is not None:
                self.pregame_winProbability = float(bid) * 100 + 2
                return
            elif ask is not None:
                self.pregame_winProbability = float(ask) * 100 - 2
                return

        # Kalshi price unavailable — fall back to statistical estimate
        logging.info(
            f"No Kalshi pregame price for {market.ticker} — "
            "using log5 + home field advantage estimate"
        )
        self.pregame_winProbability = self._estimate_pregame_statistical()

    def _estimate_pregame_statistical(self) -> float:
        """
        Estimate pre-game win probability from previous-season win% + home field advantage.
        Uses log5 formula. Falls back gracefully to 50.0 on any error.
        """
        try:
            season = int(self.game_date[:4])
            home_pct = get_team_win_pct(self.home_team_full, season, game_date=self.game_date)
            away_pct = get_team_win_pct(self.away_team_full, season, game_date=self.game_date)
            prob = estimate_pregame_prob(home_pct, away_pct)
            logging.info(
                f"Statistical pregame estimate: {self.home_team_abv} ({home_pct:.3f}) vs "
                f"{self.away_team_abv} ({away_pct:.3f}) -> {prob:.1f}%"
            )
            return prob
        except Exception as e:
            logging.warning(f"Statistical pregame estimate failed: {e}")
            return 50.0

    def roll_status(self):
        if self.strikes >= 3:
            self.strikes = 0
            self.outs += 1
        if self.outs >= 3:
            self.outs = 0
            if self.isTopInning:
                self.isTopInning = False
            else:
                self.inning += 1
                self.isTopInning = True

    def get_runner_state(self, runners):
        """
        Map the 'runners' field of a play to an integer (1-8) representing the base state.
        runners: list of dicts, each with a 'base' key (e.g., '1B', '2B', '3B')
        Returns:
            int: 1 = bases empty, 2 = 1st, 3 = 2nd, 4 = 1st+2nd, 5 = 3rd, 6 = 1st+3rd, 7 = 2nd+3rd, 8 = loaded
        """
        bases = set(r['movement']['originBase'] for r in runners)
        if None in bases:
            bases.remove(None)
        if bases == set():
            return 1  # bases empty
        elif bases == {'1B'}:
            return 2
        elif bases == {'2B'}:
            return 3
        elif bases == {'1B', '2B'}:
            return 4
        elif bases == {'3B'}:
            return 5
        elif bases == {'1B', '3B'}:
            return 6
        elif bases == {'2B', '3B'}:
            return 7
        elif bases == {'1B', '2B', '3B'}:
            return 8
        else:
            raise ValueError(f"Unknown base state: {bases}")
