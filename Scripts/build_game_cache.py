#!/usr/bin/env python3
"""
Build a local disk cache of MLB game data for backtesting.

Caches three things per market/game:
  {cache_dir}/game_info_{ticker}.json      - market ticker -> game metadata
  {cache_dir}/{game_id}.json.gz            - final game state (all plays)
  {cache_dir}/{game_id}_timestamps.json.gz - list of game timestamps

After a full cache build, backtesting makes zero calls to the MLB Stats API.

Usage:
    python Scripts/build_game_cache.py            # skip already-cached entries
    python Scripts/build_game_cache.py --force    # re-fetch everything
"""
import sys
import gzip
import json
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import statsapi
from Infrastructure.Clients.get_clients import get_http_client
from Core.market_filter import SeriesMarketFilter, StatusMarketFilter, CompositeMarketFilter
from Markets.Baseball.domain import market_to_game, BaseballGame
from Markets.Baseball.config import SERIES_TICKER, GAME_CACHE_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def build_game_cache(cache_dir: Path = GAME_CACHE_DIR, force_refresh: bool = False):
    """
    Cache all MLB game data needed for backtesting.

    Args:
        cache_dir: Directory to store cached files.
        force_refresh: If True, re-fetch and overwrite existing cache files.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Fetch all settled markets
    logging.info(f"Fetching settled markets for {SERIES_TICKER}...")
    http_client = get_http_client()
    all_markets = http_client.get_markets([SERIES_TICKER], status='settled')

    market_filter = CompositeMarketFilter(
        SeriesMarketFilter([SERIES_TICKER]),
        StatusMarketFilter('finalized')
    )
    filtered = market_filter.filter(list(all_markets.values()))
    home_markets = [m for m in filtered if m.ticker.split('-')[-1] in m.ticker.split('-')[1]]
    logging.info(f"Found {len(home_markets)} markets")

    # --- Pass 1: cache game_info per market ticker ---
    logging.info("Pass 1/3: Caching game info (market ticker -> game metadata)...")
    game_ids = {}  # game_id -> ticker
    info_cached = info_skipped = info_failed = 0

    for i, market in enumerate(home_markets, 1):
        info_file = cache_dir / f"game_info_{market.ticker}.json"

        if info_file.exists() and not force_refresh:
            # Load from cache to populate game_ids
            with open(info_file) as f:
                info = json.load(f)
            if info['game_id'] not in game_ids:
                game_ids[info['game_id']] = market.ticker
            info_skipped += 1
            continue

        try:
            game = market_to_game(market)
            if not game:
                info_failed += 1
                continue
            with open(info_file, 'w') as f:
                json.dump({
                    'game_id': game.game_id,
                    'home_team': game.home_team_abv,
                    'away_team': game.away_team_abv,
                    'game_date': game.game_date,
                    'game_datetime': game.start_time,
                    'status': game.status
                }, f)
            if game.game_id not in game_ids:
                game_ids[game.game_id] = market.ticker
            info_cached += 1
            if i % 100 == 0:
                logging.info(f"  [{i}/{len(home_markets)}] game info cached")
        except Exception as e:
            info_failed += 1
            logging.warning(f"  Could not resolve game for {market.ticker}: {e}")

    logging.info(f"Pass 1 done. Cached: {info_cached}, Skipped: {info_skipped}, Failed: {info_failed}")
    logging.info(f"Found {len(game_ids)} unique games")

    # --- Pass 2: cache final game state ---
    logging.info("Pass 2/3: Caching final game state (play-by-play)...")
    data_cached = data_skipped = data_failed = 0

    for i, (game_id, ticker) in enumerate(game_ids.items(), 1):
        data_file = cache_dir / f"{game_id}.json.gz"

        if data_file.exists() and not force_refresh:
            data_skipped += 1
            continue

        try:
            game_data = statsapi.get('game', {'gamePk': game_id})
            with gzip.open(data_file, 'wt', encoding='utf-8') as f:
                json.dump(game_data, f)
            data_cached += 1
            if i % 100 == 0:
                logging.info(f"  [{i}/{len(game_ids)}] game data cached")
        except Exception as e:
            data_failed += 1
            logging.error(f"  Failed to cache game data {game_id}: {e}")

    logging.info(f"Pass 2 done. Cached: {data_cached}, Skipped: {data_skipped}, Failed: {data_failed}")

    # --- Pass 3: cache game timestamps ---
    logging.info("Pass 3/3: Caching game timestamps...")
    ts_cached = ts_skipped = ts_failed = 0

    for i, (game_id, ticker) in enumerate(game_ids.items(), 1):
        ts_file = cache_dir / f"{game_id}_timestamps.json.gz"

        if ts_file.exists() and not force_refresh:
            ts_skipped += 1
            continue

        try:
            timestamps = statsapi.get('game_timestamps', {'gamePk': game_id})
            timestamps = [ts for ts in timestamps if ts]
            with gzip.open(ts_file, 'wt', encoding='utf-8') as f:
                json.dump(timestamps, f)
            ts_cached += 1
            if i % 100 == 0:
                logging.info(f"  [{i}/{len(game_ids)}] timestamps cached")
        except Exception as e:
            ts_failed += 1
            logging.error(f"  Failed to cache timestamps for game {game_id}: {e}")

    logging.info(f"Pass 3 done. Cached: {ts_cached}, Skipped: {ts_skipped}, Failed: {ts_failed}")
    logging.info("Cache build complete. Backtesting will make zero MLB Stats API calls.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build MLB game data cache")
    parser.add_argument('--force', action='store_true', help="Re-fetch and overwrite existing cache files")
    parser.add_argument('--cache-dir', type=Path, default=GAME_CACHE_DIR, help=f"Cache directory (default: {GAME_CACHE_DIR})")
    args = parser.parse_args()

    build_game_cache(cache_dir=args.cache_dir, force_refresh=args.force)
