"""
LiveOrderExecutor: routes orders to the Kalshi API or paper-trade log.

Paper mode (auto_execute=False):
  - Logs the intended order with [PAPER] prefix
  - Updates the portfolio at bid/ask (same fill assumption as backtest)

Live mode (auto_execute=True):
  - POSTs to Kalshi /portfolio/orders endpoint
  - Retries once on transient failure (2s delay)
  - Updates portfolio at actual fill price from API response
  - Logs slippage vs intended limit price
"""

import uuid
import time
import logging
from typing import Optional

from Core.strategy import Order, OrderSide
from Core.portfolio import Portfolio
from Infrastructure.Clients.http_client import KalshiHttpClient


class LiveOrderExecutor:
    ORDER_ENDPOINT = '/trade-api/v2/portfolio/orders'

    def __init__(self, http_client: KalshiHttpClient, auto_execute: bool = False):
        self.http_client = http_client
        self.auto_execute = auto_execute
        self._logger = logging.getLogger('order_executor')

    def execute(
        self,
        order: Order,
        ticker: str,
        portfolio: Portfolio,
        bid: float,
        ask: float,
    ) -> bool:
        """
        Execute an order. Updates portfolio and returns True on success.
        Works identically in paper and live mode from the strategy's perspective.
        """
        if not self.auto_execute:
            return self._paper_execute(order, ticker, portfolio, bid, ask)
        return self._live_execute(order, ticker, portfolio, bid, ask)

    # ------------------------------------------------------------------
    # Paper mode
    # ------------------------------------------------------------------

    def _paper_execute(
        self,
        order: Order,
        ticker: str,
        portfolio: Portfolio,
        bid: float,
        ask: float,
    ) -> bool:
        fill_price = ask if order.side == OrderSide.BUY else bid
        self._logger.info(
            f'[PAPER] [{ticker}] {order.side.value.upper()} {order.quantity}x '
            f'@ {fill_price:.1f}c  (limit {order.limit_price:.1f}c)'
        )
        self._update_portfolio(order, portfolio, fill_price)
        return True

    # ------------------------------------------------------------------
    # Live mode
    # ------------------------------------------------------------------

    def _live_execute(
        self,
        order: Order,
        ticker: str,
        portfolio: Portfolio,
        bid: float,
        ask: float,
    ) -> bool:
        body = self._build_order_body(order, ticker)
        self._logger.info(
            f'[LIVE] [{ticker}] Submitting {order.side.value.upper()} '
            f'{order.quantity}x @ {order.limit_price:.1f}c'
        )

        response = self._submit_with_retry(body, ticker)
        if response is None:
            return False

        filled_price = self._extract_fill_price(response, order)
        slippage = filled_price - order.limit_price
        if abs(slippage) > 0.5:
            self._logger.warning(
                f'[{ticker}] Slippage: intended {order.limit_price:.1f}c '
                f'filled {filled_price:.1f}c  ({slippage:+.1f}c)'
            )
        else:
            self._logger.info(
                f'[{ticker}] Filled {order.side.value.upper()} {order.quantity}x '
                f'@ {filled_price:.1f}c'
            )

        self._update_portfolio(order, portfolio, filled_price)
        return True

    def _build_order_body(self, order: Order, ticker: str) -> dict:
        """
        Build the Kalshi REST order body.
        Prices are integers in cents (1–99).

        NOTE: Field names match the Kalshi v2 REST API spec. Verify against
        the live API before going live (POST /trade-api/v2/portfolio/orders).
        """
        yes_price = int(round(order.limit_price))
        count = order.quantity

        base = {
            'ticker': ticker,
            'client_order_id': str(uuid.uuid4()),
            'type': 'limit',
            'side': 'yes',
            'count': count,
            'yes_price': yes_price,
            'expiration_ts': 0,
        }

        if order.side == OrderSide.BUY:
            return {**base, 'action': 'buy', 'buy_max_cost': yes_price * count}
        else:
            return {**base, 'action': 'sell', 'sell_position_floor': 0}

    def _submit_with_retry(self, body: dict, ticker: str) -> Optional[dict]:
        """POST the order to Kalshi, retrying once on transient failure."""
        for attempt in range(2):
            try:
                return self.http_client.post(self.ORDER_ENDPOINT, body)
            except Exception as e:
                if attempt == 0:
                    self._logger.warning(
                        f'[{ticker}] Order submission failed (attempt 1): {e}. Retrying in 2s.'
                    )
                    time.sleep(2)
                else:
                    self._logger.error(
                        f'[{ticker}] Order submission failed after 2 attempts: {e}. '
                        f'Portfolio NOT updated.'
                    )
        return None

    def _extract_fill_price(self, response: dict, order: Order) -> float:
        """Extract fill price from Kalshi order response. Falls back to limit price."""
        try:
            order_data = response.get('order', response)
            yes_price = order_data.get('yes_price') or order_data.get('price')
            if yes_price is not None:
                return float(yes_price)
        except Exception:
            pass
        return order.limit_price

    def _update_portfolio(self, order: Order, portfolio: Portfolio, fill_price: float) -> None:
        if order.side == OrderSide.BUY:
            portfolio.execute_buy(fill_price, order.quantity)
        else:
            portfolio.execute_sell(fill_price, order.quantity)
