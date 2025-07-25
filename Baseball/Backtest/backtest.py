import logging
import pandas as pd
import statsapi
import Infrastructure.Clients.get_clients as get_clients
import Baseball.date_helpers as date_helpers
from Baseball.BaseballGame import market_to_game
from Baseball.Backtest.BacktestRunner import BacktestRunner
from Baseball.Strategies.backtest_strategies import SimpleBacktestStrategy, ConservativeBacktestStrategy, AggressiveValueStrategy
from Baseball.analyze_database import BacktestAnalyzer
from Baseball.Backtest.game_data_pre_loaders import preload_game_data


logging.basicConfig(level=logging.INFO)

# TODO
# Loop through all Kalshi games
# Get actual game start timestamp so that backtest doesn't have to loop through pre-start timestamps
# Get all timestamps in bulk to greatly speed up backtest?
# Implement sqllite for analysis

def main():
    # Strategy selection
    strategies = {
        '1': ('Simple', SimpleBacktestStrategy),
        '2': ('Conservative', ConservativeBacktestStrategy), 
        '3': ('AggressiveValue', AggressiveValueStrategy)
    }
    
    print("Available strategies:")
    for key, (name, _) in strategies.items():
        print(f"{key}: {name}")
    
    choice = input("Select strategy (1-3, or 'all' for all strategies): ").strip()
    
    if choice.lower() == 'all':
        selected_strategies = list(strategies.values())
    elif choice in strategies:
        selected_strategies = [strategies[choice]]
    else:
        print("Invalid choice, using Simple strategy")
        selected_strategies = [strategies['1']]
    
    print(f"Running backtest with {len(selected_strategies)} strategy(ies)")
    
    http_client = get_clients.get_http_client()
    all_markets = http_client.get_markets(['KXMLBGAME'], status="settled")
    all_markets = dict(reversed(list(all_markets.items())))

    for strategy_name, strategy_class in selected_strategies:
        print(f"\n=== Running {strategy_name} Strategy ===")
        
        for market in list(all_markets.values())[20:]:
            try:
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

                # Pre-load all game data using multiprocessing
                game_data_cache = preload_game_data(game.game_id, timestamps)

                strategy = strategy_class()

                backtest = BacktestRunner(game, market, http_client, strategy)
                backtest.run(timestamps, game_data_cache)

                print(f"Done with {strategy_name} backtest for game:", game.home_team_abv, "vs", game.away_team_abv)
                
                if list(all_markets.values()).index(market) >= 2000:
                    input("Paused after 2000 markets.")
            except Exception as e:
                logging.error(f"Error backtesting market {market.ticker} with {strategy_name} strategy: {e}")

    # Analyze backtest results using BacktestAnalyzer
    analyzer = BacktestAnalyzer()
    analyzer.database_summary()
    analyzer.compare_strategies()
    analyzer.analyze_model_versions()
    analyzer.plot_calibration_curve()

if __name__ == "__main__":
    main()
