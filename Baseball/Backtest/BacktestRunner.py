import logging
import Baseball.date_helpers as date_helpers
from Baseball.Strategies.backtest_strategies import BacktestStrategy



class BacktestRunner:
    def __init__(self, game, market, http_client, strategy: BacktestStrategy):
        self.game = game
        self.market = market
        self.http_client = http_client
        self.strategy = strategy
        
        self.prices = {}

    def run(self, timestamps):
        logging.info(f"Starting backtest for game: {self.game.home_team_abv} vs {self.game.away_team_abv}")

        self.prices = self.get_market_prices(timestamps)
        
        for timestamp in timestamps:
            logging.debug(f"Running strategy for timestamp: {timestamp}")
            
            # Update game
            self.game.update_status(timestamp)

            
            if self.game.status == "In Progress":
                if self.game.pregame_winProbability == -1:
                    self.game.update_pregame_win_probability(self.market, self.http_client)
                    if self.game.pregame_winProbability == -1:
                        logging.error(f"Unable to get pre-game win probability for {self.game.away_team_abv} @ {self.game.home_team_abv}")
                    
                self.execute_strategy(timestamp)

            elif self.game.status == "Pre-Game":
                logging.info(f"{timestamp}: Game not started yet for {self.game.away_team_abv} @ {self.game.home_team_abv}. Waiting for start time.")
            elif self.game.status == "Final":
                logging.info(f"{timestamp}: Game complete for {self.game.away_team_abv} @ {self.game.home_team_abv}")
                self.strategy.post_process(self.game, csv=True)
                break
            

    
    def get_market_prices(self, timestamps):
        # Get 60s candlesticks
        candlesticks = self.http_client.get_market_candelstick(self.market.ticker, self.market.series_ticker, timestamps[0], timestamps[-1], 1)
        
        # Map timestamps to bid/ask prices
        prices = {}
        candle_map = {date_helpers.unix_to_utc_timestamp(candle['end_period_ts']): candle for candle in candlesticks['candlesticks']}
        for timestamp in timestamps:
            timestamp = date_helpers.round_to_next_minute(timestamp)
            if timestamp in candle_map:
                candle = candle_map[timestamp]
                prices[timestamp] = {
                    'bid': candle['yes_bid']['close'] if candle['yes_bid']['close'] is not None else None,
                    'ask': candle['yes_ask']['close'] if candle['yes_ask']['close'] is not None else None
                }
            else:
                prices[timestamp] = {'bid': None, 'ask': None}
        
        return prices
    
    def execute_strategy(self, timestamp):
        timestamp_rounded = date_helpers.round_to_next_minute(timestamp)
        bid_price = self.prices[timestamp_rounded]['bid']
        ask_price = self.prices[timestamp_rounded]['ask']
        self.strategy.trade(timestamp, self.game, bid_price, ask_price)

