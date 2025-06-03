

class Market:
    def __init__(self, market_dict: dict):
        self.can_close_early = None
        self.category = None
        self.close_time = None
        self.custom_strike = None
        self.event_ticker = None
        self.expected_expiration_time = None
        self.expiration_time = None
        self.expiration_value = None
        self.last_price = None
        self.latest_expiration_time = None
        self.liquidity = None
        self.market_type = None
        self.no_ask = None
        self.no_bid = None
        self.no_sub_title = None
        self.notional_value = None
        self.open_interest = None
        self.open_time = None
        self.previous_price = None
        self.previous_yes_ask = None
        self.previous_yes_bid = None
        self.response_price_units = None
        self.result = None
        self.risk_limit_cents = None
        self.rules_primary = None
        self.rules_secondary = None
        self.series_ticker = None
        self.settlement_timer_seconds = None
        self.status = None
        self.strike_type = None
        self.subtitle = None
        self.tick_size = None
        self.ticker = None
        self.title = None
        self.volume = None
        self.volume_24h = None
        self.yes_ask = None
        self.yes_bid = None
        self.yes_sub_title = None

        for key, val in market_dict.items():
            setattr(self, key, val)

        if self.series_ticker is None:
            self.series_ticker = self.ticker.split('-')[0]