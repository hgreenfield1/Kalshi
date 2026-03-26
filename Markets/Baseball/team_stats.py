"""
Team win percentage lookup via the MLB Stats API.

Supports two modes:
  - Previous season final standings (default, no look-ahead bias for backtesting)
  - Current season standings as of a specific date (for live trading or blended estimates)

Standings are cached in memory by (season, date_key) to avoid redundant API calls.
Date keys are rounded to the nearest month so games within the same month share a cache entry.

Usage:
    from Markets.Baseball.team_stats import get_team_win_pct

    # Previous season only (backtest-safe)
    pct = get_team_win_pct("New York Yankees", season=2024, use_previous_season=True)

    # Blended: previous season + current season as of game date
    pct = get_team_win_pct("New York Yankees", season=2024, game_date="2024-07-15")
"""

import logging
import statsapi

log = logging.getLogger(__name__)

LEAGUE_AVG_WIN_PCT = 0.500

# How many games of current-season data to require before it meaningfully
# contributes to the blend. At REGRESSION_GAMES current games, weight is 50/50.
REGRESSION_GAMES = 40

# In-memory caches
_team_id_cache: dict[str, int] = {}
_standings_cache: dict[tuple, dict[int, tuple[int, int]]] = {}  # (season, date_key) -> {id: (W, L)}


def _get_team_id(full_name: str) -> int | None:
    """Look up a statsapi team ID from a full team name. Fetched once and cached."""
    if full_name in _team_id_cache:
        return _team_id_cache[full_name]
    try:
        teams = statsapi.get('teams', {'sportId': 1})['teams']
        for t in teams:
            _team_id_cache[t['name']] = t['id']
    except Exception as e:
        log.warning("Could not fetch team list: %s", e)
        return None
    return _team_id_cache.get(full_name)


def _fetch_standings(season: int, date: str | None = None) -> dict[int, tuple[int, int]]:
    """
    Fetch standings for a season from the MLB Stats API.
    Returns {team_id: (wins, losses)}.

    date: 'YYYY-MM-DD' string. If None, fetches full/final season standings.
    Cache key rounds date to YYYY-MM to limit API calls to ~6/season.
    """
    date_key = date[:7] if date else None  # 'YYYY-MM' or None
    cache_key = (season, date_key)

    if cache_key in _standings_cache:
        return _standings_cache[cache_key]

    params: dict = {
        'leagueId': '103,104',
        'season': season,
        'standingsTypes': 'regularSeason',
    }
    if date:
        params['date'] = date

    try:
        data = statsapi.get('standings', params)
        records: dict[int, tuple[int, int]] = {}
        for division in data.get('records', []):
            for team_rec in division.get('teamRecords', []):
                team_id = team_rec['team']['id']
                wins    = team_rec.get('wins', 0)
                losses  = team_rec.get('losses', 0)
                records[team_id] = (wins, losses)
        log.info("Standings loaded: season=%d date_key=%s teams=%d", season, date_key, len(records))
        _standings_cache[cache_key] = records
        return records
    except Exception as e:
        log.warning("Could not fetch standings season=%d date=%s: %s", season, date, e)
        _standings_cache[cache_key] = {}
        return {}


def _win_pct_from_record(wins: int, losses: int) -> float:
    total = wins + losses
    return (wins / total) if total > 0 else LEAGUE_AVG_WIN_PCT


def get_team_win_pct(
    team_full_name: str,
    season: int,
    game_date: str | None = None,
    use_previous_season: bool = False,
) -> float:
    """
    Return a team's win percentage, blending previous-season and current-season
    data to balance look-ahead safety with recency.

    Modes
    -----
    use_previous_season=True
        Return previous season final win% only. Safe for any backtest context.

    game_date provided (default mode)
        Blend previous-season final record with current-season record as of
        game_date using a regress-to-prior formula:

            blended = (g_current * pct_current + REGRESSION_GAMES * pct_prev)
                      / (g_current + REGRESSION_GAMES)

        At the start of the season (g_current=0), returns pure previous-season.
        After REGRESSION_GAMES games, weight is 50/50. Fully current after ~3×.

    Args:
        team_full_name:      Full name as in mlb_teams dict, e.g. "New York Yankees".
        season:              Season the game is played in (e.g. 2024).
        game_date:           'YYYY-MM-DD' of the game. Used for current-season lookup.
        use_previous_season: If True, ignore current season entirely.

    Returns:
        Win percentage as a float in [0, 1].
    """
    team_id = _get_team_id(team_full_name)
    if team_id is None:
        log.warning("Team ID not found for '%s' — using league average", team_full_name)
        return LEAGUE_AVG_WIN_PCT

    # --- Previous season ---
    prev_records = _fetch_standings(season - 1)
    prev_record = prev_records.get(team_id)
    prev_pct = _win_pct_from_record(*prev_record) if prev_record else LEAGUE_AVG_WIN_PCT

    if use_previous_season or game_date is None:
        return prev_pct

    # --- Current season as of game_date ---
    cur_records = _fetch_standings(season, date=game_date)
    cur_record = cur_records.get(team_id)
    if cur_record is None:
        return prev_pct  # season hasn't started yet or data unavailable

    cur_w, cur_l = cur_record
    g_current = cur_w + cur_l
    cur_pct = _win_pct_from_record(cur_w, cur_l)

    # Regress-to-prior blend
    blended = (g_current * cur_pct + REGRESSION_GAMES * prev_pct) / (g_current + REGRESSION_GAMES)
    return blended
