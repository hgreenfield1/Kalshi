import pandas as pd
import requests
import time
import datetime
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric import rsa

from Infrastructure.Clients.base_client import Environment, KalshiBaseClient
from Infrastructure.market import Market


class KalshiHttpClient(KalshiBaseClient):
    """Client for handling HTTP connections to the Kalshi API."""
    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.DEMO,
    ):
        super().__init__(key_id, private_key, environment)
        self.host = self.HTTP_BASE_URL
        self.exchange_url = "/trade-api/v2/exchange"
        self.markets_url = "/trade-api/v2/markets"
        self.series_url = "/trade-api/v2/series"
        self.portfolio_url = "/trade-api/v2/portfolio"

    def rate_limit(self) -> None:
        """Built-in rate limiter to prevent exceeding API rate limits."""
        THRESHOLD_IN_MILLISECONDS = 100
        now = datetime.now()
        threshold_in_microseconds = 1000 * THRESHOLD_IN_MILLISECONDS
        threshold_in_seconds = THRESHOLD_IN_MILLISECONDS / 1000
        if now - self.last_api_call < timedelta(microseconds=threshold_in_microseconds):
            time.sleep(threshold_in_seconds)
        self.last_api_call = datetime.now()

    def raise_if_bad_response(self, response: requests.Response) -> None:
        """Raises an HTTPError if the response status code indicates an error."""
        if response.status_code not in range(200, 299):
            response.raise_for_status()

    def post(self, path: str, body: dict) -> Any:
        """Performs an authenticated POST request to the Kalshi API."""
        self.rate_limit()
        response = requests.post(
            self.host + path,
            json=body,
            headers=self.request_headers("POST", path)
        )
        self.raise_if_bad_response(response)
        return response.json()

    def get(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated GET request to the Kalshi API."""
        self.rate_limit()
        response = requests.get(
            self.host + path,
            headers=self.request_headers("GET", path),
            params=params
        )
        self.raise_if_bad_response(response)
        return response.json()

    def delete(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated DELETE request to the Kalshi API."""
        self.rate_limit()
        response = requests.delete(
            self.host + path,
            headers=self.request_headers("DELETE", path),
            params=params
        )
        self.raise_if_bad_response(response)
        return response.json()

    def get_balance(self) -> Dict[str, Any]:
        """Retrieves the account balance."""
        return self.get(self.portfolio_url + '/balance')

    def get_exchange_status(self) -> Dict[str, Any]:
        """Retrieves the exchange status."""
        return self.get(self.exchange_url + "/status")

    async def get_orders(self, market_ticker: str):
        res, code = await self.get("/portfolio/orders/?ticker=" + market_ticker + "&status=resting")
        return res, code
    
    async def cancel_limit_order(self, order_id):
        try:
            resolve, code = await self.delete(f"/portfolio/orders/{order_id}")
            return resolve, code
        except Exception as e:
            print("Error canceling order:", e)
            return False # failed cancel, don't handle error here
        
    def get_trades(
        self,
        ticker: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        max_ts: Optional[int] = None,
        min_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Retrieves trades based on provided filters."""
        params = {
            'ticker': ticker,
            'limit': limit,
            'cursor': cursor,
            'max_ts': max_ts,
            'min_ts': min_ts,
        }
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return self.get(self.markets_url + '/trades', params=params)

    def get_markets(self, series_tickers: str | list) -> dict[str: Market]:
        if isinstance(series_tickers, str):
            series_tickers = [series_tickers]

        market_dict = {}
        for series_ticker in series_tickers:
            series = self.get(self.markets_url + "?series_ticker=" + series_ticker + "&status=open")
            for market in series['markets']:
                market = Market(market)
                market_dict[market.ticker] = market

        return market_dict

    def get_market_candelstick(self, market_ticker: str, series_ticker: str, start_ts: int | str, end_ts: int | str, interval: int = 1):
        if isinstance(start_ts, str):
            try:
                start_ts = datetime.strptime(start_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                start_ts = int(start_ts.timestamp())
            except:
                Exception("Unsupported date format provided for start_ts.")
        if isinstance(end_ts, str):
            try:
                end_ts = datetime.strptime(end_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                end_ts = int(end_ts.timestamp())
            except:
                Exception("Unsupported date format provided for end_ts.")

        # todo - convert to candlestick object?
        candlestick = self.get(self.series_url + f"/{series_ticker}/markets/{market_ticker}/candlesticks?start_ts={start_ts}&end_ts={end_ts}&period_interval={interval}")\

        return candlestick
