"""
Train a baseball win probability model using pybaseball Statcast data.

Features
--------
GameStateFeatureProvider  (always present):
    inning, is_extra_innings, is_bottom, outs, on_1b/2b/3b, score_diff,
    balls, strikes

PitcherFeatureProvider:
    pitcher_pitch_count  — cumulative pitches thrown by current pitcher in
                           this game BEFORE this plate appearance (0-indexed).
    home/away_sp_k_pct   — starting pitcher's blended K% (prev + curr season).
    home/away_sp_bb_pct  — starting pitcher's blended BB%.

BatterPitcherFeatureProvider:
    is_starter           — 1 if starting pitcher still on mound, 0 = reliever.
    current_pitcher_k_pct/bb_pct  — blended K%/BB% for the actual pitcher.
    platoon_adv_batter   — 1 if batter's hand differs from pitcher's (or switch).
    batting_order_pos    — batter's lineup slot (1-9).

TeamQualityFeatureProvider:
    home/away_run_diff_per_game  — previous-season (RS-RA)/G for each team.

Look-ahead policy
-----------------
- Pitcher stats use PREVIOUS season as prior; blended with current-season
  cumulative stats before the current game (cumsum shifted by 1 game).
- Team run differential uses only the previous calendar year.
- is_starter, platoon advantage, and batting order use only data available
  at the time of the pitch — no future-game information.

Train/test split
----------------
Chronological: earlier seasons train, the final season tests.
Default: train 2015-2023, test 2024.

Usage
-----
    python Scripts/train_win_prob_model.py
    python Scripts/train_win_prob_model.py --train-years 2015-2023 --test-year 2024
    python Scripts/train_win_prob_model.py --cache-dir D:/Data/statcast
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import joblib

sys.path.insert(0, str(Path(__file__).parent.parent))

from Markets.Baseball.game_state import (
    GameStateFeatureProvider,
    PitcherFeatureProvider,
    BatterPitcherFeatureProvider,
    TeamQualityFeatureProvider,
    LEAGUE_AVG_K_PCT,
    LEAGUE_AVG_BB_PCT,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

MODEL_OUTPUT_PATH = Path(__file__).parent.parent / 'Markets' / 'Baseball' / 'win_prob_model.pkl'

SEASON_DATES = {
    2015: ('2015-04-05', '2015-11-04'),
    2016: ('2016-04-03', '2016-11-03'),
    2017: ('2017-04-02', '2017-11-02'),
    2018: ('2018-03-29', '2018-10-28'),
    2019: ('2019-03-28', '2019-10-30'),
    2020: ('2020-07-23', '2020-10-27'),
    2021: ('2021-04-01', '2021-11-02'),
    2022: ('2022-04-07', '2022-11-05'),
    2023: ('2023-03-30', '2023-11-04'),
    2024: ('2024-03-20', '2024-10-30'),
}

# Columns to keep when writing the parquet cache.
STATCAST_COLS = [
    'game_pk', 'at_bat_number', 'pitch_number',
    'inning', 'inning_topbot',
    'outs_when_up', 'on_1b', 'on_2b', 'on_3b',
    'home_score', 'away_score',
    'balls', 'strikes',
    'pitcher',        # MLBAM pitcher ID
    'batter',         # MLBAM batter ID (for batting order position)
    'p_throws',       # pitcher handedness: 'R' or 'L'
    'stand',          # batter stance: 'R', 'L', or 'S'
    'home_team',      # team abbreviation (for run differential lookup)
    'away_team',
    'events',         # at-bat outcome (strikeout / walk / …)
    'post_home_score', 'post_away_score',
]

# Required columns for cache validation — re-download if any are missing.
REQUIRED_COLS = {'pitcher', 'events', 'p_throws', 'stand', 'home_team', 'batter'}


# ---------------------------------------------------------------------------
# Data loading (with cache invalidation)
# ---------------------------------------------------------------------------

def load_year(year: int, cache_dir: Path) -> pd.DataFrame:
    """Load one season of Statcast data, re-downloading if the cache is stale."""
    cache_file = cache_dir / f'statcast_{year}.parquet'

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        if REQUIRED_COLS.issubset(df.columns):
            log.info(f"{year}: loaded from cache ({len(df):,} rows)")
            return df
        log.info(f"{year}: cache missing required columns — re-downloading")
        cache_file.unlink()

    try:
        from pybaseball import statcast
        import pybaseball
        pybaseball.cache.enable()
    except ImportError:
        raise ImportError("pybaseball is required: pip install pybaseball")

    start, end = SEASON_DATES[year]
    log.info(f"{year}: downloading Statcast data ({start} to {end})...")
    df = statcast(start_dt=start, end_dt=end)

    if df is None or df.empty:
        log.warning(f"{year}: no data returned")
        return pd.DataFrame()

    log.info(f"{year}: {len(df):,} pitches downloaded")
    available = [c for c in STATCAST_COLS if c in df.columns]
    df = df[available].copy()

    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file, index=False)
    return df


# ---------------------------------------------------------------------------
# Game outcomes
# ---------------------------------------------------------------------------

def compute_game_outcomes(df: pd.DataFrame) -> pd.Series:
    """
    Return a Series mapping game_pk → home_won (bool).

    Uses post-play scores when available (accurate for walk-offs); falls
    back to pre-play scores of the last pitch (~5% walk-off error, fine
    for training).
    """
    df_sorted = df.sort_values(['game_pk', 'at_bat_number', 'pitch_number'])
    last = df_sorted.groupby('game_pk').last()

    has_post = (
        'post_home_score' in last.columns
        and 'post_away_score' in last.columns
        and last['post_home_score'].notna().mean() > 0.5
    )

    if has_post:
        final_home = last['post_home_score'].fillna(last['home_score'])
        final_away = last['post_away_score'].fillna(last['away_score'])
        log.info("Game outcomes: using post-play scores")
    else:
        final_home = last['home_score']
        final_away = last['away_score']
        log.info("Game outcomes: using pre-play scores of last pitch")

    home_won = (final_home > final_away).rename('home_won')
    tied = final_home == final_away
    if tied.sum():
        log.warning(f"Dropping {tied.sum()} games with tied final score")
        home_won = home_won[~tied]
    return home_won


# ---------------------------------------------------------------------------
# Pitcher stats — computed from Statcast, no look-ahead
# ---------------------------------------------------------------------------

# Phantom plate appearances used to regress current-season stats toward the
# prior (previous-season stats or league average). After REGRESSION_PA real
# PAs the current season gets 50% weight; after 3× it gets 75% weight.
# K% and BB% stabilise at roughly 70-150 PA; 150 is a conservative choice.
REGRESSION_PA = 150


def compute_pitcher_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute K% and BB% per pitcher from one season of Statcast data.

    Only end-of-at-bat rows (events.notna()) are counted.
    Pitchers with fewer than 50 batters faced are excluded (noisy sample).

    Returns a DataFrame indexed by pitcher MLBAM ID with columns:
        k_pct, bb_pct
    """
    ab_endings = df[df['events'].notna()].copy()
    ab_endings['is_k']  = ab_endings['events'] == 'strikeout'
    ab_endings['is_bb'] = ab_endings['events'].isin(['walk', 'intent_walk'])

    stats = ab_endings.groupby('pitcher').agg(
        total_ab=('events', 'count'),
        k=('is_k', 'sum'),
        bb=('is_bb', 'sum'),
    )
    stats = stats[stats['total_ab'] >= 50].copy()
    stats['k_pct']  = (stats['k']  / stats['total_ab']).astype(float)
    stats['bb_pct'] = (stats['bb'] / stats['total_ab']).astype(float)
    return stats[['k_pct', 'bb_pct']]


def load_pitcher_stats(year: int, cache_dir: Path, dfs_by_year: dict) -> pd.DataFrame:
    """
    Return pitcher stats for `year`, using a parquet cache.

    If the cache doesn't exist yet, compute from dfs_by_year[year].
    """
    cache_file = cache_dir / f'pitcher_stats_{year}.parquet'
    if cache_file.exists():
        return pd.read_parquet(cache_file)

    raw = dfs_by_year.get(year)
    if raw is None or raw.empty:
        log.warning(f"No Statcast data for {year} — pitcher stats will be league average")
        return pd.DataFrame(columns=['k_pct', 'bb_pct'])

    stats = compute_pitcher_stats(raw)
    stats.to_parquet(cache_file)
    log.info(f"Pitcher stats {year}: {len(stats):,} pitchers cached")
    return stats


# ---------------------------------------------------------------------------
# Cumulative within-season pitcher stats (no look-ahead)
# ---------------------------------------------------------------------------

def compute_cumulative_pitcher_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each pitcher, compute cumulative K and BB counts from all games that
    occurred BEFORE the current game within the SAME SEASON (ordered by game_pk,
    which is monotonically increasing within a season).

    IMPORTANT: processed per-season so that a veteran's cumulative count resets
    each year. Without this, a 2023 pitcher's cum_ab would be their career total
    from 2015 onward, making REGRESSION_PA a negligible prior weight.

    Returns a DataFrame indexed by (game_pk, pitcher) with columns:
        cum_ab  — batters faced in all prior games THIS season
        cum_k   — strikeouts in all prior games this season
        cum_bb  — walks in all prior games this season

    Values are zero for a pitcher's first appearance of the season.
    """
    results = []
    years = df['year'].unique() if 'year' in df.columns else [None]

    for year in years:
        year_df = df[df['year'] == year] if year is not None else df
        ab = year_df[year_df['events'].notna()].copy()
        ab['is_k']  = ab['events'] == 'strikeout'
        ab['is_bb'] = ab['events'].isin(['walk', 'intent_walk'])

        game_stats = (
            ab.groupby(['game_pk', 'pitcher'])
            .agg(game_ab=('events', 'count'), game_k=('is_k', 'sum'), game_bb=('is_bb', 'sum'))
            .reset_index()
            .sort_values(['pitcher', 'game_pk'])
        )

        for col_in, col_out in [('game_ab', 'cum_ab'), ('game_k', 'cum_k'), ('game_bb', 'cum_bb')]:
            game_stats[col_out] = (
                game_stats.groupby('pitcher')[col_in]
                .transform(lambda x: x.cumsum().shift(1, fill_value=0))
            )

        results.append(game_stats[['game_pk', 'pitcher', 'cum_ab', 'cum_k', 'cum_bb']])

    all_stats = pd.concat(results, ignore_index=True)
    return all_stats.set_index(['game_pk', 'pitcher'])


# ---------------------------------------------------------------------------
# Pitch count
# ---------------------------------------------------------------------------

def compute_pitch_counts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add `pitcher_pitch_count` — the number of pitches the current pitcher
    has thrown in this game BEFORE the current pitch (0-indexed cumcount).
    """
    df = df.sort_values(['game_pk', 'at_bat_number', 'pitch_number'])
    df['pitcher_pitch_count'] = (
        df.groupby(['game_pk', 'pitcher']).cumcount()
    )
    return df


# ---------------------------------------------------------------------------
# Starter quality join
# ---------------------------------------------------------------------------

def join_starter_stats(
    df: pd.DataFrame,
    pitcher_stats_by_year: dict[int, pd.DataFrame],
    cum_stats: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Identify each game's starting pitchers and join blended K%/BB% stats.

    Blending formula (Empirical Bayes regress-to-prior):
        blended = (cum_ab * stat_current + REGRESSION_PA * stat_prior)
                  / (cum_ab + REGRESSION_PA)

    Home starter = first pitcher in Top-half (away bats, home pitches).
    Away starter = first pitcher in Bot-half (home bats, away pitches).
    """
    df_sorted = df.sort_values(['game_pk', 'at_bat_number', 'pitch_number'])

    home_sp = (
        df_sorted[df_sorted['inning_topbot'] == 'Top']
        .groupby('game_pk')['pitcher'].first()
        .rename('home_sp_id')
    )
    away_sp = (
        df_sorted[df_sorted['inning_topbot'] == 'Bot']
        .groupby('game_pk')['pitcher'].first()
        .rename('away_sp_id')
    )

    game_year = df.groupby('game_pk')['year'].first()
    game_info = pd.DataFrame({'home_sp_id': home_sp, 'away_sp_id': away_sp, 'year': game_year})

    def _prior(pitcher_id, year: int) -> tuple[float, float]:
        stats = pitcher_stats_by_year.get(year - 1)
        if stats is not None and pitcher_id in stats.index:
            row = stats.loc[pitcher_id]
            return float(row['k_pct']), float(row['bb_pct'])
        return LEAGUE_AVG_K_PCT, LEAGUE_AVG_BB_PCT

    def _current(pitcher_id, game_pk) -> tuple[int, int, int]:
        if cum_stats is None:
            return 0, 0, 0
        try:
            row = cum_stats.loc[(game_pk, pitcher_id)]
            return int(row['cum_ab']), int(row['cum_k']), int(row['cum_bb'])
        except KeyError:
            return 0, 0, 0

    def _blend(pitcher_id, year: int, game_pk) -> tuple[float, float]:
        prior_k, prior_bb = _prior(pitcher_id, year)
        cum_ab, cum_k, cum_bb = _current(pitcher_id, game_pk)
        weight = cum_ab + REGRESSION_PA
        return (cum_k + prior_k * REGRESSION_PA) / weight, (cum_bb + prior_bb * REGRESSION_PA) / weight

    home_stats = game_info.apply(
        lambda r: _blend(r['home_sp_id'], r['year'], r.name), axis=1
    )
    away_stats = game_info.apply(
        lambda r: _blend(r['away_sp_id'], r['year'], r.name), axis=1
    )

    game_info['home_sp_k_pct']  = [x[0] for x in home_stats]
    game_info['home_sp_bb_pct'] = [x[1] for x in home_stats]
    game_info['away_sp_k_pct']  = [x[0] for x in away_stats]
    game_info['away_sp_bb_pct'] = [x[1] for x in away_stats]

    sp_cols = ['home_sp_k_pct', 'home_sp_bb_pct', 'away_sp_k_pct', 'away_sp_bb_pct']
    return df.join(game_info[sp_cols], on='game_pk')


# ---------------------------------------------------------------------------
# Is-starter indicator
# ---------------------------------------------------------------------------

def compute_is_starter(df: pd.DataFrame) -> pd.Series:
    """
    For each pitch, return 1 if the current pitcher is the game's starting
    pitcher for that side (Top = home pitching, Bot = away pitching), else 0.

    No look-ahead: the starter is identified by who pitched first in that
    half, using data already present for earlier pitches in the same game.
    """
    df_sorted = df.sort_values(['game_pk', 'at_bat_number', 'pitch_number'])
    starters = (
        df_sorted.groupby(['game_pk', 'inning_topbot'])['pitcher']
        .first()
        .rename('starter_id')
        .reset_index()
    )
    df_tmp = df[['game_pk', 'inning_topbot', 'pitcher']].merge(
        starters, on=['game_pk', 'inning_topbot'], how='left'
    )
    result = (df_tmp['pitcher'] == df_tmp['starter_id']).astype(int)
    result.index = df.index
    return result


# ---------------------------------------------------------------------------
# Batting order position
# ---------------------------------------------------------------------------

def compute_batting_order_pos(df: pd.DataFrame) -> pd.Series:
    """
    Assign each batter a lineup position (1-9) based on the order they
    first appear within each (game, half-inning side). Substitutes who
    appear after the 9th slot are capped at 9.

    No look-ahead: position is determined solely by when the batter first
    appeared, which is always in the past relative to the current pitch.
    """
    if 'batter' not in df.columns:
        return pd.Series(5, index=df.index)

    first_ab = (
        df.sort_values(['game_pk', 'inning_topbot', 'at_bat_number'])
        .groupby(['game_pk', 'inning_topbot', 'batter'])['at_bat_number']
        .first()
        .reset_index()
    )
    first_ab['batting_order_pos'] = (
        first_ab.groupby(['game_pk', 'inning_topbot'])['at_bat_number']
        .rank(method='first')
        .clip(1, 9)
        .astype(int)
    )
    df_tmp = df[['game_pk', 'inning_topbot', 'batter']].merge(
        first_ab[['game_pk', 'inning_topbot', 'batter', 'batting_order_pos']],
        on=['game_pk', 'inning_topbot', 'batter'],
        how='left',
    )
    result = df_tmp['batting_order_pos'].fillna(5).astype(int)
    result.index = df.index
    return result


# ---------------------------------------------------------------------------
# Platoon advantage
# ---------------------------------------------------------------------------

def compute_platoon_adv(df: pd.DataFrame) -> pd.Series:
    """
    Batter has platoon advantage (1) when their stance is opposite to the
    pitcher's throwing hand, or when the batter is a switch hitter.

    p_throws: 'R' or 'L'
    stand:    'R', 'L', or 'S' (switch hitter — always has platoon advantage)
    """
    if 'p_throws' not in df.columns or 'stand' not in df.columns:
        return pd.Series(0, index=df.index)
    p = df['p_throws'].fillna('R')
    s = df['stand'].fillna('R')
    return ((s != p) | (s == 'S')).astype(int)


# ---------------------------------------------------------------------------
# Current pitcher quality (all pitchers, blended)
# ---------------------------------------------------------------------------

def join_current_pitcher_stats(
    df: pd.DataFrame,
    pitcher_stats_by_year: dict[int, pd.DataFrame],
    cum_stats: pd.DataFrame,
) -> pd.DataFrame:
    """
    For each (game_pk, pitcher) pair, compute blended K%/BB% for the actual
    pitcher on the mound (starters AND relievers).

    Uses the same regress-to-prior formula as join_starter_stats.
    Operates on ~300k unique pairs (not 7M rows) for efficiency.
    """
    game_year = df.groupby('game_pk')['year'].first().rename('year_g')
    pairs = (
        df[['game_pk', 'pitcher']].drop_duplicates()
        .join(game_year, on='game_pk')
    )

    def _blend(row):
        pid, year, gpk = row['pitcher'], row['year_g'], row['game_pk']
        stats = pitcher_stats_by_year.get(year - 1)
        if stats is not None and pid in stats.index:
            r = stats.loc[pid]
            prior_k, prior_bb = float(r['k_pct']), float(r['bb_pct'])
        else:
            prior_k, prior_bb = LEAGUE_AVG_K_PCT, LEAGUE_AVG_BB_PCT
        try:
            r = cum_stats.loc[(gpk, pid)]
            cum_ab, cum_k, cum_bb = int(r['cum_ab']), int(r['cum_k']), int(r['cum_bb'])
        except KeyError:
            cum_ab, cum_k, cum_bb = 0, 0, 0
        w = cum_ab + REGRESSION_PA
        return (cum_k + prior_k * REGRESSION_PA) / w, (cum_bb + prior_bb * REGRESSION_PA) / w

    log.info("Computing current pitcher stats for %d unique (game, pitcher) pairs...", len(pairs))
    results = pairs.apply(_blend, axis=1)
    pairs['current_pitcher_k_pct']  = [x[0] for x in results]
    pairs['current_pitcher_bb_pct'] = [x[1] for x in results]
    pitcher_df = pairs.set_index(['game_pk', 'pitcher'])[['current_pitcher_k_pct', 'current_pitcher_bb_pct']]
    return df.join(pitcher_df, on=['game_pk', 'pitcher'])


# ---------------------------------------------------------------------------
# Team run differential (previous season)
# ---------------------------------------------------------------------------

def compute_team_run_diff(dfs_by_year: dict) -> dict[int, dict[str, float]]:
    """
    For each season, compute (RS - RA) / G per team abbreviation.
    Returns {year: {team_abbrev: run_diff_per_game}}.
    """
    result = {}
    for year, df in dfs_by_year.items():
        if 'home_team' not in df.columns or 'away_team' not in df.columns:
            continue
        df_sorted = df.sort_values(['game_pk', 'at_bat_number', 'pitch_number'])
        last = df_sorted.groupby('game_pk').last().reset_index()
        has_post = (
            'post_home_score' in last.columns
            and last['post_home_score'].notna().mean() > 0.5
        )
        if has_post:
            last['home_final'] = last['post_home_score'].fillna(last['home_score'])
            last['away_final'] = last['post_away_score'].fillna(last['away_score'])
        else:
            last['home_final'] = last['home_score']
            last['away_final'] = last['away_score']

        team_stats: dict[str, float] = {}
        all_teams = set(last['home_team'].dropna()) | set(last['away_team'].dropna())
        for team in all_teams:
            hg = last[last['home_team'] == team]
            ag = last[last['away_team'] == team]
            rs = float(hg['home_final'].sum() + ag['away_final'].sum())
            ra = float(hg['away_final'].sum() + ag['home_final'].sum())
            g  = len(hg) + len(ag)
            if g > 0:
                team_stats[team] = (rs - ra) / g
        result[year] = team_stats
        log.info("Team run diff %d: %d teams computed", year, len(team_stats))
    return result


def join_team_quality(
    df: pd.DataFrame,
    team_run_diff_by_year: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """Join previous-season run differential to each row via game-level lookup."""
    if 'home_team' not in df.columns or 'away_team' not in df.columns:
        df = df.copy()
        df['home_run_diff_per_game'] = 0.0
        df['away_run_diff_per_game'] = 0.0
        return df

    game_year  = df.groupby('game_pk')['year'].first().rename('game_year')
    game_teams = df.groupby('game_pk').first()[['home_team', 'away_team']]
    game_info  = game_teams.join(game_year)

    game_info['home_run_diff_per_game'] = game_info.apply(
        lambda r: team_run_diff_by_year.get(int(r['game_year']) - 1, {}).get(r['home_team'], 0.0), axis=1
    )
    game_info['away_run_diff_per_game'] = game_info.apply(
        lambda r: team_run_diff_by_year.get(int(r['game_year']) - 1, {}).get(r['away_team'], 0.0), axis=1
    )

    rd_cols = game_info[['home_run_diff_per_game', 'away_run_diff_per_game']]
    return df.join(rd_cols, on='game_pk')


# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------

def build_dataset(
    raw: pd.DataFrame,
    outcomes: pd.Series,
    providers: list,
    pitcher_stats_by_year: dict[int, pd.DataFrame],
    team_run_diff_by_year: dict[int, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """
    Merge outcomes, compute all features, extract model features.
    Returns a DataFrame with feature columns + home_won + game_pk.
    """
    df = raw.join(outcomes, on='game_pk').dropna(subset=['home_won'])

    # Pitcher pitch count
    df = compute_pitch_counts(df)

    # Cumulative current-season pitcher stats (no look-ahead)
    cum_stats = compute_cumulative_pitcher_stats(df)

    # Starter quality (blended prev + curr season)
    df = join_starter_stats(df, pitcher_stats_by_year, cum_stats=cum_stats)

    # Current pitcher quality for all pitchers (starters + relievers)
    df = join_current_pitcher_stats(df, pitcher_stats_by_year, cum_stats)

    # Batter-pitcher matchup features
    df = df.copy()
    df['is_starter']         = compute_is_starter(df)
    df['platoon_adv_batter'] = compute_platoon_adv(df)
    df['batting_order_pos']  = compute_batting_order_pos(df)

    # Team quality (previous season run differential)
    if team_run_diff_by_year is not None:
        df = join_team_quality(df, team_run_diff_by_year)

    # Extract features from all providers
    feature_frames = [p.get_features_batch(df) for p in providers]
    result = pd.concat(feature_frames, axis=1)
    result['home_won'] = df['home_won'].astype(int).values
    result['game_pk']  = df['game_pk'].values

    all_feat_names = [f for p in providers for f in p.feature_names]
    return result.dropna(subset=all_feat_names)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def build_model():
    try:
        from xgboost import XGBClassifier
        log.info("Using XGBClassifier")
        return XGBClassifier(
            n_estimators=500, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            eval_metric='logloss', n_jobs=-1, random_state=42, verbosity=0,
        )
    except ImportError:
        pass
    from sklearn.ensemble import HistGradientBoostingClassifier
    log.info("Using HistGradientBoostingClassifier")
    return HistGradientBoostingClassifier(
        max_iter=500, max_depth=6, learning_rate=0.05, random_state=42,
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(model, X_test: pd.DataFrame, y_test: pd.Series, feature_cols: list[str]):
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    proba = model.predict_proba(X_test)[:, 1]
    log.info(
        "Overall — Brier: %.4f  LogLoss: %.4f  ROC-AUC: %.4f",
        brier_score_loss(y_test, proba),
        log_loss(y_test, proba),
        roc_auc_score(y_test, proba),
    )

    log.info("Reliability (20 equal-count buckets):")
    labels = pd.qcut(proba, q=20, duplicates='drop')
    cal = pd.DataFrame({'pred': proba, 'actual': y_test.values}).groupby(labels)['actual'].agg(['mean', 'count'])
    for bucket, row in cal.iterrows():
        mid = (bucket.left + bucket.right) / 2
        log.info("  pred=%.2f  actual=%.3f  n=%6d", mid, row['mean'], int(row['count']))

    if 'inning' in X_test.columns and 'is_extra_innings' in X_test.columns:
        log.info("Brier by inning group:")
        inn = X_test['inning'].values; extra = X_test['is_extra_innings'].values
        for label, mask in [
            ('Innings 1-3',   (inn <= 3) & (extra == 0)),
            ('Innings 4-6',   (inn >= 4) & (inn <= 6) & (extra == 0)),
            ('Innings 7-9',   (inn >= 7) & (extra == 0)),
            ('Extra innings', extra == 1),
        ]:
            if mask.sum() >= 100:
                log.info("  %-20s  Brier=%.4f  n=%d", label,
                         brier_score_loss(y_test.values[mask], proba[mask]), mask.sum())

    if 'score_diff' in X_test.columns:
        log.info("Brier by score differential:")
        sd = X_test['score_diff'].values
        for label, mask in [
            ('Home up 3+',    sd >= 3),
            ('Home up 1-2',   (sd >= 1) & (sd <= 2)),
            ('Tied',          sd == 0),
            ('Home dn 1-2',   (sd <= -1) & (sd >= -2)),
            ('Home dn 3+',    sd <= -3),
        ]:
            if mask.sum() >= 100:
                log.info("  %-20s  Brier=%.4f  n=%d", label,
                         brier_score_loss(y_test.values[mask], proba[mask]), mask.sum())

    if 'pitcher_pitch_count' in X_test.columns:
        log.info("Brier by pitcher pitch count:")
        pc = X_test['pitcher_pitch_count'].values
        for label, mask in [
            ('0-30',   pc <= 30),
            ('31-60',  (pc > 30) & (pc <= 60)),
            ('61-90',  (pc > 60) & (pc <= 90)),
            ('91+',    pc > 90),
        ]:
            if mask.sum() >= 100:
                log.info("  %-20s  Brier=%.4f  n=%d", label,
                         brier_score_loss(y_test.values[mask], proba[mask]), mask.sum())

    # Feature importances
    if hasattr(model, 'feature_importances_'):
        log.info("Feature importances:")
        fi = sorted(zip(feature_cols, model.feature_importances_), key=lambda x: -x[1])
        for name, imp in fi:
            log.info("  %-35s  %.4f", name, imp)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train-years', type=str, default=None,
                        help='e.g. 2015-2023')
    parser.add_argument('--test-year',   type=int, default=None)
    parser.add_argument('--cache-dir',   type=Path, default=Path('D:/Data/statcast'))
    parser.add_argument('--output',      type=Path, default=MODEL_OUTPUT_PATH)
    args = parser.parse_args()

    all_years  = sorted(SEASON_DATES.keys())
    test_year  = args.test_year or max(all_years)

    if args.train_years:
        s, e = args.train_years.split('-')
        train_years = list(range(int(s), int(e) + 1))
    else:
        train_years = [y for y in all_years if y < test_year]

    log.info("Train years: %s", train_years)
    log.info("Test year:   %d", test_year)

    gs_provider = GameStateFeatureProvider()
    p_provider  = PitcherFeatureProvider()
    bp_provider = BatterPitcherFeatureProvider()
    tq_provider = TeamQualityFeatureProvider()
    providers   = [gs_provider, p_provider, bp_provider, tq_provider]
    feature_cols = [f for p in providers for f in p.feature_names]
    log.info("Features (%d): %s", len(feature_cols), feature_cols)

    # ---- Load raw data ----
    def load_years(years):
        dfs = {}
        for y in years:
            if y not in SEASON_DATES:
                log.warning(f"No dates for {y}, skipping")
                continue
            df = load_year(y, args.cache_dir)
            if not df.empty:
                df['year'] = y
                dfs[y] = df
        return dfs

    all_needed = sorted(set(train_years + [test_year]))
    prior_year = min(all_needed) - 1
    prior_years_needed = [prior_year] if prior_year in SEASON_DATES else []

    dfs_by_year = load_years(all_needed + prior_years_needed)

    # ---- Pitcher stats (previous season only) ----
    pitcher_stats_by_year: dict[int, pd.DataFrame] = {}
    for y in all_needed:
        pitcher_stats_by_year[y] = load_pitcher_stats(y, args.cache_dir, dfs_by_year)
    log.info("Pitcher stats loaded for years: %s", sorted(pitcher_stats_by_year.keys()))

    # ---- Team run differential ----
    team_run_diff_by_year = compute_team_run_diff(dfs_by_year)

    # ---- Outcomes ----
    raw_train = pd.concat([dfs_by_year[y] for y in train_years if y in dfs_by_year], ignore_index=True)
    raw_test  = dfs_by_year.get(test_year, pd.DataFrame())

    if raw_train.empty:
        log.error("No training data."); sys.exit(1)

    outcomes_train = compute_game_outcomes(raw_train)
    outcomes_test  = compute_game_outcomes(raw_test) if not raw_test.empty else pd.Series(dtype=bool)

    log.info("Train games: %d  home win rate: %.3f", len(outcomes_train), outcomes_train.mean())
    log.info("Test games:  %d  home win rate: %.3f", len(outcomes_test),  outcomes_test.mean() if len(outcomes_test) else 0)

    # ---- Build datasets ----
    train_data = build_dataset(raw_train, outcomes_train, providers, pitcher_stats_by_year, team_run_diff_by_year)
    test_data  = build_dataset(raw_test, outcomes_test, providers, pitcher_stats_by_year, team_run_diff_by_year) if not raw_test.empty else pd.DataFrame()

    log.info("Train pitches: %d  Test pitches: %d", len(train_data), len(test_data))

    X_train = train_data[feature_cols];  y_train = train_data['home_won']
    X_test  = test_data[feature_cols]   if not test_data.empty else pd.DataFrame()
    y_test  = test_data['home_won']     if not test_data.empty else pd.Series()

    # ---- Train ----
    model = build_model()
    log.info("Training...")
    model.fit(X_train, y_train)
    log.info("Training complete")

    if not X_test.empty:
        evaluate(model, X_test, y_test, feature_cols)

    # ---- Save ----
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        'feature_cols':  feature_cols,
        'providers':     [type(p).__name__ for p in providers],
        'train_years':   train_years,
        'test_year':     test_year,
        'train_pitches': len(X_train),
        'test_pitches':  len(X_test) if not X_test.empty else 0,
        'trained_at':    datetime.now().isoformat(),
        'model_class':   type(model).__name__,
    }
    joblib.dump({'model': model, 'metadata': metadata}, args.output)
    log.info("Model saved to %s", args.output)


if __name__ == '__main__':
    main()
