import statsapi
from datetime import datetime
from Infrastructure.market import Market
from Baseball.lookup import mlb_teams
from Baseball.win_calculator import getProbability

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
    team2 = team2.replace("G2", "", 1) 

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

    def update_status(self):
        info = statsapi.schedule(game_id=self.game_id)
        self.status = info[0]['status']
        self.home_score = info[0]['home_score']
        self.away_score = info[0]['away_score']
        self.net_score = self.home_score - self.away_score

        if self.status == "In Progress":
            self.winProbability = self.get_win_probability()

            game_data = statsapi.get('game', {'gamePk': self.game_id})
            current_play = game_data['liveData']['plays']['currentPlay']
            self.inning = current_play['about']['inning']
            self.isTopInning = True if current_play['about']['halfInning'] == "top" else False
            self.outs = current_play['count']['outs']
            self.balls = current_play['count']['balls']
            self.strikes = current_play['count']['strikes']
            self.runner_index = current_play['runnerIndex']
            self.captivating_index = current_play['about']['captivatingIndex']

        elif self.status == "Final":
            self.inning = 9
            self.isTopInning = False
            self.outs = 3
            self.strikes = 3

        self.pctPlayed = self.calc_pct_played()

    def get_win_probability(self):
        #win_prob = statsapi.get('game_winProbability', {'gamePk': self.game_id})
        #win_prob[-1]['homeTeamWinProbability']
        if self.runner_index == [0]:
            runners = 1
        elif self.runner_index == [0, 1]:
            runners = 2
        elif self.runner_index == [0, 2]:
            runners = 3
        elif self.runner_index == [0, 1, 2]:
            runners = 4
        elif self.runner_index == [0, 3]:
            runners = 5
        elif self.runner_index == [0, 1, 3]:
            runners = 6
        elif self.runner_index == [0, 2, 3]:
            runners = 7
        elif self.runner_index == [0, 1, 2, 3]:
            runners = 8
        else:
            raise Exception("Invalid runner index")

        if self.isTopInning:
            homeOrVisitor = 'V'
        else:
            homeOrVisitor = 'H'

        return getProbability(homeOrVisitor, self.inning, self.outs, runners, self.net_score)

    def calc_pct_played(self):
        inning_pct = self.inning / 9 + (not self.isTopInning) / (9 * 2)
        out_pct = self.outs / (9 * 2 * 3)
        strike_pct = self.strikes / (9 * 2 * 3 * 3)

        return min(inning_pct + out_pct + strike_pct, 1)

    def update_pregame_win_probability(self, market, http_client):
        candlestick = http_client.get_market_candelstick(market.ticker, market.series_ticker, self.start_time, self.start_time, 1)
        if candlestick['candlesticks'][0]['price']['mean'] is not None:
            self.pregame_winProbability = candlestick['candlesticks'][0]['price']['mean']
        else:
            if candlestick['candlesticks'][0]['yes_bid']['close'] is not None:
                self.pregame_winProbability = candlestick['candlesticks'][0]['yes_bid']['close']
            else:
                Exception("Pregame win probability is unavailable.")
