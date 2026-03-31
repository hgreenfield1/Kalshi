"""
LiveGameEngine: real-clock per-game trading loop.

Mirrors BacktestEngine but drives from wall-clock time instead of replaying
historical timestamps. One instance per game, runs in its own background thread.
The Scheduler owns the thread lifecycle (start / halt / join).

Poll cycle (every 30s):
  1. Refresh game state from statsapi (30s timeout)
  2. Fetch pregame win probability once after game goes In Progress
  3. Read bid/ask from shared WebSocket orderbook (REST fallback if empty)
  4. Build Context and call strategy.on_timestep()
  5. Execute any orders via LiveOrderExecutor
  6. Save state to disk for crash recovery
  7. Check for terminal game status → resolve and exit
"""

import os
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from Core.context import Context
from Core.domain_adapter import DomainAdapter
from Core.portfolio import Portfolio
from Core.strategy import BaseStrategy
from Infrastructure.market import Market
from Infrastructure.state import TradingState
from Infrastructure.order_executor import LiveOrderExecutor
from Infrastructure.Clients.http_client import KalshiHttpClient
from Markets.Baseball.config import DEFAULT_INITIAL_CASH

POLL_INTERVAL_SECONDS = 30
STATSAPI_TIMEOUT_SECONDS = 30
ORDERBOOK_MAX_AGE_SECONDS = 60
STATE_DIR = Path(__file__).parent.parent / 'live_state'


class LiveGameEngine:
    """
    Real-clock trading engine for a single MLB game.

    Instantiated and started by Scheduler._arm_game().
    The strategy receives a Context identical in shape to the backtest Context,
    so no strategy code needs to change between backtest and live.

    Crash recovery:
      On restart, Scheduler re-arms the game. __init__ restores portfolio and
      strategy state from the per-game JSON file in live_state/.
    """

    def __init__(
        self,
        market: Market,
        adapter: DomainAdapter,
        strategy: BaseStrategy,
        http_client: KalshiHttpClient,
        trading_state: TradingState,
        auto_execute: bool = False,
        poll_interval: int = POLL_INTERVAL_SECONDS,
    ):
        self.market = market
        self.adapter = adapter
        self.strategy = strategy
        self.http_client = http_client
        self.trading_state = trading_state
        self.auto_execute = auto_execute
        self.poll_interval = poll_interval

        self.portfolio = Portfolio(cash=DEFAULT_INITIAL_CASH)
        self.executor = LiveOrderExecutor(http_client, auto_execute)

        self._halt_flag = threading.Event()
        self._done_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Sanitise ticker for use as a filename
        safe_ticker = market.ticker.replace('/', '_')
        self._state_path = STATE_DIR / f'game_{safe_ticker}.json'

        self._logger = logging.getLogger(f'engine.{market.ticker}')

    # ------------------------------------------------------------------
    # Public interface (called by Scheduler)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the game loop in a background thread."""
        self._thread = threading.Thread(
            target=self._run,
            name=f'engine-{self.market.ticker}',
            daemon=True,
        )
        self._thread.start()
        mode = 'LIVE' if self.auto_execute else 'PAPER'
        self._logger.info(f'Engine started [{mode}]: {self.adapter.description()}')

    def halt(self) -> None:
        """Signal the engine to exit after the current tick.

        In live mode, cancels any resting orders for this market before
        setting the halt flag to reduce the chance of fills after shutdown.
        """
        self._logger.warning('Halt requested.')
        if self.auto_execute:
            self._cancel_open_orders()
        self._halt_flag.set()

    def _cancel_open_orders(self) -> None:
        """Best-effort cancellation of all resting orders for this market ticker."""
        try:
            orders = self.http_client.get_open_orders(self.market.ticker)
            if not orders:
                return
            self._logger.info(f'Cancelling {len(orders)} resting order(s) before halt.')
            for order in orders:
                oid = order.get('order_id') or order.get('id')
                if oid:
                    cancelled = self.http_client.cancel_order(str(oid))
                    if cancelled:
                        self._logger.info(f'Cancelled order {oid}')
                    else:
                        self._logger.warning(f'Could not cancel order {oid}')
        except Exception:
            self._logger.warning('Failed to cancel open orders on halt.', exc_info=True)

    def is_done(self) -> bool:
        return self._done_flag.is_set()

    def get_realized_pnl(self) -> float:
        """Realized P&L relative to starting cash."""
        return round(self.portfolio.cash - DEFAULT_INITIAL_CASH, 2)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Entry point for the background thread."""
        try:
            self._restore_state()

            while not self._halt_flag.is_set():
                try:
                    self._tick()
                except Exception:
                    self._logger.exception('Tick error — continuing.')

                if self.adapter.is_complete():
                    self._resolve()
                    break

                # Wait for next poll (interruptible by halt)
                self._halt_flag.wait(timeout=self.poll_interval)

        except Exception:
            self._logger.exception('Unhandled exception in game loop')
        finally:
            self._done_flag.set()
            self._logger.info(
                f'Engine finished. '
                f'P&L=${self.get_realized_pnl():+.2f}  '
                f'positions={self.portfolio.positions}  '
                f'trades={len(self.portfolio.trade_history)}'
            )

    def _tick(self) -> None:
        """Single 30-second polling cycle."""
        # 1. Refresh event state from upstream source (with timeout)
        self._update_domain_state()

        # 2. Fetch pregame win probability once after event goes live
        if not self.adapter.pregame_probability_fetched and self.adapter.is_tradeable():
            self._fetch_pregame_prob()

        # 3. Refresh market REST prices (ensures bid/ask stays current even if
        #    the WebSocket orderbook drifts over a long game)
        self._refresh_market()

        # 4. Get bid/ask
        bid, ask = self._get_bid_ask()

        self._logger.info(
            f'{self.adapter.description()}  '
            f'tradeable={self.adapter.is_tradeable()}  '
            f'bid={bid}  ask={ask}  '
            f'pnl=${self.get_realized_pnl():+.2f}  pos={self.portfolio.positions}'
        )

        if not self.adapter.is_tradeable():
            return
        if bid is None or ask is None:
            self._logger.warning('No bid/ask — skipping strategy this tick.')
            return

        # 5. Build context (identical shape to backtest Context)
        context = Context(
            timestamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            market=self.market,
            bid_price=bid,
            ask_price=ask,
            portfolio_snapshot=self.portfolio.snapshot(),
            auxiliary_data=self.adapter.build_auxiliary_data(),
            metadata={
                'strategy_version': self.strategy.version,
                'auto_execute': self.auto_execute,
            },
        )

        # 5. Strategy decision
        orders = self.strategy.on_timestep(context)

        # 6. Execute
        for order in orders:
            self._logger.info(
                f'Signal: {order.side.value.upper()} {order.quantity}x '
                f'@ {order.limit_price:.1f}c'
            )
            filled = self.executor.execute(
                order, self.market.ticker, self.portfolio, bid, ask,
                position_limits=getattr(self.strategy, 'position_limits', None),
            )
            if filled:
                self.portfolio.trade_history[-1]['ts'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # 7. Persist state after any trade
        if orders:
            self._save_state()

    def _resolve(self) -> None:
        """Close all open positions and notify strategy of outcome."""
        bid, ask = self._get_bid_ask()

        if self.portfolio.positions != 0:
            if bid is not None and ask is not None:
                self._logger.info(
                    f'Closing {self.portfolio.positions} open contract(s) at resolution.'
                )
                self.portfolio.close_all_positions(bid, ask)
            else:
                self._logger.warning(
                    'Event resolved but no bid/ask available. '
                    f'{self.portfolio.positions} contract(s) may remain open on Kalshi.'
                )

        outcome = self.adapter.get_outcome()
        context = Context(
            timestamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            market=self.market,
            bid_price=bid,
            ask_price=ask,
            portfolio_snapshot=self.portfolio.snapshot(),
            auxiliary_data=self.adapter.build_auxiliary_data(),
        )
        self.strategy.on_resolution(context, outcome)

        self._logger.info(
            f'RESOLVED: {self.adapter.description()}  '
            f'outcome={"YES" if outcome else "NO"}  '
            f'P&L=${self.get_realized_pnl():+.2f}'
        )
        self._save_state()

    # ------------------------------------------------------------------
    # Pregame probability
    # ------------------------------------------------------------------

    def _fetch_pregame_prob(self) -> None:
        """
        Fetch the opening Kalshi market price via the adapter.
        Called once when the event first transitions to a tradeable state.
        """
        try:
            self.adapter.fetch_pregame_probability(self.market, self.http_client)
            self._logger.info('Pre-event probability fetched.')
        except Exception:
            self._logger.warning('Failed to fetch pre-event probability.', exc_info=True)
            # Mark as fetched so we don't retry every tick; adapter must handle
            # the missing value internally (e.g. fall back to 50%).

    # ------------------------------------------------------------------
    # Domain state update
    # ------------------------------------------------------------------

    def _update_domain_state(self) -> None:
        """
        Call adapter.update() with a hard timeout.
        If the upstream feed hangs, skip the tick rather than blocking the
        engine thread indefinitely.
        """
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.adapter.update)
                future.result(timeout=STATSAPI_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            self._logger.warning(
                f'Domain update timed out after {STATSAPI_TIMEOUT_SECONDS}s — '
                f'using last known state.'
            )
        except Exception as e:
            self._logger.warning(f'adapter.update() raised: {e}')

    # ------------------------------------------------------------------
    # Market refresh + bid/ask
    # ------------------------------------------------------------------

    def _refresh_market(self) -> None:
        """Re-fetch the Market object from REST to keep bid/ask current.

        Called every tick. The WebSocket orderbook can drift over long games
        (stale price levels with non-zero qty linger after partial fills),
        so the freshly fetched yes_bid/yes_ask from REST is the authoritative
        source for the 30-second polling cycle.
        """
        try:
            self.market = self.http_client.get_market_by_ticker(self.market.ticker)
        except Exception as e:
            self._logger.debug(f'Market refresh failed: {e}')

    def _get_bid_ask(self) -> tuple[Optional[float], Optional[float]]:
        """
        Return best bid/ask in cents.

        Primary source: Market REST prices (refreshed each tick via _refresh_market).
        Fallback: WebSocket orderbook (useful when REST is unavailable).
        """
        # Primary: REST prices from the freshly refreshed Market object
        if self.market.yes_bid is not None and self.market.yes_ask is not None:
            bid = round(float(self.market.yes_bid) * 100)
            ask = round(float(self.market.yes_ask) * 100)
            if ask > 0:
                return float(bid), float(ask)

        # Fallback: WebSocket orderbook (only if data is fresh enough)
        ob = self.trading_state.orderbooks.get(self.market.ticker)
        if ob and ob.bids and ob.asks:
            if ob.last_updated_at is not None:
                age = (datetime.now(timezone.utc) - ob.last_updated_at).total_seconds()
                if age > ORDERBOOK_MAX_AGE_SECONDS:
                    self._logger.warning(
                        f'WebSocket orderbook stale ({age:.0f}s old) — skipping fallback.'
                    )
                    return None, None
            self._logger.debug('REST prices unavailable — using WebSocket orderbook.')
            return float(max(ob.bids.keys())), float(min(ob.asks.keys()))

        return None, None

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Atomically write engine state to disk for crash recovery."""
        state = {
            'ticker': self.market.ticker,
            'portfolio': {
                'cash': self.portfolio.cash,
                'positions': self.portfolio.positions,
                'trade_history': self.portfolio.trade_history,
            },
            'strategy_state': self.strategy.save_state(),
            'saved_at': datetime.now(timezone.utc).isoformat(),
        }
        tmp = self._state_path.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
            os.replace(tmp, self._state_path)
        except Exception:
            self._logger.exception('Failed to save engine state')

    def _restore_state(self) -> None:
        """
        Reload engine state from disk.
        Called at thread start — if a state file exists, we crashed mid-game
        and need to resume with the correct portfolio and strategy windows.
        """
        if not self._state_path.exists():
            return

        try:
            data = json.loads(self._state_path.read_text(encoding='utf-8'))
        except Exception:
            self._logger.exception('State file unreadable. Starting fresh.')
            return

        if data.get('ticker') != self.market.ticker:
            self._logger.warning(
                f'State file ticker {data.get("ticker")} != {self.market.ticker}. Ignoring.'
            )
            return

        port = data.get('portfolio', {})
        self.portfolio.cash = port.get('cash', DEFAULT_INITIAL_CASH)
        self.portfolio.positions = port.get('positions', 0)
        self.portfolio.trade_history = port.get('trade_history', [])

        strat_state = data.get('strategy_state', {})
        if strat_state:
            self.strategy.restore_state(strat_state)

        self._logger.warning(
            f'Crash recovery: cash={self.portfolio.cash:.2f}  '
            f'positions={self.portfolio.positions}  '
            f'trades={len(self.portfolio.trade_history)}'
        )

        if self.auto_execute:
            self._reconcile_account()

    def _reconcile_account(self) -> None:
        """
        Compare the restored portfolio cash against the actual Kalshi account
        balance. On significant divergence, halt the engine to prevent trading
        on stale state.

        The Kalshi balance endpoint returns {"balance": <integer cents>}.
        A divergence > $1.00 is treated as a reconciliation failure.
        """
        try:
            resp = self.http_client.get_balance()
            balance_cents = resp.get('balance')
            if balance_cents is None:
                self._logger.warning(
                    'Account reconciliation: balance key missing from API response %s', resp
                )
                return
            actual_cash = balance_cents / 100.0
            delta = abs(actual_cash - self.portfolio.cash)
            if delta > 1.0:
                self._logger.critical(
                    f'Account reconciliation MISMATCH: '
                    f'Kalshi=${actual_cash:.2f}  portfolio=${self.portfolio.cash:.2f}  '
                    f'delta=${delta:.2f}. Halting to prevent trading on stale state.'
                )
                self._halt_flag.set()
            else:
                self._logger.info(
                    f'Account reconciliation OK: Kalshi=${actual_cash:.2f}  '
                    f'portfolio=${self.portfolio.cash:.2f}'
                )
        except Exception:
            self._logger.warning('Account reconciliation failed — proceeding with caution.', exc_info=True)
