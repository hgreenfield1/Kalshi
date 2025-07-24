import logging
import pandas as pd
import statsapi
import Infrastructure.Clients.get_clients as get_clients
import Baseball.date_helpers as date_helpers
from Baseball.BaseballGame import market_to_game
from Baseball.Backtest.BacktestRunner import BacktestRunner
from Baseball.Strategies.backtest_strategies import SimpleBacktestStrategy
from Baseball.Backtest.analyze import plot_calibration_curve


logging.basicConfig(level=logging.INFO)

# TODO
# Loop through all Kalshi games
# Get actual game start timestamp so that backtest doesn't have to loop through pre-start timestamps
# Get all timestamps in bulk to greatly speed up backtest?
# Implement sqllite for analysis

def main():
    prediction_path = "probability_predictions_v7.csv"
    http_client = get_clients.get_http_client()
    all_markets = http_client.get_markets(['KXMLBGAME'], status="settled")
    all_markets = dict(reversed(list(all_markets.items())))

    for market in list(all_markets.values())[50:]:
        game = market_to_game(market)
        if market.ticker.split('-')[-1] != game.home_team_abv:
            continue

        game_timestamps = statsapi.get('game_timestamps', {'gamePk': game.game_id})
        start_time = game_timestamps[2]
        end_time = game_timestamps[-1]
        timestamps = date_helpers.get_backtest_timestamps(start_time, end_time)
        
        schedule = statsapi.schedule(game_id=game.game_id)
        status = schedule[0]['status']
        if status != "Final":
            logging.info(f"Skipping backtest for {game.home_team_abv} vs {game.away_team_abv} because the game is not final.")
            continue

        strategy = SimpleBacktestStrategy(prediction_path=prediction_path)

        backtest = BacktestRunner(game, market, http_client, strategy)
        backtest.run(timestamps)

        print("Done with backtest for game:", game.home_team_abv, "vs", game.away_team_abv)
        
        if list(all_markets.values()).index(market) >= 2000:
            input("Paused after 2000 markets.")

    df = pd.read_csv(prediction_path, index_col=False)
    num_unique_games = df['game_id'].nunique()
    final_cash_sum = df.groupby('game_id')['cash'].last().sum()
    print(f"Number of unique games: {num_unique_games}")
    print(f"Sum of final cash for each game: {final_cash_sum}")
    print(f"Cash per game: {final_cash_sum/num_unique_games}")
    plot_calibration_curve(df, n_bins=20)

if __name__ == "__main__":
    main()
