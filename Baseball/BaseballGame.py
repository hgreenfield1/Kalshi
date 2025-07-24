import statsapi
import logging
from datetime import datetime
from Infrastructure.market import Market
from Baseball.lookup import mlb_teams
from Baseball.win_calculator import getProbability
import Baseball.date_helpers as date_helpers

# statsapi.get('game', {'gamePk': 565997})
# statsapi.get('game_timestamps', {'gamePk': 565997})
# statsapi.get('game_winProbability', {'gamePk': 565997})
# statsapi.get('game_contextMetrics', {'gamePk': 565997})
# sportID = 1
# statsapi.get('teams')
# statsapi.get('schedule', {'sportId': 1, 'gamePk': 777735})
# markets = http_client.get_markets(['KXMLBGAME'])


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

    def update_status(self, timestamp=None):
        if not timestamp:
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

    def get_win_probability(self):
        #win_prob = statsapi.get('game_winProbability', {'gamePk': self.game_id})
        #win_prob[-1]['homeTeamWinProbability']
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

    def update_pregame_win_probability(self, market, http_client):
        start_time = self.start_time
        end_time = date_helpers.add_min_to_utc_timestamp(self.start_time, 10)  # Get pregame data for the hour before the game starts        
        candlestick = http_client.get_market_candelstick(market.ticker, market.series_ticker, start_time, end_time, 1)

        if len(candlestick['candlesticks']) == 0:
            raise Exception("No pregame candlestick data available for this game.")
        else:
            if candlestick['candlesticks'][-1]['price']['mean'] is not None:
                self.pregame_winProbability = candlestick['candlesticks'][-1]['price']['mean']
            else:
                if candlestick['candlesticks'][-1]['yes_bid']['close'] is not None and candlestick['candlesticks'][-1]['yes_ask']['close'] is not None:
                    self.pregame_winProbability = (candlestick['candlesticks'][-1]['yes_bid']['close'] + candlestick['candlesticks'][-1]['yes_ask']['close']) / 2
                elif candlestick['candlesticks'][-1]['yes_bid']['close'] is not None:
                    self.pregame_winProbability = candlestick['candlesticks'][-1]['yes_bid']['close'] + 2
                elif candlestick['candlesticks'][-1]['yes_bid']['close'] is not None:
                    self.pregame_winProbability = candlestick['candlesticks'][-1]['yes_ask']['close'] - 2
                else:
                    Exception("Pregame win probability is unavailable.")

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
        