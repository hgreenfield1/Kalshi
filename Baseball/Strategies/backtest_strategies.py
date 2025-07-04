import logging
import math
from Baseball.BaseballGame import BaseballGame
from Baseball.TradingStrategy import BacktestStrategy


class SimpleBacktestStrategy(BacktestStrategy):
    def __init__(self):
        super().__init__()
        self.min_positions = -10
        self.max_positions = 10

    def calculate_expected_win_prob(self, game: BaseballGame) -> float:
        alpha_t = 4
        alpha_prob = 8
        t = game.pctPlayed
        P_pre = game.pregame_winProbability
        P_live = game.winProbability

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

    def calculate_signal(self, mid_price: float, bid_price: float, ask_price: float) -> str:
        if mid_price is None:
            logging.warning(f"---- Mid price projection is None. Unable to calculate signal.")
            return

        if bid_price is None or ask_price is None:
            logging.warning(f"---- No bid/ask prices available. Unable to calculate signal.")
            return

        if mid_price < ask_price - 10 and bid_price < 97:
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                return -1

        if mid_price > ask_price + 10 and ask_price > 3:
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                return +1
            
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            logging.info(f"{timestamp}: Calculating Signal -- Mid Price: {mid_price}, Bid Price: {bid_price}, Ask Price: {ask_price}")
            
            signal = self.calculate_signal(mid_price, bid_price, ask_price)

            if signal:
                logging.info(f"-- Signal generated: {signal} positions")
                if signal > 0:
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.sell(bid_price, -signal)

        else:
            signal = None
        
        # Record the prediction
        self.prediction_log.append({
            'game_id': game.game_id,
            'timestamp': timestamp,
            'mid_price': mid_price,
            'bid_price': bid_price,
            'ask_price': ask_price,
            'cash': self.cash,
            'positions': self.positions,
            'signal': signal
        })
