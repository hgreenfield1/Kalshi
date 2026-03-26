#!/usr/bin/env python3
"""
Run a single live game engine directly (no scheduler).

Usage:
    python Scripts/run_one_game.py

Targets the NYY @ SF game in progress. Edit TICKER / GAME_ID as needed.
"""
import sys
import logging
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from Infrastructure.Clients.get_clients import get_http_client, get_websocket_client
from Infrastructure.state import TradingState
from Markets.Baseball.strategies import MeanReversionStrategy
from Markets.Baseball.domain import BaseballGame
from Core.live_engine import LiveGameEngine
import asyncio

# ---------------------------------------------------------------------------
# Game config
# ---------------------------------------------------------------------------
TICKER  = 'KXMLBGAME-26MAR252005NYYSF-SF'
GAME_ID = 823244
HOME    = 'SF'
AWAY    = 'NYY'
DATE    = '2026-03-25'
START   = '2026-03-25T20:05:00Z'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler()],
)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    http_client = get_http_client()

    logging.info(f'Fetching market: {TICKER}')
    market = http_client.get_market_by_ticker(TICKER)
    logging.info(f'Market: status={market.status}  yes_bid={market.yes_bid}  yes_ask={market.yes_ask}')

    # Shared orderbook state
    update_event = threading.Event()
    trading_state = TradingState(http_client, [TICKER])
    ws_client = get_websocket_client([TICKER], trading_state, update_event)

    def _ws_thread():
        asyncio.run(ws_client.run())

    ws = threading.Thread(target=_ws_thread, name='websocket', daemon=True)
    ws.start()
    time.sleep(2)  # let WebSocket connect and snapshot arrive

    game = BaseballGame(
        game_id=GAME_ID,
        home_team_abv=HOME,
        away_team_abv=AWAY,
        game_date=DATE,
        start_time=START,
        status='In Progress',
    )

    engine = LiveGameEngine(
        market=market,
        game=game,
        strategy=MeanReversionStrategy(),
        http_client=http_client,
        trading_state=trading_state,
        auto_execute=False,   # paper mode
        poll_interval=30,
    )

    engine.start()
    logging.info('Engine running — press Ctrl+C to stop.')

    try:
        while not engine.is_done():
            time.sleep(5)
    except KeyboardInterrupt:
        logging.info('Interrupted — halting engine.')
        engine.halt()

    logging.info(f'Done. P&L=${engine.get_realized_pnl():+.2f}')
