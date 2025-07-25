import logging
from abc import ABC, abstractmethod
from typing import Any, Optional
from Baseball.database import BacktestDatabase


class TradingStrategy(ABC):
    _version = "1.0.0"
    _prediction_model_version = "1.0.0"

    def __init__(self):
        self.trade_log = []
        self.prediction_log = []
        self.cash = 100
        self.positions = 0

    @property
    def version(self) -> str:
        return self._version
    
    @property
    def prediction_model_version(self) -> str:
        return self._prediction_model_version


    @abstractmethod
    def calculate_signal(self, mid_price: float, bid_price: float, ask_price: float) -> Any:
        pass


class BacktestStrategy(TradingStrategy):
    def __init__(self, db_path: Optional[str] = None):
        super().__init__()
        self.db = BacktestDatabase(db_path) if db_path else BacktestDatabase()


    def calculate_signal(self, mid_price: float, bid_price: float, ask_price: float) -> Any:
        raise NotImplementedError
    
    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        raise NotImplementedError
    
    def post_process(self, game, save_to_db=True):
        if self.positions != 0:
            logging.warning(f"Settling remaining positions at end of backtest: {self.positions}")
            if game.net_score > 0:
                last_bid = last_ask = 100
            else:
                last_bid = last_ask = 0

            self.close_all_positions(last_bid, last_ask)
        
        if save_to_db:
            logging.info("Saving predictions to database.")
            self.save_predictions_to_db(self.prediction_log, game.net_score > 0)
            
        logging.info(f"Final cash: {self.cash}, Final positions: {self.positions}")
        logging.info("Backtest completed successfully.")

    def buy(self, ask, position_size=1):
        """
        Buy contracts.
        - If net short, buying covers short position (generates cash).
        - If flat or long, buying increases long position (uses cash).
        """
        if self.positions < 0:
            # Cover short position first (generates cash)
            cover_qty = min(position_size, abs(self.positions))
            self.positions += cover_qty
            self.cash += round(cover_qty * (100 - ask) / 100, 2)
            position_size -= cover_qty
            logging.info(f"Covered {cover_qty} existing short contracts. New position: {self.positions}")
        if position_size > 0:
            # Add to long position (uses cash)
            self.positions += position_size
            self.cash -= round(position_size * ask / 100, 2)
            logging.info(f"Bought {position_size} new contracts. New position: {self.positions}")

        self.trade_log.append({
            'action': 'buy',
            'price': ask,
            'position_size': position_size,
            'positions': self.positions,
            'cash': self.cash
        })

    def sell(self, bid, position_size=1):
        """
        Sell contracts.
        - If net long, selling reduces long position (generates cash).
        - If flat or short, selling increases short position (uses cash).
        """
        if self.positions > 0:
            # Sell from long position first (generates cash)
            sell_qty = min(position_size, self.positions)
            self.positions -= sell_qty
            self.cash += round(sell_qty * bid / 100, 2)
            position_size -= sell_qty
            logging.info(f"Sold {sell_qty} existing long contracts. New position: {self.positions}")
        if position_size > 0:
            # Open/increase short position (uses cash)
            self.positions -= position_size
            self.cash -= round(position_size * (100 - bid) / 100, 2)
            logging.info(f"Sold short {position_size} new contracts. New position: {self.positions}")

        self.trade_log.append({
            'action': 'sell',
            'price': bid,
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

    def save_predictions_to_db(self, prediction_log, is_win: bool):
        """Save predictions to SQLite database."""
        if not prediction_log:
            logging.warning("No predictions to save to database")
            return
        
        self.db.save_predictions(
            predictions=prediction_log,
            actual_outcome=is_win,
            prediction_model_version=self.prediction_model_version,
            strategy_version=self.version
        )