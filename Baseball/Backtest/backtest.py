import logging
import asyncio
import statsapi
import Infrastructure.Clients.get_clients as get_clients
import Baseball.date_helpers as date_helpers
from Baseball.BaseballGame import market_to_game
from Baseball.Backtest.BacktestRunner import BacktestRunner
from Baseball.Strategies.backtest_strategies import SimpleBacktestStrategy


logging.basicConfig(level=logging.INFO)

# TODO
# Loop through all Kalshi games
# Get actual game start timestamp so that backtest doesn't have to loop through pre-start timestamps
# Get all timestamps in bulk to greatly speed up backtest?
# Implement sqllite for analysis

def main():
    http_client = get_clients.get_http_client()
    #market = http_client.get_market_by_ticker('KXMLBGAME-25JUN24BOSLAA-LAA')
    #game = market_to_game(market)
    all_markets = http_client.get_markets(['KXMLBGAME'], status="settled")

    for market in all_markets.values():
        game = market_to_game(market)
        if market.ticker.split('-')[-1] != game.home_team_abv:
            continue

        game_timestamps = statsapi.get('game_timestamps', {'gamePk': game.game_id})
        start_time = game_timestamps[1]
        end_time = game_timestamps[-1]
        timestamps = date_helpers.get_backtest_timestamps(start_time, end_time)
        
        strategy = SimpleBacktestStrategy()

        backtest = BacktestRunner(game, market, http_client, strategy)
        backtest.run(timestamps)

        print("Done with backtest for game:", game.home_team_abv, "vs", game.away_team_abv)
        
        if all_markets.values().index(market) == 24:
            input("Paused after 25 markets.")


if __name__ == "__main__":
    main()
