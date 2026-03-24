from Core.strategy import BaseStrategy, DataRequirement, Order, OrderSide
from Markets.Baseball.prediction import get_prediction_model_by_version
from collections import deque


class BaseMLBStrategy(BaseStrategy):
    """
    Shared infrastructure for MLB strategies:
      - Signal state tracking: only trades on signal transitions (None → 'long'/'short')
      - Kelly criterion sizing: fractional Kelly scales contracts by edge magnitude
      - Early exit: profit target, stop loss, and model reversal exits
    """

    def __init__(self):
        super().__init__()
        self._active_signal = None  # 'long', 'short', or None
        self._entry_price = None    # price at which current position was opened
        self.position_limits = (-10, 10)
        self.kelly_fraction = 0.25
        self.profit_target_pts = 35
        self.stop_loss_pts = 25

    def _kelly_contracts(self, model_prob: float, price: float, cash: float, side: str) -> int:
        """Fractional Kelly contract sizing.

        Buy:   f = (model_prob - ask) / (100 - ask)
        Short: f = (bid - model_prob) / bid
        Scale by kelly_fraction * max_position. Floor at 1, cap by cash.
        """
        if side == 'long':
            edge, denom = model_prob - price, 100 - price
        else:
            edge, denom = price - model_prob, price

        if denom <= 0 or edge <= 0:
            return 0

        kelly_f = (edge / denom) * self.kelly_fraction
        kelly_qty = max(1, round(kelly_f * self.position_limits[1]))

        cost_per = (price / 100) if side == 'long' else ((100 - price) / 100)
        cash_limit = int(cash / cost_per) if cost_per > 0 else 0

        return min(kelly_qty, cash_limit, self.position_limits[1])

    def _check_early_exit(self, positions: int, bid: float, ask: float, model_prob: float):
        """Return 'close_long', 'close_short', or None."""
        if positions == 0 or self._entry_price is None:
            return None

        if positions > 0:
            pnl = bid - self._entry_price
            if pnl >= self.profit_target_pts:
                return 'close_long'
            if pnl <= -self.stop_loss_pts:
                return 'close_long'
            if model_prob < 50:  # model reversed to bearish
                return 'close_long'

        elif positions < 0:
            pnl = self._entry_price - ask
            if pnl >= self.profit_target_pts:
                return 'close_short'
            if pnl <= -self.stop_loss_pts:
                return 'close_short'
            if model_prob > 50:  # model reversed to bullish
                return 'close_short'

        return None

    def _compute_signal(self, context, model_prob: float):
        """Override in subclass. Return 'long', 'short', or None."""
        raise NotImplementedError

    def on_timestep(self, context):
        game = context.auxiliary_data.get('game')
        if not game or game.status != "In Progress":
            return []

        model_prob = self.prediction_model.calculate_expected_win_prob(game)
        if model_prob is None or model_prob == -1:
            return []

        bid = context.bid_price
        ask = context.ask_price
        if bid is None or ask is None:
            return []

        positions = context.portfolio_snapshot['positions']
        cash = context.portfolio_snapshot['cash']
        orders = []

        # --- Early exit ---
        exit_action = self._check_early_exit(positions, bid, ask, model_prob)
        if exit_action == 'close_long' and positions > 0:
            orders.append(Order(OrderSide.SELL, positions, bid))
            self._active_signal = None
            self._entry_price = None
            return orders
        elif exit_action == 'close_short' and positions < 0:
            orders.append(Order(OrderSide.BUY, abs(positions), ask))
            self._active_signal = None
            self._entry_price = None
            return orders

        # --- Signal state: only trade on transitions ---
        new_signal = self._compute_signal(context, model_prob)
        if new_signal == self._active_signal:
            return []

        self._active_signal = new_signal

        if new_signal == 'long' and positions < self.position_limits[1]:
            qty = self._kelly_contracts(model_prob, ask, cash, 'long')
            if qty > 0:
                orders.append(Order(OrderSide.BUY, qty, ask))
                self._entry_price = ask

        elif new_signal == 'short' and positions > self.position_limits[0]:
            qty = self._kelly_contracts(model_prob, bid, cash, 'short')
            if qty > 0:
                orders.append(Order(OrderSide.SELL, qty, bid))
                self._entry_price = bid

        return orders

    def on_resolution(self, context, outcome: bool):
        self._active_signal = None
        self._entry_price = None


class FavoriteLongShotStrategy(BaseMLBStrategy):
    """
    Exploits the favorite-longshot bias: markets systematically underprice heavy
    favorites and overprice longshots relative to true probability.

    Only trades when the model has strong conviction (win prob far from 50%),
    and the market hasn't priced that conviction in.

    Signal:
      long  — model >= conviction_threshold AND model - ask >= edge_threshold
      short — model <= (100 - conviction_threshold) AND bid - model >= edge_threshold
    """

    _version = "v1.1.0"
    _prediction_model_version = "v1.1.0"

    def __init__(self):
        super().__init__()
        self.prediction_model = get_prediction_model_by_version(self._prediction_model_version)
        self.conviction_threshold = 60
        self.edge_threshold = 5

    def get_data_requirements(self):
        return [DataRequirement(
            data_key="game",
            loader_class="Markets.Baseball.data_loader.BaseballDataLoader",
            params={}
        )]

    def _compute_signal(self, context, model_prob: float):
        bid = context.bid_price
        ask = context.ask_price
        if model_prob >= self.conviction_threshold and model_prob - ask >= self.edge_threshold:
            return 'long'
        if model_prob <= (100 - self.conviction_threshold) and bid - model_prob >= self.edge_threshold:
            return 'short'
        return None


class MeanReversionStrategy(BaseMLBStrategy):
    """
    Fades market overreactions: when the market moves significantly more than
    the model suggests, trade against the direction of the move.

    Tracks rolling windows of market mid-price and model probability.
    Signal:
      short — price_change - model_change > overreaction_threshold  (market ran up too much)
      long  — model_change - price_change > overreaction_threshold  (market dropped too much)
    """

    _version = "v2.1.0"
    _prediction_model_version = "v1.1.0"

    def __init__(self):
        super().__init__()
        self.prediction_model = get_prediction_model_by_version(self._prediction_model_version)
        self.window_minutes = 10
        self.overreaction_threshold = 5
        self.price_history = deque(maxlen=self.window_minutes)
        self.model_history = deque(maxlen=self.window_minutes)

    def get_data_requirements(self):
        return [DataRequirement(
            data_key="game",
            loader_class="Markets.Baseball.data_loader.BaseballDataLoader",
            params={}
        )]

    def _compute_signal(self, context, model_prob: float):
        mid = context.mid_price
        if mid is not None:
            self.price_history.append(mid)
        self.model_history.append(model_prob)

        if len(self.price_history) < self.window_minutes or len(self.model_history) < self.window_minutes:
            return None

        price_change = self.price_history[-1] - self.price_history[0]
        model_change = self.model_history[-1] - self.model_history[0]
        overreaction = price_change - model_change

        if overreaction > self.overreaction_threshold:
            return 'short'
        if overreaction < -self.overreaction_threshold:
            return 'long'
        return None

    def on_resolution(self, context, outcome: bool):
        super().on_resolution(context, outcome)
        self.price_history.clear()
        self.model_history.clear()
