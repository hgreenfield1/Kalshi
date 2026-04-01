#!/usr/bin/env python3
"""Generic backtesting CLI."""
import sys
import argparse
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
    InningAdjustedEdgeStrategy,
)
from Markets.Baseball.config import SERIES_TICKER, MARKET_TYPE

# Configure logging
_log_dir = Path(__file__).parent.parent / 'logs'
_log_dir.mkdir(exist_ok=True)
_log_file = _log_dir / f"backtest_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file),
    ]
)

BASEBALL_STRATEGIES = {
    '1': ('FavoriteLongShot', FavoriteLongShotStrategy),
    '2': ('MeanReversion', MeanReversionStrategy),
    '3': ('InningAdjustedEdge', InningAdjustedEdgeStrategy),
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
    parser = argparse.ArgumentParser(description='Run baseball strategy backtest')
    parser.add_argument('--strategy', type=str, default=None,
                        help='Strategy key (1=FavoriteLongShot, 2=MeanReversion, 3=InningAdjustedEdge, all)')
    parser.add_argument('--start', type=int, default=0, help='Start market index')
    parser.add_argument('--end', type=int, default=None, help='End market index')
    args = parser.parse_args()

    # Initialize HTTP client
    http_client = get_http_client()

    # Select strategies
    if args.strategy is not None:
        if args.strategy.lower() == 'all':
            strategies = list(BASEBALL_STRATEGIES.values())
        elif args.strategy in BASEBALL_STRATEGIES:
            strategies = [BASEBALL_STRATEGIES[args.strategy]]
        else:
            print(f"Unknown strategy '{args.strategy}'. Options: {list(BASEBALL_STRATEGIES.keys())} or 'all'")
            return
    else:
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

    # Filter to home team markets only (avoid duplicates).
    # Ticker format: KXMLBGAME-{DDMMMYY}{TEAMS}-{TEAM}
    # Home team always appears first in TEAMS (e.g. MIALAD → MIA is home).
    # A market is a home-team market when TEAM == the leading prefix of TEAMS.
    def _is_home_market(m):
        parts = m.ticker.split('-')
        if len(parts) < 3:
            return False
        # Ticker format: KXMLBGAME-{DDMMMYY}[{HHMM}]{HOMETEAM}{AWAYTEAM}-{TEAM}
        # Date is always 7 chars (DDMMMYY); time is 4 optional digits after that.
        segment = parts[1]
        offset = 11 if len(segment) > 11 and segment[7:11].isdigit() else 7
        teams_str = segment[offset:]
        team = parts[2]
        return teams_str.upper().startswith(team.upper())

    home_markets = [m for m in filtered_markets if _is_home_market(m)]
    logging.info(f"Found {len(home_markets)} markets to backtest")

    # Market range
    if args.strategy is not None:
        start_idx = args.start
        end_idx = args.end if args.end is not None else len(home_markets)
    else:
        start_idx = int(input(f"Start index (0-{len(home_markets)-1}): ") or "0")
        end_idx = int(input(f"End index (default: all remaining): ") or str(len(home_markets)))

    markets_to_run = home_markets[start_idx:end_idx]
    logging.info(f"Running on markets [{start_idx}:{end_idx}] = {len(markets_to_run)} markets")

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
