import logging
import asyncio
import Infrastructure.Clients.get_clients as get_clients
from Infrastructure.state import TradingState
from Baseball.strategy import Strategy
from Baseball.BaseballGame import market_to_game

logging.basicConfig(level=logging.INFO)

async def main():
    update = asyncio.Event()

    http_client = get_clients.get_http_client()
    market = http_client.get_market_by_ticker('KXMLBGAME-25JUN13ATHKC-KC')
    game = market_to_game(market)

    trading_state = TradingState(http_client, market.ticker)
    web_client = get_clients.get_websocket_client([market.ticker], trading_state, update)
    strategy = Strategy(market, game, update, trading_state, http_client)

    web_client = asyncio.create_task(web_client.run())
    strategy = asyncio.create_task(strategy.run())

    await web_client
    await strategy


if __name__ == "__main__":
    asyncio.run(main())

