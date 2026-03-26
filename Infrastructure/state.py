import logging
from datetime import datetime
from Infrastructure.Clients.http_client import KalshiHttpClient


class Orderbook:
    def __init__(self, ticker):
        self.ticker = ticker
        self.bids = {}
        self.asks = {}
        self.last_update = ""
        self.position = 0

    def set_orderbook(self, orderbook):
        """
        Handle Kalshi WebSocket v2 orderbook_snapshot messages.

        Snapshot format:
          {
            "market_ticker": "...",
            "yes_dollars_fp": [["0.0700", "4666.00"], ...],  # YES bids
            "no_dollars_fp":  [["0.0800", "5953.00"], ...],  # NO bids → YES asks
          }
        Prices are dollar strings; quantities are float strings.
        Internally we store prices as integer cents.
        """
        bids = {}
        asks = {}

        for entry in orderbook.get("yes_dollars_fp", []):
            price_cents = round(float(entry[0]) * 100)
            qty = float(entry[1])
            bids[price_cents] = qty

        for entry in orderbook.get("no_dollars_fp", []):
            no_price_cents = round(float(entry[0]) * 100)
            ask_cents = 100 - no_price_cents
            qty = float(entry[1])
            asks[ask_cents] = qty

        self.bids = bids
        self.asks = asks
        self.last_update = "kalshi"
        logging.debug(datetime.now().strftime("%H:%M:%S") + f": Received Kalshi orderbook snapshot: {orderbook}")

    def update_orderbook(self, delta):
        """
        Handle Kalshi WebSocket v2 orderbook_delta messages.

        Delta format:
          {
            "market_ticker": "...",
            "price_dollars": "0.0700",   # price as dollar string
            "delta_fp": "29.00",          # qty change (can be negative)
            "side": "yes" | "no",
            "ts": "..."
          }
        """
        side = delta.get("side")
        price_dollars = delta.get("price_dollars")
        delta_fp = delta.get("delta_fp")

        if price_dollars is None or delta_fp is None or side is None:
            return

        price_cents = round(float(price_dollars) * 100)
        change = float(delta_fp)

        if side == "yes":
            qty = self.bids.get(price_cents, 0) + change
            if qty <= 0:
                self.bids.pop(price_cents, None)
            else:
                self.bids[price_cents] = qty
        elif side == "no":
            ask_cents = 100 - price_cents
            qty = self.asks.get(ask_cents, 0) + change
            if qty <= 0:
                self.asks.pop(ask_cents, None)
            else:
                self.asks[ask_cents] = qty

        self.last_update = "kalshi"
        logging.debug(f"Received Kalshi orderbook delta: {delta}")


class TradingState:

    def __init__(self, client: KalshiHttpClient, tickers: list | str):
        if isinstance(tickers, str):
            tickers = [tickers]
        self.orderbooks = {ticker: Orderbook(ticker) for ticker in tickers}
        self.client = client

    def set_orderbooks(self, orderbook):
        ticker = orderbook["market_ticker"]
        self.orderbooks[ticker].set_orderbook(orderbook)

    def update_orderbooks(self, delta):
        ticker = delta["market_ticker"]
        self.orderbooks[ticker].update_orderbook(delta)

