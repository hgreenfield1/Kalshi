import logging
import asyncio
import KalshiDogecoin.util.get_clients as get_clients
from KalshiDogecoin.state import TradingState
from Baseball.strategy import Strategy
from BaseballGame import market_to_game

logging.basicConfig(level=logging.INFO)


# TODO
#   Improve mid price projection
#   implement market making algorithm with inventory controls
#   build out logging for single game
#   build order placing logic
#   make sure pre-game and finished games are handled correctly in the update call()
#   make logging optional on market state functions

async def main():
    update = asyncio.Event()

    http_client = get_clients.get_http_client()
    markets = http_client.get_markets(['KXMLBGAME'])

    market_game_pairs = {market: market_to_game(market) for market in markets.values()}
    market_game_pairs = {k: v for k, v in market_game_pairs.items() if v is not None}
    market_game_pairs = {k: v for k, v in market_game_pairs.items() if v.status != 'Postponed'}

    market = list(market_game_pairs.keys())[0]
    game = market_game_pairs[market]

    trading_state = TradingState(http_client, market.ticker)
    web_client = get_clients.get_websocket_client([market.ticker], trading_state, update)
    strategy = Strategy(market, game, update, trading_state, http_client)

    web_client = asyncio.create_task(web_client.run())
    strategy = asyncio.create_task(strategy.run())

    await web_client
    await strategy


if __name__ == "__main__":
    asyncio.run(main())

