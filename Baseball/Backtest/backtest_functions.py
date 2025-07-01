import logging
import math
import pandas as pd
import csv
from pathlib import Path
from datetime import datetime, timedelta, timezone


def get_backtest_timestamps(start_time_str, end_time_str):
    """
    Returns a list of 60-second (1 minute) increments between start_time and end_time (inclusive),
    formatted as UTC ISO 8601 strings (e.g., '2025-06-13T19:15:54Z').
    Input timestamps are in the format 'yyyymmdd_hhmmss'.
    """
    fmt_in = "%Y%m%d_%H%M%S"
    fmt_out = "%Y-%m-%dT%H:%M:%SZ"
    start_dt = datetime.strptime(start_time_str, fmt_in)
    end_dt = datetime.strptime(end_time_str, fmt_in)
    increments = []
    current = start_dt
    while current < end_dt:
        increments.append(current.strftime(fmt_out))
        current += timedelta(seconds=60)
    increments.append(end_dt.strftime(fmt_out))
    return increments


def append_prediction_to_csv(prediction_log, is_win):
    CSV_PATH = Path("probability_predictions.csv")
    file_exists = CSV_PATH.exists()

    with open(CSV_PATH, mode='a', newline='') as file:
        writer = csv.writer(file)
        
        # Write header if file doesn't exist
        if not file_exists:
            writer.writerow(["game_id", "timestamp", "team", "predicted_prob", "actual_outcome"])
        
        for entry in prediction_log:
            writer.writerow([
                entry['game_id'],
                entry['timestamp'],
                entry['mid_price'],
                entry['bid_price'],
                entry['ask_price'],
                entry['cash'],
                entry['positions'],
                is_win
            ])


class BacktestStrategy:
    def __init__(self, game, market, http_client):
        self.game = game
        self.market = market
        self.http_client = http_client

        # Parameters
        self.min_positions = -5
        self.max_positions = 5
        
        self.cash = 100
        self.positions = 0
        self.prices = {}
        self.prediction_log = []

    def run(self, timestamps):
        logging.info(f"Starting backtest for game: {self.game.home_team_abv} vs {self.game.away_team_abv}")

        self.prices = self.get_market_prices(timestamps)
        
        for timestamp in timestamps:
            logging.info(f"Running strategy for timestamp: {timestamp}")
            
            # Update game
            self.game.update_status(timestamp)

            
            if self.game.status == "In Progress":
                if self.game.pregame_winProbability == -1:
                    self.game.update_pregame_win_probability(self.market, self.http_client)
                    if self.game.pregame_winProbability == -1:
                        logging.error(f"Unable to get pre-game win probability for {self.game.away_team_abv} @ {self.game.home_team_abv}")
                    
                self.trade(timestamp)

            elif self.game.status == "Pre-Game":
                logging.info(f"Game not started yet for {self.game.away_team_abv} @ {self.game.home_team_abv}. Waiting for start time.")
            elif self.game.status == "Final":
                logging.info(f"Game complete for {self.game.away_team_abv} @ {self.game.home_team_abv}")
                self.post_process(csv=True)
                break
            

    
    def get_market_prices(self, timestamps):
        # Get 60s candlesticks
        candlesticks = self.http_client.get_market_candelstick(self.market.ticker, self.market.series_ticker, timestamps[0], timestamps[-1], 1)
        
        # Map timestamps to bid/ask prices
        prices = {}
        candle_map = {BacktestStrategy.unix_to_utc_timestamp(candle['end_period_ts']): candle for candle in candlesticks['candlesticks']}
        for timestamp in timestamps:
            timestamp = BacktestStrategy.round_to_next_minute(timestamp)
            if timestamp in candle_map:
                candle = candle_map[timestamp]
                prices[timestamp] = {
                    'bid': candle['yes_bid']['close'] if candle['yes_bid']['close'] is not None else None,
                    'ask': candle['yes_ask']['close'] if candle['yes_ask']['close'] is not None else None
                }
            else:
                prices[timestamp] = {'bid': None, 'ask': None}
        
        return prices

    @staticmethod
    def unix_to_utc_timestamp(unix_timestamp):
        """
        Converts a Unix timestamp to a UTC timestamp string in the format 'yyyymmdd_hhmmss'.
        """
        dt_utc = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    

    @staticmethod
    def round_to_next_minute(ts):
        """
        Takes a timestamp string in the format 'yyyymmdd_hhmmss' and rounds it up to the next number of seconds divisible by 60.
        Returns the rounded timestamp string in the same format.
        """
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        dt = datetime.strptime(ts, fmt)
        if dt.second != 0:
            dt += timedelta(seconds=(60 - dt.second))
            dt = dt.replace(second=0)
        return dt.strftime(fmt)

    def trade(self, timestamp):
        mid_price = self.get_mid_price_projection()
        timestamp_rounded = self.round_to_next_minute(timestamp)
        bid_price = self.prices[timestamp_rounded]['bid']
        ask_price = self.prices[timestamp_rounded]['ask']

        if mid_price is None:
            logging.warning(f"Mid price projection is None for timestamp {timestamp}. Skipping trade.")
            return

        if bid_price is None or ask_price is None:
            logging.warning(f"No bid/ask prices available for timestamp {timestamp}. Skipping trade.")
            return

        if mid_price < ask_price - 10 and bid_price < 97:
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                self.sell(bid_price)

        if mid_price > ask_price + 10 and ask_price > 3:
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                self.buy(ask_price)

        self.prediction_log.append({
            'game_id': self.game.game_id,
            'timestamp': timestamp,
            'mid_price': mid_price,
            'bid_price': bid_price,
            'ask_price': ask_price,
            'cash': self.cash,
            'positions': self.positions
        })

        pass


    def get_mid_price_projection(self):
        alpha_t = 4
        alpha_prob = 8
        t = self.game.pctPlayed
        P_pre = self.game.pregame_winProbability
        P_live = self.game.winProbability

        if P_live == -1:
            logging.warning("Live win probability is not available.")
            return None

        # Standard exponential decay weight
        base_weight = math.exp(-alpha_t * t)
        # Confidence factor: 0 at 0.5, 1 at 0 or 1 (scales up live weight as it moves away from 0.5)
        confidence = 1 - math.exp(-alpha_prob * abs(P_live - 50)/100)
        # Adjusted live weight
        live_weight = (1 - base_weight) * confidence
        # Adjusted pre-game weight
        pre_weight = 1 - live_weight

        # Normalize weights to sum to 1 (optional, but recommended)
        total = pre_weight + live_weight
        pre_weight /= total
        live_weight /= total

        return round(pre_weight * P_pre + live_weight * P_live, 2)
    
    def buy(self, price, position_size=1):
        """
        Buy contracts.
        - If net short, buying covers short position (generates cash).
        - If flat or long, buying increases long position (uses cash).
        """
        if self.positions < 0:
            # Cover short position first (generates cash)
            cover_qty = min(position_size, abs(self.positions))
            self.positions += cover_qty
            self.cash += cover_qty * (100 - price) / 100
            position_size -= cover_qty
            logging.info(f"Covered {cover_qty} existing short contracts. New position: {self.positions}")
        if position_size > 0:
            # Add to long position (uses cash)
            self.positions += position_size
            self.cash -= position_size * price / 100
            logging.info(f"Bought {position_size} new contracts. New position: {self.positions}")

    def sell(self, price, position_size=1):
        """
        Sell contracts.
        - If net long, selling reduces long position (generates cash).
        - If flat or short, selling increases short position (uses cash).
        """
        if self.positions > 0:
            # Sell from long position first (generates cash)
            sell_qty = min(position_size, self.positions)
            self.positions -= sell_qty
            self.cash += sell_qty * price / 100
            position_size -= sell_qty
            logging.info(f"Sold {sell_qty} existing long contracts. New position: {self.positions}")
        if position_size > 0:
            # Open/increase short position (uses cash)
            self.positions -= position_size
            self.cash -= position_size * price / 100
            logging.info(f"Sold short {position_size} new contracts. New position: {self.positions}")

    def close_all_positions(self, bid, ask):
        if self.positions > 0:
            self.sell(bid, self.positions)
        if self.positions < 0:
            self.buy(ask, -self.positions)
        logging.info(f"Closed all positions: Cash={self.cash}, Positions={self.positions}")


    def post_process(self, csv=False):
        if csv:
            logging.info("Appending predictions to CSV file.")
            append_prediction_to_csv(self.prediction_log, self.game.net_score > 0)
        if self.positions != 0:
            logging.warning(f"Settling remaining positions at end of backtest: {self.positions}")
            if self.game.net_score > 0:
                last_bid = last_ask = 100
            else:
                last_bid = last_ask = 0

            self.close_all_positions(last_bid, last_ask)

        logging.info(f"Final cash: {self.cash}, Final positions: {self.positions}")
        logging.info("Backtest completed successfully.")