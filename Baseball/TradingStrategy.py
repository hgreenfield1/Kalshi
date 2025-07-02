import logging
import csv
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any


class TradingStrategy(ABC):
    _version = "1.0.0"

    def __init__(self):
        self.trade_log = []
        self.prediction_log = []
        self.cash = 100
        self.positions = 0

    @property
    def version(self) -> str:
        return self._version

    @abstractmethod
    def calculate_expected_win_prob(self) -> float:
        pass

    @abstractmethod
    def calculate_signal(self, mid_price: float, bid_price: float, ask_price: float) -> Any:
        pass


class BacktestStrategy(TradingStrategy):
    def __init__(self):
        super().__init__()

    def calculate_expected_win_prob(self) -> float:
        raise NotImplementedError

    def calculate_signal(self, mid_price: float, bid_price: float, ask_price: float) -> Any:
        raise NotImplementedError
    
    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        raise NotImplementedError
    
    def post_process(self, game, csv=False):
        if csv:
            logging.info("Appending predictions to CSV file.")
            self.append_prediction_to_csv(self.prediction_log, game.net_score > 0)
        if self.positions != 0:
            logging.warning(f"Settling remaining positions at end of backtest: {self.positions}")
            if game.net_score > 0:
                last_bid = last_ask = 100
            else:
                last_bid = last_ask = 0

            self.close_all_positions(last_bid, last_ask)

        logging.info(f"Final cash: {self.cash}, Final positions: {self.positions}")
        logging.info("Backtest completed successfully.")

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

        self.trade_log.append({
            'action': 'buy',
            'price': price,
            'position_size': position_size,
            'positions': self.positions,
            'cash': self.cash
        })

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

        self.trade_log.append({
            'action': 'sell',
            'price': price,
            'position_size': position_size,
            'positions': self.positions,
            'cash': self.cash
        })

    def close_all_positions(self, bid, ask):
        if self.positions > 0:
            self.sell(bid, self.positions)
        if self.positions < 0:
            self.buy(ask, -self.positions)
        logging.info(f"Closed all positions: Cash={self.cash}, Positions={self.positions}")

    def append_prediction_to_csv(self, prediction_log, is_win):
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
                    entry['signal'],
                    is_win
                ])