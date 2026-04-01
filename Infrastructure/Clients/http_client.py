import logging
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
            headers=self.request_headers("POST", path),
            timeout=30
        )
        self.raise_if_bad_response(response)
        return response.json()

    def get(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated GET request to the Kalshi API."""
        self.rate_limit()
        response = requests.get(
            self.host + path,
            headers=self.request_headers("GET", path),
            params=params,
            timeout=30
        )
        self.raise_if_bad_response(response)
        return response.json()

    def delete(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated DELETE request to the Kalshi API."""
        self.rate_limit()
        response = requests.delete(
            self.host + path,
            headers=self.request_headers("DELETE", path),
            params=params,
            timeout=30
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

    def get_open_orders(self, ticker: Optional[str] = None) -> list:
        """Return all resting (unfilled) orders, optionally filtered by ticker."""
        params: Dict[str, Any] = {'status': 'resting', 'limit': 100}
        if ticker:
            params['ticker'] = ticker
        try:
            resp = self.get(self.portfolio_url + '/orders', params)
            return resp.get('orders', [])
        except Exception:
            return []

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single resting order by ID. Returns True on success."""
        try:
            self.delete(f'{self.portfolio_url}/orders/{order_id}')
            return True
        except Exception as e:
            logging.getLogger(__name__).warning('Failed to cancel order %s: %s', order_id, e)
            return False
        
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

    def get_markets(self, series_tickers: str | list, status="open") -> dict[str: Market]:
        if isinstance(series_tickers, str):
            series_tickers = [series_tickers]

        market_dict = {}
        for series_ticker in series_tickers:
            series_list = []
            series_response = self.get(self.markets_url + "?series_ticker=" + series_ticker + "&status=" + status + "&limit=999")
            series_list += series_response['markets']
            while series_response['cursor'] != "":
                series_response = self.get(self.markets_url + "?series_ticker=" + series_ticker + "&status=" + status + "&limit=999&cursor=" + series_response['cursor'])
                series_list += series_response['markets']

            for market in series_list:
                market = Market(market)
                market_dict[market.ticker] = market

            # For settled markets, also fetch from the historical archive which covers
            # events before the cutoff (~Jan 1 of current year). The live endpoint only
            # returns a rolling window of ~138 recent markets.
            if status == 'settled':
                historical = self._get_historical_markets(series_ticker)
                for market in historical:
                    if market.ticker not in market_dict:
                        market_dict[market.ticker] = market

        return market_dict

    def _get_historical_markets(self, series_ticker: str) -> list:
        """Fetch archived markets from /historical/markets using cached event tickers.

        Reconstructs expected market tickers from event tickers, then batch-fetches
        from the historical endpoint (50 tickers per call). Results are disk-cached.
        """
        import json
        try:
            from Markets.Baseball.config import GAME_CACHE_DIR
            from Markets.Baseball.utils import mlb_teams
            cache_path = GAME_CACHE_DIR / f'historical_markets_{series_ticker}.json'
        except Exception:
            return []

        logger = logging.getLogger(__name__)
        team_set = set(mlb_teams.keys())

        def _parse_teams(event_ticker):
            _, seg = event_ticker.split('-', 1)
            offset = 11 if len(seg) > 11 and seg[7:11].isdigit() else 7
            ts = seg[offset:]
            for sfx in ('G2', 'G1'):
                if ts.endswith(sfx):
                    ts = ts[:-2]
                    break
            for n in (3, 2):
                if ts[:n] in team_set and ts[n:] in team_set:
                    return ts[:n], ts[n:]
            return None, None

        # Load cache: markets list + set of already-attempted tickers (including not-found ones)
        attempted_path = cache_path.with_suffix('.attempted.json')
        cached_raw: list = []
        already_attempted: set = set()
        if cache_path.exists():
            try:
                cached_raw = json.loads(cache_path.read_text())
                logger.info(f'Loaded {len(cached_raw)} cached historical markets')
            except Exception:
                cached_raw = []
        if attempted_path.exists():
            try:
                already_attempted = set(json.loads(attempted_path.read_text()))
            except Exception:
                already_attempted = set()

        cached_tickers = {m['ticker'] for m in cached_raw}

        # Get event ticker list (uses its own cache)
        try:
            event_tickers = self._get_settled_event_tickers(series_ticker)
        except Exception:
            event_tickers = []

        # Build expected home-team market tickers not yet attempted
        missing_tickers = []
        for et in event_tickers:
            home, _ = _parse_teams(et)
            if home:
                ticker = f'{et}-{home}'
                if ticker not in cached_tickers and ticker not in already_attempted:
                    missing_tickers.append(ticker)

        if missing_tickers:
            logger.info(f'Fetching {len(missing_tickers)} missing historical markets...')
            new_markets = []
            BATCH = 50
            for i in range(0, len(missing_tickers), BATCH):
                batch = missing_tickers[i:i + BATCH]
                for attempt in range(3):
                    try:
                        r = self.get(f'/trade-api/v2/historical/markets?tickers={",".join(batch)}&limit=100')
                        new_markets.extend(r.get('markets', []))
                        break
                    except Exception as e:
                        if '429' in str(e) and attempt < 2:
                            time.sleep(2 ** attempt)
                        else:
                            break

            cached_raw.extend(new_markets)
            already_attempted.update(missing_tickers)
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cached_raw))
                attempted_path.write_text(json.dumps(list(already_attempted)))
                logger.info(f'Cached {len(cached_raw)} historical markets to {cache_path.name}')
            except Exception as e:
                logger.warning(f'Could not write historical market cache: {e}')

        return [Market(m) for m in cached_raw]

    def _get_settled_event_tickers(self, series_ticker: str) -> list[str]:
        """Page through the events API to get all settled event tickers for a series, with disk caching."""
        import json
        try:
            from Markets.Baseball.config import GAME_CACHE_DIR
            cache_path = GAME_CACHE_DIR / f'settled_events_{series_ticker}.json'
        except Exception:
            cache_path = None

        logger = logging.getLogger(__name__)
        cached: list[str] = []
        if cache_path and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
            except Exception:
                cached = []

        first_resp = self.get(f'/trade-api/v2/events?series_ticker={series_ticker}&status=settled&limit=200')
        first_page = [e['event_ticker'] for e in first_resp.get('events', [])]

        if cached and all(t in set(cached) for t in first_page):
            return cached

        event_tickers = list(first_page)
        cursor = first_resp.get('cursor', '')
        while cursor:
            resp = self.get(f'/trade-api/v2/events?series_ticker={series_ticker}&status=settled&limit=200&cursor={cursor}')
            for e in resp.get('events', []):
                event_tickers.append(e['event_ticker'])
            cursor = resp.get('cursor', '')

        if cache_path:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(event_tickers))
            except Exception:
                pass

        return event_tickers

    def get_market_by_ticker(self, ticker) -> Market:
        market = self.get(self.markets_url + "?tickers=" + ticker)
        return Market(market['markets'][0])

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
