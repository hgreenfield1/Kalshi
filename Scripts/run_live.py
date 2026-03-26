#!/usr/bin/env python3
"""
Live trading entry point.

Usage:
    python Scripts/run_live.py

Environment variables:
    AUTO_EXECUTE=true         Submit real orders (default: false = paper mode)
    DAILY_LOSS_LIMIT=50       Halt if daily P&L drops below -$N (default: 50)

Paper mode is the default. Set AUTO_EXECUTE=true only after validating on paper.
"""
import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from Infrastructure.Clients.get_clients import get_http_client
from Markets.Baseball.strategies import MeanReversionStrategy
from Core.scheduler import Scheduler

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
auto_execute = os.environ.get('AUTO_EXECUTE', 'false').lower() == 'true'
daily_loss_limit = float(os.environ.get('DAILY_LOSS_LIMIT', '50.0'))

# ---------------------------------------------------------------------------
# Logging (file handler is added by Scheduler; stdout handler here)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()],
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    mode = 'LIVE' if auto_execute else 'PAPER'
    logging.info(f'Starting run_live.py in {mode} mode (daily_loss_limit=${daily_loss_limit:.2f})')

    http_client = get_http_client()

    scheduler = Scheduler(
        http_client=http_client,
        strategy_class=MeanReversionStrategy,
        auto_execute=auto_execute,
        daily_loss_limit=daily_loss_limit,
    )
    scheduler.run()
