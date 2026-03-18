from Core.strategy import BaseStrategy, DataRequirement, Order, OrderSide
from Markets.Baseball.prediction import get_prediction_model_by_version
from collections import deque
import logging
import Utils.date_helpers as date_helpers


class SimpleBacktestStrategy(BaseStrategy):
    """Simple baseball strategy (v1.1.0)."""

    _version = "v1.1.0"
    _prediction_model_version = "v1.1.0"

    def __init__(self):
        super().__init__()
        self.prediction_model = get_prediction_model_by_version(self._prediction_model_version)
        self.last_trade_time = None
        self.position_limits = (-10, 10)
        self.trade_cooldown_minutes = 10

    def get_data_requirements(self):
        return [DataRequirement(
            data_key="game",
            loader_class="Markets.Baseball.data_loader.BaseballDataLoader",
            params={}
        )]

    def on_resolution(self, context, outcome: bool):
        """Reset per-market state so strategy is fresh for the next market."""
        self.last_trade_time = None

    def on_timestep(self, context):
        game = context.auxiliary_data.get('game')
        if not game or game.status != "In Progress":
            return []

        # Calculate mid-price from prediction model
        mid_price = self.prediction_model.calculate_expected_win_prob(game)
        if mid_price == -1 or mid_price is None:
            return []

        # Calculate signal
        signal = self._calculate_signal(
            context.timestamp,
            mid_price,
            context.bid_price,
            context.ask_price,
            context.portfolio_snapshot['positions']
        )

        # Generate orders
        orders = []
        if signal > 0:
            orders.append(Order(OrderSide.BUY, signal, context.ask_price))
        elif signal < 0:
            orders.append(Order(OrderSide.SELL, abs(signal), context.bid_price))

        if orders:
            self.last_trade_time = context.timestamp

        return orders

    def _calculate_signal(self, timestamp, mid_price, bid_price, ask_price, current_positions):
        """Calculate trading signal."""
        if bid_price is None or ask_price is None:
            return 0

        # Trade cooldown
        if self.last_trade_time:
            minutes_since_trade = date_helpers.minutes_between_timestamps(
                self.last_trade_time, timestamp
            )
            if minutes_since_trade < self.trade_cooldown_minutes:
                return 0

        # Buy signal
        if mid_price - ask_price >= 5 and ask_price > 15:
            if current_positions < self.position_limits[1]:
                return 1

        # Sell signal
        if bid_price - mid_price >= 5 and bid_price < 85:
            if current_positions > self.position_limits[0]:
                return -1

        return 0


class ConservativeBacktestStrategy(SimpleBacktestStrategy):
    """Conservative strategy with higher thresholds."""

    _version = "v2.0.0"
    _prediction_model_version = "v1.1.0"

    def __init__(self):
        super().__init__()
        self.position_limits = (-5, 5)
        self.trade_cooldown_minutes = 15
        self.threshold = 20
        self.price_min = 20
        self.price_max = 80

    def _calculate_signal(self, timestamp, mid_price, bid_price, ask_price, current_positions):
        if bid_price is None or ask_price is None:
            return 0

        # Price constraints
        if bid_price < self.price_min or ask_price > self.price_max:
            return 0

        # Trade cooldown
        if self.last_trade_time:
            minutes_since_trade = date_helpers.minutes_between_timestamps(
                self.last_trade_time, timestamp
            )
            if minutes_since_trade < self.trade_cooldown_minutes:
                return 0

        # Buy/sell with higher threshold
        if mid_price - ask_price >= self.threshold and current_positions < self.position_limits[1]:
            return 1
        if bid_price - mid_price >= self.threshold and current_positions > self.position_limits[0]:
            return -1

        return 0


class AggressiveValueStrategy(SimpleBacktestStrategy):
    """Aggressive strategy with position scaling."""

    _version = "v3.0.0"
    _prediction_model_version = "v1.1.0"

    def __init__(self):
        super().__init__()
        self.position_limits = (-20, 20)
        self.trade_cooldown_minutes = 5
        self.threshold = 5

    def _calculate_signal(self, timestamp, mid_price, bid_price, ask_price, current_positions):
        if bid_price is None or ask_price is None:
            return 0

        # Trade cooldown
        if self.last_trade_time:
            minutes_since_trade = date_helpers.minutes_between_timestamps(
                self.last_trade_time, timestamp
            )
            if minutes_since_trade < self.trade_cooldown_minutes:
                return 0

        # Calculate edge
        buy_edge = mid_price - ask_price
        sell_edge = bid_price - mid_price

        # Position scaling based on edge
        if buy_edge >= self.threshold:
            if buy_edge >= 15:
                position_size = 3
            elif buy_edge >= 10:
                position_size = 2
            else:
                position_size = 1

            if current_positions + position_size <= self.position_limits[1]:
                return position_size

        if sell_edge >= self.threshold:
            if sell_edge >= 15:
                position_size = 3
            elif sell_edge >= 10:
                position_size = 2
            else:
                position_size = 1

            if current_positions - position_size >= self.position_limits[0]:
                return -position_size

        return 0


class ReverseSteamStrategy(SimpleBacktestStrategy):
    """Mean reversion strategy tracking price momentum."""

    _version = "v4.0.0"
    _prediction_model_version = "v1.1.0"

    def __init__(self):
        super().__init__()
        self.position_limits = (-10, 10)
        self.trade_cooldown_minutes = 10
        self.price_history = deque(maxlen=10)  # 10-minute window
        self.model_history = deque(maxlen=10)

    def on_resolution(self, context, outcome: bool):
        super().on_resolution(context, outcome)
        self.price_history.clear()
        self.model_history.clear()

    def on_timestep(self, context):
        game = context.auxiliary_data.get('game')
        if not game or game.status != "In Progress":
            return []

        mid_price = self.prediction_model.calculate_expected_win_prob(game)
        if mid_price == -1 or mid_price is None:
            return []

        # Track history
        if context.mid_price:
            self.price_history.append(context.mid_price)
        self.model_history.append(mid_price)

        # Need enough history
        if len(self.price_history) < 2 or len(self.model_history) < 2:
            return []

        # Calculate changes
        price_change = self.price_history[-1] - self.price_history[0]
        model_change = self.model_history[-1] - self.model_history[0]

        # Signal when market overreacts (>1.5x model change)
        orders = []
        if abs(price_change) > 1.5 * abs(model_change):
            if price_change > 0:  # Market went up too much, sell
                if context.portfolio_snapshot['positions'] > self.position_limits[0]:
                    orders.append(Order(OrderSide.SELL, 1, context.bid_price))
            elif price_change < 0:  # Market went down too much, buy
                if context.portfolio_snapshot['positions'] < self.position_limits[1]:
                    orders.append(Order(OrderSide.BUY, 1, context.ask_price))

        return orders


class ChangeInValueStrategy(SimpleBacktestStrategy):
    """Trade on divergence between model and market changes."""

    _version = "v5.0.0"
    _prediction_model_version = "v1.1.0"

    def __init__(self):
        super().__init__()
        self.position_limits = (-10, 10)
        self.trade_cooldown_minutes = 10
        self.price_history = deque(maxlen=10)
        self.model_history = deque(maxlen=10)
        self.min_change = 5
        self.multiplier = 2.0

    def on_resolution(self, context, outcome: bool):
        super().on_resolution(context, outcome)
        self.price_history.clear()
        self.model_history.clear()

    def on_timestep(self, context):
        game = context.auxiliary_data.get('game')
        if not game or game.status != "In Progress":
            return []

        mid_price = self.prediction_model.calculate_expected_win_prob(game)
        if mid_price == -1 or mid_price is None:
            return []

        # Track history
        if context.mid_price:
            self.price_history.append(context.mid_price)
        self.model_history.append(mid_price)

        if len(self.price_history) < 2 or len(self.model_history) < 2:
            return []

        # Calculate changes
        price_change = self.price_history[-1] - self.price_history[0]
        model_change = self.model_history[-1] - self.model_history[0]

        # Trade when model change exceeds market change by multiplier
        orders = []
        if abs(model_change) >= self.min_change:
            if model_change > self.multiplier * price_change:  # Model up more than market
                if context.portfolio_snapshot['positions'] < self.position_limits[1]:
                    orders.append(Order(OrderSide.BUY, 1, context.ask_price))
            elif model_change < self.multiplier * price_change:  # Model down more than market
                if context.portfolio_snapshot['positions'] > self.position_limits[0]:
                    orders.append(Order(OrderSide.SELL, 1, context.bid_price))

        return orders
