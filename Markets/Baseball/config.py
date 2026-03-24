"""Baseball market configuration."""

from pathlib import Path

SERIES_TICKER = "KXMLBGAME"
MARKET_TYPE = "baseball"

# Strategy defaults
DEFAULT_INITIAL_CASH = 100.0
DEFAULT_POSITION_LIMITS = (-10, 10)
DEFAULT_TRADE_COOLDOWN_MINUTES = 10

# Disk cache location for MLB game data
GAME_CACHE_DIR = Path(r"D:\Code\Kalshi\Baseball")
