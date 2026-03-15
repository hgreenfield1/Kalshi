import sys
sys.path.insert(0, r"C:\Users\henry\Kalshi")

import logging
import pandas as pd
import statsapi
import Infrastructure.Clients.get_clients as get_clients
import Baseball.date_helpers as date_helpers
from Baseball.BaseballGame import market_to_game
from Baseball.Backtest.BacktestRunner import BacktestRunner
from Baseball.Strategies.backtest_strategies import SimpleBacktestStrategy, ConservativeBacktestStrategy, AggressiveValueStrategy, ReverseSteamStrategy, ChangeInValueStrategy
from Baseball.analyze_database import BacktestAnalyzer
from Baseball.Backtest.game_data_pre_loaders import preload_game_data


logging.basicConfig(level=logging.INFO)

def main():
    # ==== STRATEGY SELECTION ====
    # Define available backtest strategies
    strategies = {
        '1': ('Simple', SimpleBacktestStrategy),
        '2': ('Conservative', ConservativeBacktestStrategy), 
        '3': ('AggressiveValue', AggressiveValueStrategy),
        '4': ('ReverseSteam', ReverseSteamStrategy),
        '5': ('ChangeInValue', ChangeInValueStrategy)
    }
    
    print("Available strategies:")
    for key, (name, _) in strategies.items():
        print(f"{key}: {name}")
    
    choice = input("Select strategy (1-5, comma-separated for multiple, or 'all' for all strategies): ").strip()
    
    if choice.lower() == 'all':
        selected_strategies = list(strategies.values())
    elif ',' in choice:
        # Handle comma-separated list
        choices = [c.strip() for c in choice.split(',')]
        selected_strategies = []
        for c in choices:
            if c in strategies:
                selected_strategies.append(strategies[c])
            else:
                print(f"Invalid choice '{c}', skipping")
        if not selected_strategies:
            print("No valid strategies selected, using Simple strategy")
            selected_strategies = [strategies['1']]
    elif choice in strategies:
        selected_strategies = [strategies[choice]]
    else:
        print("Invalid choice, using Simple strategy")
        selected_strategies = [strategies['1']]
    
    print(f"Running backtest with {len(selected_strategies)} strategy(ies)")
    
    # ==== MARKET DATA RETRIEVAL ====
    # Get all settled Kalshi baseball game markets
    http_client = get_clients.get_http_client()
    all_markets = http_client.get_markets(['KXMLBGAME'], status="settled")
    all_markets = dict(reversed(list(all_markets.items())))

    # ==== MAIN BACKTEST LOOP ====
    # Outer loop: iterate through each market
    # Inner loop: run all selected strategies for each market using shared game data
    for market in list(all_markets.values())[0:1]:
        try:
            # Convert Kalshi market to baseball game object
            game = market_to_game(market)
            # Skip if market ticker doesn't match home team (likely away team market)
            if market.ticker.split('-')[-1] != game.home_team_abv:
                continue

            # Get game timestamps for backtest period
            game_timestamps = statsapi.get('game_timestamps', {'gamePk': game.game_id})
            start_time = game_timestamps[2]
            end_time = game_timestamps[-1]
            timestamps = date_helpers.get_backtest_timestamps(start_time, end_time)
            
            # Verify game is completed before backtesting
            schedule = statsapi.schedule(game_id=game.game_id)
            status = schedule[0]['status']
            if status != "Final":
                logging.info(f"Skipping backtest for {game.home_team_abv} vs {game.away_team_abv} because the game is not final.")
                continue

            # Pre-load all game data using multiprocessing (shared across all strategies)
            game_data_cache = preload_game_data(game.game_id, timestamps)

            # Run each selected strategy on this market using the shared game data
            for strategy_name, strategy_class in selected_strategies:
                strategy = strategy_class()

                backtest = BacktestRunner(game, market, http_client, strategy)
                backtest.run(timestamps, game_data_cache)

                print(f"Done with {strategy_name} backtest for game:", game.home_team_abv, "vs", game.away_team_abv)
                
        except Exception as e:
            logging.error(f"Error backtesting market {market.ticker}: {e}")

    # ==== RESULTS ANALYSIS ====
    # Analyze and display backtest results using BacktestAnalyzer
    analyzer = BacktestAnalyzer()
    analyzer.database_summary() 
    analyzer.compare_strategies()
    analyzer.analyze_model_versions()
    analyzer.plot_calibration_curve()

if __name__ == "__main__":
    main()
2