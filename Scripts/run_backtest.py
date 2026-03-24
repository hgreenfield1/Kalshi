#!/usr/bin/env python3
"""Generic backtesting CLI."""
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Core.engine import BacktestEngine
from Core.execution import SimpleExecutionModel
from Core.market_filter import SeriesMarketFilter, StatusMarketFilter, CompositeMarketFilter
from Infrastructure.Clients.get_clients import get_http_client

# Import market-specific components
from Markets.Baseball.strategies import (
    FavoriteLongShotStrategy,
    MeanReversionStrategy,
)
from Markets.Baseball.config import SERIES_TICKER, MARKET_TYPE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BASEBALL_STRATEGIES = {
    '1': ('FavoriteLongShot', FavoriteLongShotStrategy),
    '2': ('MeanReversion', MeanReversionStrategy),
}

def select_strategies():
    """Interactive strategy selection."""
    print("\nAvailable Baseball Strategies:")
    for key, (name, _) in BASEBALL_STRATEGIES.items():
        print(f"  {key}. {name}")
    print("  all. Run all strategies")

    choice = input("\nSelect strategy (comma-separated for multiple): ").strip()

    if choice.lower() == 'all':
        return list(BASEBALL_STRATEGIES.values())

    selected = []
    for c in choice.split(','):
        c = c.strip()
        if c in BASEBALL_STRATEGIES:
            selected.append(BASEBALL_STRATEGIES[c])

    return selected

def main():
    # Initialize HTTP client
    http_client = get_http_client()

    # Select strategies
    strategies = select_strategies()
    if not strategies:
        print("No strategies selected. Exiting.")
        return

    print(f"\nRunning {len(strategies)} strategies")

    # Create market filter
    market_filter = CompositeMarketFilter(
        SeriesMarketFilter([SERIES_TICKER]),
        StatusMarketFilter('finalized')
    )

    # Get markets
    logging.info(f"Fetching markets for {SERIES_TICKER}...")
    all_markets = http_client.get_markets([SERIES_TICKER], status='settled')
    filtered_markets = market_filter.filter(list(all_markets.values()))

    # Filter to home team markets only (avoid duplicates)
    home_markets = [m for m in filtered_markets if m.ticker.split('-')[-1] in m.ticker.split('-')[1]]

    logging.info(f"Found {len(home_markets)} markets to backtest")

    # Ask for market range
    start_idx = int(input(f"Start index (0-{len(home_markets)-1}): ") or "0")
    end_idx = int(input(f"End index (default: all remaining): ") or str(len(home_markets)))

    markets_to_run = home_markets[start_idx:end_idx]

    # Run each strategy
    for strategy_name, strategy_class in strategies:
        print(f"\n{'='*60}")
        print(f"Running {strategy_name} strategy ({strategy_class._version})")
        print(f"{'='*60}\n")

        strategy = strategy_class()
        execution_model = SimpleExecutionModel()

        engine = BacktestEngine(
            strategy=strategy,
            market_filter=market_filter,
            execution_model=execution_model,
            http_client=http_client
        )

        results = engine.run_multiple_markets(markets_to_run, MARKET_TYPE)

        # Summary
        total_cash = sum(r.final_cash for r in results)
        avg_cash = total_cash / len(results) if results else 0
        print(f"\n{strategy_name} Summary:")
        print(f"  Markets: {len(results)}")
        print(f"  Average final cash: ${avg_cash:.2f}")
        print(f"  Total ROI: {(avg_cash - 100):.2f}%")

if __name__ == "__main__":
    main()
