import logging
import statsapi
from multiprocessing import Pool, cpu_count
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
    """Pre-load all game data using multiprocessing"""
    logging.info(f"Pre-loading game data for game {game_id} with {len(timestamps)} timestamps")
    
    # Create arguments for each timestamp
    args = [(game_id, timestamp) for timestamp in timestamps]
    
    # Use multiprocessing to fetch all data in parallel
    with Pool(processes=min(cpu_count(), len(timestamps))) as pool:
        results = pool.map(fetch_game_data, args)
    
    # Convert results to dictionary
    game_data_cache = {timestamp: data for timestamp, data in results if data is not None}
    
    logging.info(f"Successfully pre-loaded {len(game_data_cache)} game states out of {len(timestamps)} timestamps")
    return game_data_cache