from Core.strategy import BaseStrategy, DataRequirement, Order, OrderSide
from Markets.Baseball.prediction import get_prediction_model_by_version
from collections import deque


# ---------------------------------------------------------------------------
# Per-inning edge thresholds (based on model Brier by inning group)
# ---------------------------------------------------------------------------
# Innings 1-3: Brier ~0.22 — require large deviation to overcome uncertainty
# Innings 4-6: Brier ~0.16 — moderate threshold, sweet spot for market lag
# Innings 7+:  Brier ~0.09 — model is sharp, standard threshold
INNING_EDGE_THRESHOLDS = {
    'early': 10,  # innings 1-3
    'mid':    5,  # innings 4-6
    'late':   5,  # innings 7+
}
INNING_CONVICTION_THRESHOLDS = {
    'early': 60,  # innings 1-3: need strong conviction given uncertainty
    'mid':   55,  # innings 4-6: allow moderate conviction trades
    'late':  55,  # innings 7+
}


def _inning_bucket(inning: int) -> str:
    if inning <= 3:
        return 'early'
    elif inning <= 6:
        return 'mid'
    return 'late'


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
        self._tick_history: list = []  # {ts, bid, ask, model_prob} — capped at 200

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

        # Record tick for dashboard price chart
        self._tick_history.append({
            'ts': context.timestamp,
            'bid': bid,
            'ask': ask,
            'model_prob': model_prob,
        })
        if len(self._tick_history) > 200:
            self._tick_history = self._tick_history[-200:]

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
        # Keep _tick_history so the dashboard can render the price chart after game end

    def save_state(self) -> dict:
        state = {}
        try:
            state = super().save_state()
        except Exception:
            pass
        state['tick_history'] = self._tick_history[-200:]
        return state

    def restore_state(self, state: dict) -> None:
        try:
            super().restore_state(state)
        except Exception:
            pass
        self._tick_history = state.get('tick_history', [])


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
    _name = "FavoriteLongShot"
    _description = (
        "Exploits favorite-longshot bias. "
        "Long when model >= 60% and edge vs ask >= 5pts. "
        "Short when model <= 40% and edge vs bid >= 5pts. "
        "Kelly fraction=0.25, profit target=+35¢, stop loss=-25¢, model reversal exit."
    )

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
    _name = "MeanReversion"
    _description = (
        "Fades market overreactions. "
        "Short when price_change - model_change > 5pts over 10-min window. "
        "Long when model_change - price_change > 5pts over 10-min window. "
        "Kelly fraction=0.25, profit target=+35¢, stop loss=-25¢, model reversal exit."
    )

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

    def save_state(self) -> dict:
        return {
            **super().save_state(),
            'price_history': list(self.price_history),
            'model_history': list(self.model_history),
        }

    def restore_state(self, state: dict) -> None:
        super().restore_state(state)
        self.price_history = deque(state.get('price_history', []), maxlen=self.window_minutes)
        self.model_history = deque(state.get('model_history', []), maxlen=self.window_minutes)


class InningAdjustedEdgeStrategy(BaseMLBStrategy):
    """
    Trades model-vs-market deviations with edge requirements calibrated
    to model reliability by inning group.

    Rationale
    ---------
    The win probability model has very different accuracy by inning:
      - Innings 1-3: Brier ~0.22 (score still 0-0, high uncertainty)
      - Innings 4-6: Brier ~0.16 (sweet spot — model is good, market lags)
      - Innings 7-9: Brier ~0.09 (sharp, but market is also efficient)

    By requiring a larger edge early (10 pts) and standard edge mid/late (5 pts),
    we only trade early when the market is genuinely mispriced vs the model,
    and capture mid-game opportunities that FavoriteLongShot misses by
    requiring 60% conviction.

    Signal (both innings 4-9 at 5 pts, innings 1-3 at 10 pts):
      long  — model >= conviction_threshold AND model - ask >= edge_threshold(inning)
      short — model <= (100 - conviction_threshold) AND bid - model >= edge_threshold(inning)
    """

    _version = "v3.0.0"
    _prediction_model_version = "v1.1.0"
    _name = "InningAdjustedEdge"
    _description = (
        "Model-vs-market edge with inning-calibrated thresholds. "
        "Innings 1-3: edge >= 10pts, conviction >= 60%. "
        "Innings 4-6: edge >= 5pts, conviction >= 55%. "
        "Innings 7+: edge >= 5pts, conviction >= 55%. "
        "Kelly fraction=0.25, profit target=+35¢, stop loss=-25¢, model reversal exit."
    )

    def __init__(self):
        super().__init__()
        self.prediction_model = get_prediction_model_by_version(self._prediction_model_version)

    def get_data_requirements(self):
        return [DataRequirement(
            data_key="game",
            loader_class="Markets.Baseball.data_loader.BaseballDataLoader",
            params={}
        )]

    def _compute_signal(self, context, model_prob: float):
        game = context.auxiliary_data.get('game')
        bid = context.bid_price
        ask = context.ask_price

        inning = getattr(game, 'inning', 5) if game else 5
        bucket = _inning_bucket(inning)
        edge_thresh = INNING_EDGE_THRESHOLDS[bucket]
        conv_thresh = INNING_CONVICTION_THRESHOLDS[bucket]

        if model_prob >= conv_thresh and model_prob - ask >= edge_thresh:
            return 'long'
        if model_prob <= (100 - conv_thresh) and bid - model_prob >= edge_thresh:
            return 'short'
        return None
