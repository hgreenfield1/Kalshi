"""
BaseballMarketDiscovery: resolves an MLB game to a Kalshi KXMLBGAME ticker.

Extracted from Scheduler so the search logic lives alongside the baseball
domain code and Scheduler stays market-agnostic.

Ticker formats:
  Old (no time component):  KXMLBGAME-{YYMMMDD}{HOME}{AWAY}-{HOME}
  New (with time):          KXMLBGAME-{YYMMMDD}{HHMM}{HOME}{AWAY}-{HOME}

Because we don't know the {HHMM} component ahead of time, a direct lookup
rarely succeeds for new-format tickers. The series search is the primary
discovery path.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from Core.market_discovery import MarketDiscovery
from Markets.Baseball.config import SERIES_TICKER

_log = logging.getLogger(__name__)


class BaseballMarketDiscovery(MarketDiscovery):
    """Discover open KXMLBGAME Kalshi markets for MLB games."""

    def discover(
        self,
        home_team: str,
        away_team: str,
        game_date: str,
        scheduled_start_utc: datetime,
        game_num: int,
        http_client,
    ) -> Optional[str]:
        """
        Try three strategies in order:
          1. Direct ticker lookup (works for old-format tickers without {HHMM})
          2. Series search filtered by date + teams
          3. Last-resort search filtered by teams only (date-agnostic, logs warning)
        """
        local_date = datetime.strptime(game_date, '%Y-%m-%d').date()
        utc_date = scheduled_start_utc.date()

        local_date_str = local_date.strftime('%y%b%d').upper()   # e.g. "26MAR27"
        utc_date_str   = utc_date.strftime('%y%b%d').upper()     # e.g. "26MAR28"

        date_strs = [local_date_str]
        if utc_date_str != local_date_str:
            date_strs.append(utc_date_str)

        # Direct lookup (handles old tickers that embed no time component)
        result = self._direct_lookup(home_team, away_team, date_strs, game_num, http_client)
        if result:
            return result

        _log.debug(
            'Direct lookup failed for %s vs %s (dates tried: %s). '
            'Trying series search.',
            home_team, away_team, date_strs,
        )

        # Series search (primary path for new-format tickers with {HHMM})
        try:
            markets = http_client.get_markets(SERIES_TICKER, status='open')
        except Exception:
            _log.exception('get_markets() failed during fallback search')
            return None

        result = self._search_by_date_and_teams(
            home_team, away_team, date_strs, game_num, markets
        )
        if result:
            return result

        # Last resort: match only on teams, ignoring the date
        return self._search_by_teams_only(
            home_team, away_team, game_num, markets, scheduled_start_utc
        )

    # ------------------------------------------------------------------
    # Discovery strategies
    # ------------------------------------------------------------------

    def _direct_lookup(
        self,
        home_team: str,
        away_team: str,
        date_strs: list[str],
        game_num: int,
        http_client,
    ) -> Optional[str]:
        """Try every known date + G2 suffix combination as a direct GET."""
        g2_suffixes = ['G2', '2'] if game_num == 2 else ['']
        for date_str in date_strs:
            for suffix in g2_suffixes:
                candidate = f'{SERIES_TICKER}-{date_str}{home_team}{away_team}{suffix}-{home_team}'
                try:
                    market = http_client.get_market_by_ticker(candidate)
                    if market:
                        _log.debug('Direct lookup succeeded: %s', candidate)
                        return candidate
                except Exception:
                    pass
        return None

    def _search_by_date_and_teams(
        self,
        home_team: str,
        away_team: str,
        date_strs: list[str],
        game_num: int,
        markets: dict,
    ) -> Optional[str]:
        """
        Filter open markets to those containing one of the candidate dates,
        both team abbreviations, and the correct home-team suffix.
        """
        matches = []
        for ticker in markets:
            upper = ticker.upper()
            if not any(d in upper for d in date_strs):
                continue
            if home_team not in upper or away_team not in upper:
                continue
            if not ticker.endswith(f'-{home_team}'):
                continue
            is_dh_g2 = 'G2' in upper
            if game_num == 2 and not is_dh_g2:
                continue
            if game_num != 2 and is_dh_g2:
                continue
            matches.append(ticker)

        if len(matches) == 1:
            _log.info(
                'Series search matched: %s  (home=%s away=%s dates=%s)',
                matches[0], home_team, away_team, date_strs,
            )
            return matches[0]

        if len(matches) > 1:
            _log.warning(
                'Ambiguous match for %s vs %s: %s. Using first result.',
                home_team, away_team, matches,
            )
            return matches[0]

        return None

    def _search_by_teams_only(
        self,
        home_team: str,
        away_team: str,
        game_num: int,
        markets: dict,
        scheduled_start_utc: datetime,
    ) -> Optional[str]:
        """
        Last-resort: match on team abbreviations only, ignoring the date.
        When multiple tickers match, prefer the one whose embedded date is
        closest to today (past dates preferred over future on a tie).
        Logs a warning because this match is date-ambiguous.
        """
        matches = []
        for ticker in markets:
            upper = ticker.upper()
            if home_team not in upper or away_team not in upper:
                continue
            if not ticker.endswith(f'-{home_team}'):
                continue
            is_dh_g2 = 'G2' in upper
            if game_num == 2 and not is_dh_g2:
                continue
            if game_num != 2 and is_dh_g2:
                continue
            matches.append(ticker)

        if not matches:
            _log.warning(
                'No open Kalshi market found for %s vs %s '
                'after exhausting all search strategies.',
                home_team, away_team,
            )
            return None

        today = datetime.now(timezone.utc).date()
        best = _pick_closest_date(matches, today)

        if len(matches) > 1:
            _log.warning(
                'Date-agnostic fallback: %d matches for %s vs %s: %s. '
                'Selected closest to today: %s',
                len(matches), home_team, away_team, matches, best,
            )
        else:
            _log.warning(
                'Date-agnostic fallback matched: %s  (home=%s away=%s). '
                'Ticker date may not match today — verify if unexpected.',
                best, home_team, away_team,
            )
        return best


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_closest_date(tickers: list[str], today) -> str:
    """
    Return the ticker whose embedded YYMMMDD date is closest to `today`.
    On equal distance, prefer past dates over future. Unparseable tickers rank last.
    """
    def _sort_key(ticker: str):
        try:
            data = ticker.split('-')[1]   # e.g. "26MAR271635NYYSF"
            d = datetime.strptime(data[:7], '%y%b%d').date()
            delta = (d - today).days
            return (abs(delta), 1 if delta > 0 else 0)
        except Exception:
            return (999999, 1)

    return min(tickers, key=_sort_key)
