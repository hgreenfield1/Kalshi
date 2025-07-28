import logging
import statsapi
from multiprocessing import cpu_count
from concurrent.futures import ProcessPoolExecutor, TimeoutError, as_completed
import Baseball.date_helpers as date_helpers


def fetch_game_data(args):
    """Fetch game data for a single timestamp using statsapi"""
    game_id, timestamp = args
    try:
        timestamp_formatted = date_helpers.convert_utc_to_game_timestamp(timestamp)
        game_data = statsapi.get('game', {'gamePk': game_id, 'timecode': timestamp_formatted})
        return (timestamp, game_data)
    except Exception as e:
        logging.error(f"Error fetching data for game {game_id} at {timestamp}: {e}")
        return (timestamp, None)


def preload_game_data(game_id, timestamps):
    """Pre-load all game data using multiprocessing with timeout"""
    logging.info(f"Pre-loading game data for game {game_id} with {len(timestamps)} timestamps")
    
    # Create arguments for each timestamp
    args = [(game_id, timestamp) for timestamp in timestamps]
    
    game_data_cache = {}
    
    # Use ProcessPoolExecutor with timeout to handle lengthy API calls
    with ProcessPoolExecutor(max_workers=min(cpu_count(), len(timestamps))) as executor:
        # Submit all tasks
        future_to_timestamp = {executor.submit(fetch_game_data, arg): arg[1] for arg in args}
        
        # Collect results with timeout
        for future in as_completed(future_to_timestamp, timeout=300):  # 5 min total timeout
            timestamp = future_to_timestamp[future]
            try:
                result_timestamp, data = future.result(timeout=15)  # 15 sec per request
                game_data_cache[result_timestamp] = data
            except TimeoutError:
                logging.warning(f"Timeout fetching data for game {game_id} at {timestamp}")
                game_data_cache[timestamp] = None
            except Exception as e:
                logging.error(f"Exception fetching data for game {game_id} at {timestamp}: {e}")
                game_data_cache[timestamp] = None
    
    successful_loads = sum(1 for data in game_data_cache.values() if data is not None)
    logging.info(f"Successfully pre-loaded {successful_loads} game states out of {len(timestamps)} timestamps")
    return game_data_cache