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
        bids = {}
        asks = {}

        if "yes" in orderbook:
            for bid in orderbook["yes"]:
                bids[bid[0]] = bid[1]

        if "no" in orderbook:
            for ask in orderbook["no"]:
                asks[100 - ask[0]] = ask[1]

        self.bids = bids
        self.asks = asks
        self.last_update = "kalshi"
        logging.debug(datetime.now().strftime("%H:%M:%S") + F": Received Kalshi orderbook snapshot: {orderbook}")

    def update_orderbook(self, delta):
        price = delta["price"]
        change = delta["delta"]
        side = delta["side"]

        if side == "no":
            price = 100 - price
            if price in self.asks:
                self.asks[price] += change
            else:
                self.asks[price] = change

            if self.asks[price] == 0:
                del self.asks[price]
        else:
            if price in self.bids:
                self.bids[price] += change
            else:
                self.bids[price] = change

            if self.bids[price] == 0:
                del self.bids[price]

        self.last_update = "kalshi"
        logging.debug(f"Received Kalshi orderbook delta: {delta}")
        #self.om.interupted = True


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

