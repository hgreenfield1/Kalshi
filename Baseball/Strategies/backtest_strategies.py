import logging
from collections import deque
from Baseball.BaseballGame import BaseballGame
from Baseball.TradingStrategy import BacktestStrategy
from Baseball.date_helpers import minutes_between_timestamps, add_minutes_to_timestamp
from Baseball.PredictionModel import AlphaDecayPredictionModel, get_prediction_model_by_version


class SimpleBacktestStrategy(BacktestStrategy):
    _version = "1.1.0"
    _prediction_model_version = "1.1.0"
    
    def __init__(self, db_path=None, prediction_model=None):
        super().__init__(db_path)
        self.min_positions = -10
        self.max_positions = 10
        self.last_buy_ts = None
        self.last_sell_ts = None
        self.trade_cooldown = 10
        self.prediction_model = prediction_model or get_prediction_model_by_version(self._prediction_model_version)


    def calculate_signal(self, timestamp, mid_price: float, bid_price: float, ask_price: float) -> str:
        if mid_price is None:
            logging.warning(f"---- Mid price projection is None. Unable to calculate signal.")
            return

        if bid_price is None or ask_price is None:
            logging.warning(f"---- No bid/ask prices available. Unable to calculate signal.")
            return

        if mid_price < bid_price - 15 and bid_price < 85:
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                if self.last_sell_ts is None:
                    return -1
                else:
                    time_dif = minutes_between_timestamps(self.last_sell_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return -1

        if mid_price > ask_price + 15 and ask_price > 15:
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                if self.last_buy_ts is None:
                    return 1
                else:
                    time_dif = minutes_between_timestamps(self.last_buy_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return 1
            
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            logging.info(f"{timestamp}: Calculating Signal -- Mid Price: {mid_price}, Bid Price: {bid_price}, Ask Price: {ask_price}")
            
            signal = self.calculate_signal(timestamp, mid_price, bid_price, ask_price)

            if signal:
                logging.info(f"-- Signal generated: {signal} positions")
                if signal > 0:
                    self.last_buy_ts = timestamp
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.last_sell_ts = timestamp
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


class ChangeInValueStrategy(BacktestStrategy):
    """Trades based on divergence between model prediction changes and market price changes."""
    _version = "5.0.0"
    _prediction_model_version = "1.1.0"
    
    def __init__(self, db_path=None, prediction_model=None, history_minutes=10):
        super().__init__(db_path)
        self.min_positions = -10
        self.max_positions = 10
        self.last_buy_ts = None
        self.last_sell_ts = None
        self.trade_cooldown = 5
        self.prediction_model = prediction_model or get_prediction_model_by_version(self._prediction_model_version)
        
        # History tracking
        self.history_minutes = history_minutes
        self.value_history = deque(maxlen=1000)
        self.min_change_threshold = 5  # Minimum change to trigger signal
        self.divergence_multiplier = 2.0  # How much model change must exceed market change
        
    def update_history(self, timestamp, predicted_price, market_mid):
        """Update value history with current data."""
        self.value_history.append({
            'timestamp': timestamp,
            'predicted_price': predicted_price,
            'market_mid': market_mid
        })
    
    def calculate_change_signal(self, timestamp, current_predicted, current_market):
        """Calculate if model change significantly exceeds market change."""
        if len(self.value_history) < 2:
            return 0
            
        # Find data from n minutes ago
        cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
        historical_data = [h for h in self.value_history if h['timestamp'] >= cutoff_time]
        
        if len(historical_data) < 2:
            return 0
            
        # Get oldest data point in window
        oldest = historical_data[0]
        
        # Calculate changes
        model_change = current_predicted - oldest['predicted_price']
        market_change = current_market - oldest['market_mid']
        
        # Check if changes are significant enough
        if abs(model_change) < self.min_change_threshold:
            return 0
            
        # Model predicts much larger positive change than market moved - buy
        if model_change > 0 and model_change > abs(market_change) * self.divergence_multiplier:
            return 1
            
        # Model predicts much larger negative change than market moved - sell
        if model_change < 0 and abs(model_change) > abs(market_change) * self.divergence_multiplier:
            return -1
            
        return 0

    def calculate_signal(self, timestamp, mid_price: float, bid_price: float, ask_price: float) -> int:
        if mid_price is None or bid_price is None or ask_price is None:
            logging.warning("---- Missing price data. Unable to calculate signal.")
            return 0
            
        market_mid = (bid_price + ask_price) / 2
        
        # Update history
        self.update_history(timestamp, mid_price, market_mid)
        
        # Calculate change-based signal
        change_signal = self.calculate_change_signal(timestamp, mid_price, market_mid)
        
        if change_signal == 0:
            return 0
            
        # Apply position and cash constraints
        if change_signal < 0:  # Sell signal
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                if self.last_sell_ts is None:
                    return -1
                else:
                    time_dif = minutes_between_timestamps(self.last_sell_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return -1
                        
        elif change_signal > 0:  # Buy signal
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                if self.last_buy_ts is None:
                    return 1
                else:
                    time_dif = minutes_between_timestamps(self.last_buy_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return 1
                        
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            market_mid = (bid_price + ask_price) / 2
            logging.info(f"{timestamp}: ChangeInValue Strategy -- Predicted: {mid_price}, Market Mid: {market_mid}, Bid: {bid_price}, Ask: {ask_price}")
            
            signal = self.calculate_signal(timestamp, mid_price, bid_price, ask_price)

            if signal != 0:
                # Log the change details
                if len(self.value_history) >= 2:
                    cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
                    historical_data = [h for h in self.value_history if h['timestamp'] >= cutoff_time]
                    if historical_data:
                        oldest = historical_data[0]
                        model_change = mid_price - oldest['predicted_price']
                        market_change = market_mid - oldest['market_mid']
                        logging.info(f"-- Value divergence: Model change: {model_change:.1f}, Market change: {market_change:.1f}")
                
                logging.info(f"-- ChangeInValue signal generated: {signal} positions")
                if signal > 0:
                    self.last_buy_ts = timestamp
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.last_sell_ts = timestamp
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


class ConservativeBacktestStrategy(BacktestStrategy):
    """A more conservative trading strategy with higher thresholds and smaller position sizes."""
    _version = "2.0.0"
    _prediction_model_version = "1.1.0"
    
    def __init__(self, db_path=None, prediction_model=None):
        super().__init__(db_path)
        self.min_positions = -5  # Smaller position limits
        self.max_positions = 5
        self.last_buy_ts = None
        self.last_sell_ts = None
        self.trade_cooldown = 15  # Longer cooldown between trades
        self.prediction_model = prediction_model or get_prediction_model_by_version(self._prediction_model_version)
        self.min_edge_threshold = 20  # Higher edge threshold for trades

    def calculate_signal(self, timestamp, mid_price: float, bid_price: float, ask_price: float) -> str:
        if mid_price is None:
            logging.warning(f"---- Mid price projection is None. Unable to calculate signal.")
            return

        if bid_price is None or ask_price is None:
            logging.warning(f"---- No bid/ask prices available. Unable to calculate signal.")
            return

        # More conservative thresholds - require higher edge and avoid extreme prices
        if mid_price < bid_price - self.min_edge_threshold and bid_price < 80 and bid_price > 20:
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                if self.last_sell_ts is None:
                    return -1
                else:
                    time_dif = minutes_between_timestamps(self.last_sell_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return -1

        if mid_price > ask_price + self.min_edge_threshold and ask_price > 20 and ask_price < 80:
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                if self.last_buy_ts is None:
                    return 1
                else:
                    time_dif = minutes_between_timestamps(self.last_buy_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return 1
            
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            logging.info(f"{timestamp}: Conservative Strategy -- Mid Price: {mid_price}, Bid Price: {bid_price}, Ask Price: {ask_price}")
            
            signal = self.calculate_signal(timestamp, mid_price, bid_price, ask_price)

            if signal:
                logging.info(f"-- Conservative signal generated: {signal} positions")
                if signal > 0:
                    self.last_buy_ts = timestamp
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.last_sell_ts = timestamp
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


class ChangeInValueStrategy(BacktestStrategy):
    """Trades based on divergence between model prediction changes and market price changes."""
    _version = "5.0.0"
    _prediction_model_version = "1.1.0"
    
    def __init__(self, db_path=None, prediction_model=None, history_minutes=10):
        super().__init__(db_path)
        self.min_positions = -10
        self.max_positions = 10
        self.last_buy_ts = None
        self.last_sell_ts = None
        self.trade_cooldown = 5
        self.prediction_model = prediction_model or get_prediction_model_by_version(self._prediction_model_version)
        
        # History tracking
        self.history_minutes = history_minutes
        self.value_history = deque(maxlen=1000)
        self.min_change_threshold = 5  # Minimum change to trigger signal
        self.divergence_multiplier = 2.0  # How much model change must exceed market change
        
    def update_history(self, timestamp, predicted_price, market_mid):
        """Update value history with current data."""
        self.value_history.append({
            'timestamp': timestamp,
            'predicted_price': predicted_price,
            'market_mid': market_mid
        })
    
    def calculate_change_signal(self, timestamp, current_predicted, current_market):
        """Calculate if model change significantly exceeds market change."""
        if len(self.value_history) < 2:
            return 0
            
        # Find data from n minutes ago
        cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
        historical_data = [h for h in self.value_history if h['timestamp'] >= cutoff_time]
        
        if len(historical_data) < 2:
            return 0
            
        # Get oldest data point in window
        oldest = historical_data[0]
        
        # Calculate changes
        model_change = current_predicted - oldest['predicted_price']
        market_change = current_market - oldest['market_mid']
        
        # Check if changes are significant enough
        if abs(model_change) < self.min_change_threshold:
            return 0
            
        # Model predicts much larger positive change than market moved - buy
        if model_change > 0 and model_change > abs(market_change) * self.divergence_multiplier:
            return 1
            
        # Model predicts much larger negative change than market moved - sell
        if model_change < 0 and abs(model_change) > abs(market_change) * self.divergence_multiplier:
            return -1
            
        return 0

    def calculate_signal(self, timestamp, mid_price: float, bid_price: float, ask_price: float) -> int:
        if mid_price is None or bid_price is None or ask_price is None:
            logging.warning("---- Missing price data. Unable to calculate signal.")
            return 0
            
        market_mid = (bid_price + ask_price) / 2
        
        # Update history
        self.update_history(timestamp, mid_price, market_mid)
        
        # Calculate change-based signal
        change_signal = self.calculate_change_signal(timestamp, mid_price, market_mid)
        
        if change_signal == 0:
            return 0
            
        # Apply position and cash constraints
        if change_signal < 0:  # Sell signal
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                if self.last_sell_ts is None:
                    return -1
                else:
                    time_dif = minutes_between_timestamps(self.last_sell_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return -1
                        
        elif change_signal > 0:  # Buy signal
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                if self.last_buy_ts is None:
                    return 1
                else:
                    time_dif = minutes_between_timestamps(self.last_buy_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return 1
                        
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            market_mid = (bid_price + ask_price) / 2
            logging.info(f"{timestamp}: ChangeInValue Strategy -- Predicted: {mid_price}, Market Mid: {market_mid}, Bid: {bid_price}, Ask: {ask_price}")
            
            signal = self.calculate_signal(timestamp, mid_price, bid_price, ask_price)

            if signal != 0:
                # Log the change details
                if len(self.value_history) >= 2:
                    cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
                    historical_data = [h for h in self.value_history if h['timestamp'] >= cutoff_time]
                    if historical_data:
                        oldest = historical_data[0]
                        model_change = mid_price - oldest['predicted_price']
                        market_change = market_mid - oldest['market_mid']
                        logging.info(f"-- Value divergence: Model change: {model_change:.1f}, Market change: {market_change:.1f}")
                
                logging.info(f"-- ChangeInValue signal generated: {signal} positions")
                if signal > 0:
                    self.last_buy_ts = timestamp
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.last_sell_ts = timestamp
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


class AggressiveValueStrategy(BacktestStrategy):
    """A very aggressive value-focused trading strategy with high position limits and frequent trading."""
    _version = "3.0.0"
    _prediction_model_version = "1.1.0"
    
    def __init__(self, db_path=None, prediction_model=None):
        super().__init__(db_path)
        self.min_positions = -20  # Much larger position limits
        self.max_positions = 20
        self.last_buy_ts = None
        self.last_sell_ts = None
        self.trade_cooldown = 5  # 5 minute cooldown between trades
        self.prediction_model = prediction_model or get_prediction_model_by_version(self._prediction_model_version)
        self.min_edge_threshold = 5  # Very low edge threshold for maximum trading
        self.position_scaling = True  # Scale position size based on edge

    def calculate_signal(self, timestamp, mid_price: float, bid_price: float, ask_price: float) -> int:
        if mid_price is None:
            logging.warning(f"---- Mid price projection is None. Unable to calculate signal.")
            return 0

        if bid_price is None or ask_price is None:
            logging.warning(f"---- No bid/ask prices available. Unable to calculate signal.")
            return 0

        # Calculate edge size for position scaling
        sell_edge = bid_price - mid_price if mid_price < bid_price else 0
        buy_edge = mid_price - ask_price if mid_price > ask_price else 0
        
        # Sell signal (short)
        if sell_edge >= self.min_edge_threshold and bid_price < 90:
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                if self.last_sell_ts is None:
                    # Scale position size based on edge (1-3 contracts)
                    position_size = min(3, max(1, int(sell_edge / 10))) if self.position_scaling else 1
                    return -position_size
                else:
                    time_dif = minutes_between_timestamps(self.last_sell_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        position_size = min(3, max(1, int(sell_edge / 10))) if self.position_scaling else 1
                        return -position_size

        # Buy signal (long)
        if buy_edge >= self.min_edge_threshold and ask_price > 10:
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                if self.last_buy_ts is None:
                    # Scale position size based on edge (1-3 contracts)
                    position_size = min(3, max(1, int(buy_edge / 10))) if self.position_scaling else 1
                    return position_size
                else:
                    time_dif = minutes_between_timestamps(self.last_buy_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        position_size = min(3, max(1, int(buy_edge / 10))) if self.position_scaling else 1
                        return position_size
            
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            logging.info(f"{timestamp}: AggressiveValue Strategy -- Mid Price: {mid_price}, Bid Price: {bid_price}, Ask Price: {ask_price}")
            
            signal = self.calculate_signal(timestamp, mid_price, bid_price, ask_price)

            if signal != 0:
                logging.info(f"-- AggressiveValue signal generated: {signal} positions")
                if signal > 0:
                    self.last_buy_ts = timestamp
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.last_sell_ts = timestamp
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


class ReverseSteamStrategy(BacktestStrategy):
    """A mean reversion strategy that trades against price movements that exceed prediction changes."""
    _version = "4.0.0"
    _prediction_model_version = "1.1.0"
    
    def __init__(self, db_path=None, prediction_model=None, history_minutes=10):
        super().__init__(db_path)
        self.min_positions = -10
        self.max_positions = 10
        self.last_buy_ts = None
        self.last_sell_ts = None
        self.trade_cooldown = 5
        self.prediction_model = prediction_model or get_prediction_model_by_version(self._prediction_model_version)
        
        # History tracking
        self.history_minutes = history_minutes
        self.price_history = deque(maxlen=1000)  # Store price and prediction data
        self.min_steam_threshold = 10  # Minimum price movement to trigger signal
        self.reversion_multiplier = 1.5  # How much price must exceed prediction movement
        
    def update_history(self, timestamp, mid_price, market_mid):
        """Update price history with current data."""
        self.price_history.append({
            'timestamp': timestamp,
            'predicted_price': mid_price,
            'market_mid': market_mid
        })
    
    def calculate_steam_signal(self, timestamp, current_predicted, current_market):
        """Calculate if price moved more than prediction suggests (steam)."""
        if len(self.price_history) < 2:
            return 0
            
        # Find data from n minutes ago using proper timestamp comparison
        cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
        historical_data = [h for h in self.price_history if h['timestamp'] >= cutoff_time]
        
        if len(historical_data) < 2:
            return 0
            
        # Get oldest data point in window
        oldest = historical_data[0]
        
        # Calculate changes
        predicted_change = current_predicted - oldest['predicted_price']
        market_change = current_market - oldest['market_mid']
        
        # Check if market moved significantly more than predicted
        if abs(market_change) < self.min_steam_threshold:
            return 0
            
        # Market steamed up more than prediction suggests - bet on reversion down
        if market_change > 0 and market_change > predicted_change * self.reversion_multiplier:
            return -1  # Sell signal
            
        # Market steamed down more than prediction suggests - bet on reversion up  
        if market_change < 0 and abs(market_change) > abs(predicted_change) * self.reversion_multiplier:
            return 1  # Buy signal
            
        return 0

    def calculate_signal(self, timestamp, mid_price: float, bid_price: float, ask_price: float) -> int:
        if mid_price is None or bid_price is None or ask_price is None:
            logging.warning("---- Missing price data. Unable to calculate signal.")
            return 0
            
        market_mid = (bid_price + ask_price) / 2
        
        # Update history
        self.update_history(timestamp, mid_price, market_mid)
        
        # Calculate steam/reversion signal
        steam_signal = self.calculate_steam_signal(timestamp, mid_price, market_mid)
        
        if steam_signal == 0:
            return 0
            
        # Apply position and cash constraints
        if steam_signal < 0:  # Sell signal
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                if self.last_sell_ts is None:
                    return -1
                else:
                    time_dif = minutes_between_timestamps(self.last_sell_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return -1
                        
        elif steam_signal > 0:  # Buy signal
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                if self.last_buy_ts is None:
                    return 1
                else:
                    time_dif = minutes_between_timestamps(self.last_buy_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return 1
                        
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            market_mid = (bid_price + ask_price) / 2
            logging.info(f"{timestamp}: ReverseSteam Strategy -- Predicted: {mid_price}, Market Mid: {market_mid}, Bid: {bid_price}, Ask: {ask_price}")
            
            signal = self.calculate_signal(timestamp, mid_price, bid_price, ask_price)

            if signal != 0:
                # Log the steam details
                if len(self.price_history) >= 2:
                    cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
                    historical_data = [h for h in self.price_history if h['timestamp'] >= cutoff_time]
                    if historical_data:
                        oldest = historical_data[0]
                        pred_change = mid_price - oldest['predicted_price']
                        market_change = market_mid - oldest['market_mid']
                        logging.info(f"-- Steam detected: Market change: {market_change:.1f}, Predicted change: {pred_change:.1f}")
                
                logging.info(f"-- ReverseSteam signal generated: {signal} positions")
                if signal > 0:
                    self.last_buy_ts = timestamp
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.last_sell_ts = timestamp
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


class ChangeInValueStrategy(BacktestStrategy):
    """Trades based on divergence between model prediction changes and market price changes."""
    _version = "5.0.0"
    _prediction_model_version = "1.1.0"
    
    def __init__(self, db_path=None, prediction_model=None, history_minutes=10):
        super().__init__(db_path)
        self.min_positions = -10
        self.max_positions = 10
        self.last_buy_ts = None
        self.last_sell_ts = None
        self.trade_cooldown = 5
        self.prediction_model = prediction_model or get_prediction_model_by_version(self._prediction_model_version)
        
        # History tracking
        self.history_minutes = history_minutes
        self.value_history = deque(maxlen=1000)
        self.min_change_threshold = 5  # Minimum change to trigger signal
        self.divergence_multiplier = 2.0  # How much model change must exceed market change
        
    def update_history(self, timestamp, predicted_price, market_mid):
        """Update value history with current data."""
        self.value_history.append({
            'timestamp': timestamp,
            'predicted_price': predicted_price,
            'market_mid': market_mid
        })
    
    def calculate_change_signal(self, timestamp, current_predicted, current_market):
        """Calculate if model change significantly exceeds market change."""
        if len(self.value_history) < 2:
            return 0
            
        # Find data from n minutes ago
        cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
        historical_data = [h for h in self.value_history if h['timestamp'] >= cutoff_time]
        
        if len(historical_data) < 2:
            return 0
            
        # Get oldest data point in window
        oldest = historical_data[0]
        
        # Calculate changes
        model_change = current_predicted - oldest['predicted_price']
        market_change = current_market - oldest['market_mid']
        
        # Check if changes are significant enough
        if abs(model_change) < self.min_change_threshold:
            return 0
            
        # Model predicts much larger positive change than market moved - buy
        if model_change > 0 and model_change > abs(market_change) * self.divergence_multiplier:
            return 1
            
        # Model predicts much larger negative change than market moved - sell
        if model_change < 0 and abs(model_change) > abs(market_change) * self.divergence_multiplier:
            return -1
            
        return 0

    def calculate_signal(self, timestamp, mid_price: float, bid_price: float, ask_price: float) -> int:
        if mid_price is None or bid_price is None or ask_price is None:
            logging.warning("---- Missing price data. Unable to calculate signal.")
            return 0
            
        market_mid = (bid_price + ask_price) / 2
        
        # Update history
        self.update_history(timestamp, mid_price, market_mid)
        
        # Calculate change-based signal
        change_signal = self.calculate_change_signal(timestamp, mid_price, market_mid)
        
        if change_signal == 0:
            return 0
            
        # Apply position and cash constraints
        if change_signal < 0:  # Sell signal
            if self.positions > self.min_positions and self.cash >= bid_price / 100:
                if self.last_sell_ts is None:
                    return -1
                else:
                    time_dif = minutes_between_timestamps(self.last_sell_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return -1
                        
        elif change_signal > 0:  # Buy signal
            if self.positions < self.max_positions and self.cash >= ask_price / 100:
                if self.last_buy_ts is None:
                    return 1
                else:
                    time_dif = minutes_between_timestamps(self.last_buy_ts, timestamp)
                    if time_dif >= self.trade_cooldown:
                        return 1
                        
        return 0

    def trade(self, timestamp, game, bid_price: float, ask_price: float):
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
       
        if mid_price and bid_price and ask_price:
            market_mid = (bid_price + ask_price) / 2
            logging.info(f"{timestamp}: ChangeInValue Strategy -- Predicted: {mid_price}, Market Mid: {market_mid}, Bid: {bid_price}, Ask: {ask_price}")
            
            signal = self.calculate_signal(timestamp, mid_price, bid_price, ask_price)

            if signal != 0:
                # Log the change details
                if len(self.value_history) >= 2:
                    cutoff_time = add_minutes_to_timestamp(timestamp, -self.history_minutes)
                    historical_data = [h for h in self.value_history if h['timestamp'] >= cutoff_time]
                    if historical_data:
                        oldest = historical_data[0]
                        model_change = mid_price - oldest['predicted_price']
                        market_change = market_mid - oldest['market_mid']
                        logging.info(f"-- Value divergence: Model change: {model_change:.1f}, Market change: {market_change:.1f}")
                
                logging.info(f"-- ChangeInValue signal generated: {signal} positions")
                if signal > 0:
                    self.last_buy_ts = timestamp
                    self.buy(ask_price, signal)
                elif signal < 0:
                    self.last_sell_ts = timestamp
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