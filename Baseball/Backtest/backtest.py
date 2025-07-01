import logging
import asyncio
import statsapi
import Infrastructure.Clients.get_clients as get_clients
from Baseball.BaseballGame import market_to_game
import Baseball.Backtest.backtest_functions as bf

logging.basicConfig(level=logging.INFO)

# TODO
# Loop through all Kalshi games
# Refactor backtest_functions to use a class / clean up functions
# Implement sqllite for analysis

def main():
    update = asyncio.Event()

    http_client = get_clients.get_http_client()
    market = http_client.get_market_by_ticker('KXMLBGAME-25JUN24BOSLAA-LAA')
    game = market_to_game(market)

    game_timestamps = statsapi.get('game_timestamps', {'gamePk': game.game_id})
    start_time = game_timestamps[1]
    end_time = game_timestamps[-1]
    timestamps = bf.get_backtest_timestamps(start_time, end_time)

    backtest = bf.BacktestStrategy(game, market, http_client)
    backtest.run(timestamps)

    print("a")


if __name__ == "__main__":
    main()
