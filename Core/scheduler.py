"""
Scheduler for live MLB trading.

Responsibilities:
  - Load today's MLB schedule and discover matching Kalshi markets
  - Manage LiveGameEngine lifecycle: arm 5 min before first pitch,
    finalize after game ends
  - Persist state to disk every 30s for crash recovery
  - Enforce daily loss limits across all running engines
"""

import asyncio
import os
import json
import time
import logging
import threading
import statsapi
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from Infrastructure.market import Market
from Infrastructure.state import TradingState
from Infrastructure.Clients.http_client import KalshiHttpClient
from Infrastructure.Clients.get_clients import get_websocket_client
from Markets.Baseball.utils import mlb_teams
from Markets.Baseball.config import SERIES_TICKER


# ---------------------------------------------------------------------------
# Reverse team lookup: statsapi full name → Kalshi abbreviation
# ---------------------------------------------------------------------------
# Where multiple abbreviations exist for the same team, prefer the one listed
# in _PREFERRED_ABBREVS (e.g. ARI over AZ for Arizona Diamondbacks).
# Kalshi uses AZ (not ARI) for the Diamondbacks — leave empty to use mlb_teams insertion order,
# where AZ appears before ARI so it wins by default.
_PREFERRED_ABBREVS: dict[str, str] = {}

_full_to_abbv: dict[str, str] = {}
for _abbv, _full in mlb_teams.items():
    # Add if not seen yet, or if this is the preferred abbreviation for this team
    if _full not in _full_to_abbv or (
        _full in _PREFERRED_ABBREVS and _PREFERRED_ABBREVS[_full] == _abbv
    ):
        _full_to_abbv[_full] = _abbv


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STATE_DIR = Path(__file__).parent.parent / 'live_state'
LOG_DIR = Path(__file__).parent.parent / 'logs'
ARM_OFFSET_MINUTES = 5
LOOP_INTERVAL_SECONDS = 30

# statsapi statuses that mean the game is no longer actionable
_FINISHED_STATUSES = {'Final', 'Game Over', 'Postponed', 'Cancelled', 'Suspended', 'Completed Early'}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GameScheduleEntry:
    """All per-game metadata that the scheduler tracks."""
    game_id: int
    market_ticker: str        # e.g. KXMLBGAME-01APR26NYYNYM-NYY, or '' if not found
    home_team: str            # 3-letter Kalshi abbreviation
    away_team: str            # 3-letter Kalshi abbreviation
    game_num: int             # 1 or 2 for doubleheaders
    scheduled_start: datetime  # UTC first-pitch time
    arm_time: datetime        # scheduled_start - ARM_OFFSET_MINUTES
    status: str               # 'pending' | 'armed' | 'running' | 'done' | 'skipped' | 'no_market'
    engine: Optional[Any] = field(default=None, repr=False)  # LiveGameEngine when armed

    def to_dict(self) -> dict:
        return {
            'game_id': self.game_id,
            'market_ticker': self.market_ticker,
            'home_team': self.home_team,
            'away_team': self.away_team,
            'game_num': self.game_num,
            'scheduled_start': self.scheduled_start.isoformat(),
            'arm_time': self.arm_time.isoformat(),
            'status': self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'GameScheduleEntry':
        return cls(
            game_id=d['game_id'],
            market_ticker=d['market_ticker'],
            home_team=d['home_team'],
            away_team=d['away_team'],
            game_num=d['game_num'],
            scheduled_start=datetime.fromisoformat(d['scheduled_start']),
            arm_time=datetime.fromisoformat(d['arm_time']),
            status=d['status'],
        )


class _GameLogAdapter(logging.LoggerAdapter):
    """Prefixes log messages with [TICKER] for per-game context."""
    def process(self, msg, kwargs):
        ticker = self.extra.get('ticker', '')
        prefix = f'[{ticker}] ' if ticker else ''
        return f'{prefix}{msg}', kwargs


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """
    Daily orchestrator for live MLB trading.

    Lifecycle:
      1. Attempt crash recovery from today's state file
      2. Load today's MLB schedule; discover Kalshi markets
      3. Main loop (every 30s):
           - Arm engines ARM_OFFSET_MINUTES before each first pitch
           - Poll running engines for completion
           - Enforce daily loss limit
           - Save state to disk
      4. Exit when all games are done / halted

    Usage:
        scheduler = Scheduler(http_client, MeanReversionStrategy,
                              auto_execute=False, daily_loss_limit=50.0)
        scheduler.run()

    Environment:
        AUTO_EXECUTE=true   — submit real orders (default: false, paper mode)
        DAILY_LOSS_LIMIT=50 — halt threshold in dollars
    """

    def __init__(
        self,
        http_client: KalshiHttpClient,
        strategy_class,
        auto_execute: bool = False,
        daily_loss_limit: float = 50.0,
    ):
        self.http_client = http_client
        self.strategy_class = strategy_class
        self.auto_execute = auto_execute
        self.daily_loss_limit = daily_loss_limit

        self.entries: list[GameScheduleEntry] = []
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._daily_pnl = 0.0
        self._date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        self._trading_state: Optional[TradingState] = None
        self._ws_thread: Optional[threading.Thread] = None

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._state_path = STATE_DIR / f'scheduler_{self._date_str}.json'

        self._logger = logging.getLogger('scheduler')
        self._setup_file_logging()

    # ------------------------------------------------------------------
    # Logging setup
    # ------------------------------------------------------------------

    def _setup_file_logging(self) -> None:
        """Add a daily log file handler to the root logger."""
        log_path = LOG_DIR / f'live_{self._date_str}.log'
        handler = logging.FileHandler(log_path, encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
        root = logging.getLogger()
        # Avoid adding a duplicate handler if _setup_file_logging is called twice
        if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == str(log_path) for h in root.handlers):
            root.addHandler(handler)
        self._logger.info(f'Log file: {log_path}')

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Blocking main loop. Returns when all games are done or the scheduler is halted."""
        mode = 'LIVE' if self.auto_execute else 'PAPER'
        self._logger.info(
            f'Scheduler starting — date={self._date_str}  mode={mode}  '
            f'daily_loss_limit=${self.daily_loss_limit:.2f}'
        )

        recovered = self._recover_state()
        if not recovered:
            self._load_todays_schedule()

        if not self.entries:
            self._logger.info('No games to track today. Exiting.')
            return

        self._start_websocket()

        actionable = [e for e in self.entries if e.status not in ('done', 'no_market', 'skipped')]
        self._logger.info(
            f'Tracking {len(self.entries)} game(s) total, {len(actionable)} actionable: '
            + ', '.join(
                f'{e.away_team}@{e.home_team} ({e.scheduled_start.strftime("%H:%M")} UTC)'
                for e in actionable
            )
        )

        try:
            self._main_loop()
        except KeyboardInterrupt:
            self._logger.warning('Interrupted by user. Halting all engines.')
            self._halt_all()
        except Exception:
            self._logger.exception('Unhandled exception in scheduler main loop')
            self._halt_all()
            raise

    def halt(self) -> None:
        """Signal the scheduler and all running engines to stop."""
        self._logger.warning('External halt requested.')
        self._halt.set()
        self._halt_all()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _main_loop(self) -> None:
        _terminal = {'done', 'skipped', 'no_market'}

        while not self._halt.is_set():
            now = datetime.now(timezone.utc)

            with self._lock:
                for entry in self.entries:
                    if entry.status == 'pending' and now >= entry.arm_time:
                        self._arm_game(entry)
                    elif entry.status == 'running' and entry.engine is not None:
                        if entry.engine.is_done():
                            self._finalize_game(entry)

                self._update_daily_pnl()
                self._check_daily_loss_limit()
                self._save_state()

            if all(e.status in _terminal for e in self.entries):
                self._logger.info(
                    f'All {len(self.entries)} game(s) resolved. '
                    f'Daily P&L: ${self._daily_pnl:+.2f}'
                )
                break

            time.sleep(LOOP_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Schedule loading
    # ------------------------------------------------------------------

    def _load_todays_schedule(self) -> None:
        """Fetch today's MLB schedule from statsapi and discover Kalshi markets."""
        today = datetime.now(timezone.utc).strftime('%m/%d/%Y')
        self._logger.info(f'Fetching MLB schedule for {today}')

        try:
            games = statsapi.schedule(today)
        except Exception:
            self._logger.exception('statsapi.schedule() failed')
            return

        self._logger.info(f'statsapi returned {len(games)} game(s)')

        for game in games:
            entry = self._parse_schedule_entry(game)
            if entry is None:
                continue
            label = entry.market_ticker or f'{entry.away_team}@{entry.home_team}'
            log = _GameLogAdapter(self._logger, {'ticker': label})
            if entry.status == 'no_market':
                log.warning(
                    f'No Kalshi market found for game_id={entry.game_id} '
                    f'({entry.away_team} @ {entry.home_team}). Will not trade.'
                )
            else:
                log.info(
                    f'Discovered: {entry.away_team} @ {entry.home_team}  '
                    f'first_pitch={entry.scheduled_start.strftime("%H:%M")} UTC  '
                    f'arm_at={entry.arm_time.strftime("%H:%M")} UTC'
                )
            self.entries.append(entry)

    def _parse_schedule_entry(self, game: dict) -> Optional[GameScheduleEntry]:
        """
        Convert a raw statsapi schedule dict to a GameScheduleEntry.
        Returns None for games that are already finished or unparseable.
        """
        if game.get('status') in _FINISHED_STATUSES:
            return None

        try:
            home_full = game['home_name']
            away_full = game['away_name']
            home_abv = _full_to_abbv.get(home_full)
            away_abv = _full_to_abbv.get(away_full)

            if not home_abv or not away_abv:
                self._logger.warning(
                    f'Unknown team: home="{home_full}" away="{away_full}" '
                    f'(game_id={game.get("game_id")}). Skipping.'
                )
                return None

            # Parse first-pitch time (UTC)
            game_dt_str = game.get('game_datetime', '')
            if game_dt_str:
                scheduled_start = datetime.fromisoformat(
                    game_dt_str.replace('Z', '+00:00')
                ).astimezone(timezone.utc)
            else:
                # Fallback: use midnight UTC on the game date
                date_str = game.get('game_date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
                yr, mo, day = map(int, date_str.split('-'))
                scheduled_start = datetime(yr, mo, day, tzinfo=timezone.utc)
                self._logger.warning(
                    f'game_id={game.get("game_id")} has no game_datetime. '
                    f'Arm time will be approximate.'
                )

            # statsapi 'game_date' is the US local calendar date of the game (YYYY-MM-DD).
            # Kalshi uses this date (not the UTC date) in the ticker. We always prefer it
            # over deriving the date from the UTC game_datetime (which can be a day ahead
            # for late-evening west coast games).
            local_game_date_str = game.get('game_date') or scheduled_start.strftime('%Y-%m-%d')

            game_num = game.get('game_num', 1)
            arm_time = scheduled_start - timedelta(minutes=ARM_OFFSET_MINUTES)

            market_ticker = self._discover_kalshi_ticker(
                home_abv, away_abv, local_game_date_str, scheduled_start, game_num
            )

            return GameScheduleEntry(
                game_id=game['game_id'],
                market_ticker=market_ticker or '',
                home_team=home_abv,
                away_team=away_abv,
                game_num=game_num,
                scheduled_start=scheduled_start,
                arm_time=arm_time,
                status='pending' if market_ticker else 'no_market',
            )

        except Exception:
            self._logger.exception(f'Failed to parse schedule entry: {game}')
            return None

    # ------------------------------------------------------------------
    # Kalshi market discovery
    # ------------------------------------------------------------------

    def _discover_kalshi_ticker(
        self,
        home_abv: str,
        away_abv: str,
        local_game_date_str: str,
        scheduled_start_utc: datetime,
        game_num: int,
    ) -> Optional[str]:
        """
        Resolve the Kalshi market ticker for a game.

        Ticker format (2026+): KXMLBGAME-{YYMMMDD}{HHMM}{HOME}{AWAY}-{HOME}
        The {HHMM} is the game time, which we don't know ahead of time, so
        direct lookup is unlikely to succeed. The fallback series search is
        the primary discovery path.

        We try two candidate dates:
          1. US local game date from statsapi 'game_date' (e.g. "26MAR27")
          2. UTC date from game_datetime (e.g. "26MAR28") — for late-night games
             that cross midnight UTC
        """
        from datetime import date as date_type

        local_date = datetime.strptime(local_game_date_str, '%Y-%m-%d').date()
        utc_date = scheduled_start_utc.date()

        local_date_str = local_date.strftime('%y%b%d').upper()   # e.g. "26MAR27"
        utc_date_str = utc_date.strftime('%y%b%d').upper()       # e.g. "26MAR28"

        # Deduplicate if both dates are the same
        date_strs = [local_date_str]
        if utc_date_str != local_date_str:
            date_strs.append(utc_date_str)

        teams = f'{home_abv}{away_abv}'
        g2_suffixes = ['G2', '2'] if game_num == 2 else ['']

        # Direct lookup (works for old-format tickers without time component)
        for date_str in date_strs:
            for suffix in g2_suffixes:
                candidate = f'{SERIES_TICKER}-{date_str}{teams}{suffix}-{home_abv}'
                try:
                    market = self.http_client.get_market_by_ticker(candidate)
                    if market:
                        self._logger.debug(f'Direct lookup succeeded: {candidate}')
                        return candidate
                except Exception:
                    pass

        # Fallback: search open markets (handles the {HHMM} time component in new tickers)
        self._logger.debug(
            f'Direct lookup failed for {home_abv} vs {away_abv}. '
            f'Trying series search (dates tried: {date_strs}).'
        )
        return self._search_open_markets(home_abv, away_abv, date_strs, game_num)

    def _search_open_markets(
        self,
        home_abv: str,
        away_abv: str,
        date_strs: list[str],
        game_num: int,
    ) -> Optional[str]:
        """
        Search all open KXMLBGAME markets and match by date + team abbreviations.

        For each matching ticker we check that:
          - One of the candidate date strings is present
          - Both team abbreviations are present in the ticker
          - The ticker ends with -{home_abv} (ensures we get the home-team contract
            and not the away-team variant of the same game)
          - Doubleheader game 2 tickers contain 'G2' or end with a digit before the home suffix
        """
        try:
            markets = self.http_client.get_markets(SERIES_TICKER, status='open')
        except Exception:
            self._logger.exception('get_markets() failed during fallback search')
            return None

        matches = []
        for ticker in markets:
            upper = ticker.upper()
            if not any(d in upper for d in date_strs):
                continue
            if home_abv not in upper or away_abv not in upper:
                continue
            if not ticker.endswith(f'-{home_abv}'):
                continue
            is_dh_g2 = 'G2' in upper
            if game_num == 2 and not is_dh_g2:
                continue
            if game_num != 2 and is_dh_g2:
                continue
            matches.append(ticker)

        if len(matches) == 1:
            self._logger.info(
                f'Fallback search matched: {matches[0]} '
                f'(home={home_abv} away={away_abv} dates={date_strs})'
            )
            return matches[0]

        if len(matches) > 1:
            self._logger.warning(
                f'Ambiguous match for {home_abv} vs {away_abv}: {matches}. '
                f'Using first result.'
            )
            return matches[0]

        # Date-filtered search found nothing. Try team-name-only search as last resort.
        # This handles cases where Kalshi's ticker date encoding doesn't match our expectation
        # (e.g. a 2025-dated market reused for a 2026 game, or date encoding edge cases).
        return self._search_open_markets_by_teams(home_abv, away_abv, game_num, markets)

    def _search_open_markets_by_teams(
        self,
        home_abv: str,
        away_abv: str,
        game_num: int,
        markets: dict,
    ) -> Optional[str]:
        """
        Last-resort search: match only on team abbreviations, ignoring the date.

        Used when Kalshi's ticker date doesn't match our expected date strings
        (e.g. a 2025-dated market carried over for a 2026 game, or other encoding
        edge cases). Warns loudly since this match is date-ambiguous.
        """
        matches = []
        for ticker in markets:
            upper = ticker.upper()
            if home_abv not in upper or away_abv not in upper:
                continue
            if not ticker.endswith(f'-{home_abv}'):
                continue
            is_dh_g2 = 'G2' in upper
            if game_num == 2 and not is_dh_g2:
                continue
            if game_num != 2 and is_dh_g2:
                continue
            matches.append(ticker)

        if not matches:
            self._logger.warning(
                f'No open Kalshi market found for {home_abv} vs {away_abv} '
                f'after exhausting all search strategies.'
            )
            return None

        # When multiple markets match, prefer the one whose ticker date is
        # closest to today. Ties are broken by preferring the past (an open
        # market from a prior game date is more likely to be the active one
        # than a future-scheduled market created in advance).
        today = datetime.now(timezone.utc).date()
        best = self._pick_closest_date(matches, today)

        if len(matches) > 1:
            self._logger.warning(
                f'Date-agnostic fallback: {len(matches)} matches for '
                f'{home_abv} vs {away_abv}: {matches}. '
                f'Selected closest to today: {best}'
            )
        else:
            self._logger.warning(
                f'Date-agnostic fallback matched: {best} '
                f'(home={home_abv} away={away_abv}). '
                f'Ticker date may not match today — verify if unexpected.'
            )
        return best

    @staticmethod
    def _pick_closest_date(tickers: list[str], today) -> str:
        """
        Among a list of tickers, return the one whose embedded YYMMMDD date
        is closest to `today`. On equal distance, prefer the past over future.
        Unparseable tickers are ranked last.
        """
        from datetime import date as date_type

        def _ticker_date(ticker: str):
            # Ticker format: SERIES-{YYMMMDD}..., so data segment starts at index 9
            try:
                data = ticker.split('-')[1]   # e.g. "26MAR271635NYYSF"
                date_part = data[:7]           # e.g. "26MAR27"
                return datetime.strptime(date_part, '%y%b%d').date()
            except Exception:
                return None

        def _sort_key(ticker: str):
            d = _ticker_date(ticker)
            if d is None:
                return (999999, 1)           # unparseable — rank last
            delta = (d - today).days
            # (abs_distance, 1 if future else 0) — prefer past on tie
            return (abs(delta), 1 if delta > 0 else 0)

        return min(tickers, key=_sort_key)

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def _start_websocket(self) -> None:
        """
        Start a shared WebSocket price feed for all known market tickers.
        Runs in a background daemon thread with its own asyncio event loop.
        The resulting TradingState is shared across all LiveGameEngine instances.
        """
        tickers = [e.market_ticker for e in self.entries if e.market_ticker]
        if not tickers:
            self._logger.warning('No tickers to subscribe to — WebSocket not started.')
            self._trading_state = TradingState(self.http_client, [])
            return

        self._logger.info(f'Starting WebSocket for {len(tickers)} ticker(s).')
        update_event = threading.Event()
        self._trading_state = TradingState(self.http_client, tickers)
        ws_client = get_websocket_client(tickers, self._trading_state, update_event)

        def _ws_thread():
            asyncio.run(ws_client.run())

        self._ws_thread = threading.Thread(target=_ws_thread, name='websocket', daemon=True)
        self._ws_thread.start()
        self._logger.info('WebSocket thread started.')

    def _arm_game(self, entry: GameScheduleEntry) -> None:
        """
        Instantiate a LiveGameEngine and start it 5 minutes before first pitch.
        Fetches the live Market object and constructs a fresh BaseballGame.
        """
        from Core.live_engine import LiveGameEngine
        from Markets.Baseball.domain import BaseballGame
        from Infrastructure.state import Orderbook

        log = _GameLogAdapter(self._logger, {'ticker': entry.market_ticker})

        if not entry.market_ticker:
            log.warning('Cannot arm — no market ticker. Skipping.')
            entry.status = 'skipped'
            return

        log.info(
            f'Arming: {entry.away_team} @ {entry.home_team}  '
            f'game_id={entry.game_id}  game_num={entry.game_num}  '
            f'auto_execute={self.auto_execute}'
        )

        # Mark as armed immediately so a second loop iteration can't re-arm
        entry.status = 'armed'

        try:
            market = self.http_client.get_market_by_ticker(entry.market_ticker)
        except Exception:
            log.exception('Failed to fetch Market object. Skipping.')
            entry.status = 'skipped'
            return

        game = BaseballGame(
            game_id=entry.game_id,
            home_team_abv=entry.home_team,
            away_team_abv=entry.away_team,
            game_date=entry.scheduled_start.strftime('%Y-%m-%d'),
            start_time=entry.scheduled_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            status='Pre-Game',
        )

        # Ensure the ticker is registered in the shared TradingState
        if self._trading_state and entry.market_ticker not in self._trading_state.orderbooks:
            self._trading_state.orderbooks[entry.market_ticker] = Orderbook(entry.market_ticker)

        engine = LiveGameEngine(
            market=market,
            game=game,
            strategy=self.strategy_class(),
            http_client=self.http_client,
            trading_state=self._trading_state,
            auto_execute=self.auto_execute,
        )
        entry.engine = engine
        engine.start()
        entry.status = 'running'
        log.info('Engine started.')

    def _finalize_game(self, entry: GameScheduleEntry) -> None:
        """Record final P&L and mark a game as done."""
        log = _GameLogAdapter(self._logger, {'ticker': entry.market_ticker})
        pnl = entry.engine.get_realized_pnl() if entry.engine else 0.0
        log.info(
            f'Game resolved: {entry.away_team} @ {entry.home_team}  '
            f'P&L: ${pnl:+.2f}'
        )
        entry.status = 'done'

    # ------------------------------------------------------------------
    # Daily P&L + loss limit
    # ------------------------------------------------------------------

    def _update_daily_pnl(self) -> None:
        """Sum realized P&L across all running engines."""
        self._daily_pnl = sum(
            e.engine.get_realized_pnl()
            for e in self.entries
            if e.engine is not None and hasattr(e.engine, 'get_realized_pnl')
        )

    def _check_daily_loss_limit(self) -> None:
        """Halt everything if the daily loss threshold is breached."""
        if self._daily_pnl < -self.daily_loss_limit:
            self._logger.critical(
                f'Daily loss limit breached: ${self._daily_pnl:.2f} < -${self.daily_loss_limit:.2f}. '
                f'Halting all engines immediately.'
            )
            self._halt.set()
            self._halt_all()

    def _halt_all(self) -> None:
        """Signal every running engine to stop."""
        for entry in self.entries:
            if entry.engine is not None and hasattr(entry.engine, 'halt'):
                try:
                    entry.engine.halt()
                except Exception:
                    self._logger.exception(
                        f'Error halting engine for {entry.market_ticker}'
                    )
            if entry.status == 'running':
                entry.status = 'done'

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """
        Atomically write scheduler state to disk.

        Uses write-to-temp + os.replace() to ensure the state file is never
        partially written (safe on both POSIX and Windows).
        """
        state = {
            'date': self._date_str,
            'auto_execute': self.auto_execute,
            'daily_loss_limit': self.daily_loss_limit,
            'daily_pnl': self._daily_pnl,
            'entries': [e.to_dict() for e in self.entries],
            'saved_at': datetime.now(timezone.utc).isoformat(),
        }
        tmp_path = self._state_path.with_suffix('.tmp')
        try:
            tmp_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
            os.replace(tmp_path, self._state_path)
        except Exception:
            self._logger.exception('Failed to save scheduler state to disk')

    def _recover_state(self) -> bool:
        """
        Attempt to reload today's state file after a crash.

        Returns True if recovery succeeded and self.entries was populated.
        Games that were 'running' at crash time are reset to 'pending' with
        arm_time set to now-1s so the main loop re-arms them immediately.
        """
        if not self._state_path.exists():
            return False

        self._logger.warning(
            f'Crash recovery: found state file {self._state_path}'
        )
        try:
            data = json.loads(self._state_path.read_text(encoding='utf-8'))
        except Exception:
            self._logger.exception('State file unreadable. Starting fresh.')
            return False

        if data.get('date') != self._date_str:
            self._logger.warning(
                f'State file is from {data.get("date")}, not today ({self._date_str}). Ignoring.'
            )
            return False

        self._daily_pnl = data.get('daily_pnl', 0.0)
        self.entries = []

        for entry_dict in data.get('entries', []):
            try:
                entry = GameScheduleEntry.from_dict(entry_dict)
            except Exception:
                self._logger.exception(f'Failed to restore entry: {entry_dict}')
                continue

            if entry.status == 'running':
                # Was mid-game when crash happened — re-arm immediately
                self._logger.warning(
                    f'[{entry.market_ticker}] Was running at crash. Scheduling immediate re-arm.'
                )
                entry.status = 'pending'
                entry.arm_time = datetime.now(timezone.utc) - timedelta(seconds=1)

            elif entry.status == 'armed':
                # Crashed before first tick — re-arm
                entry.status = 'pending'
                entry.arm_time = datetime.now(timezone.utc) - timedelta(seconds=1)

            self.entries.append(entry)

        n_rearm = sum(1 for e in self.entries if e.status == 'pending')
        self._logger.warning(
            f'Crash recovery complete: {len(self.entries)} game(s) restored, '
            f'{n_rearm} will be re-armed. Daily P&L was ${self._daily_pnl:+.2f}.'
        )
        return True
