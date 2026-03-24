"""
Train a baseball win probability model using pybaseball Statcast data.

Features
--------
GameStateFeatureProvider  (always present):
    inning, is_extra_innings, is_bottom, outs, on_1b/2b/3b, score_diff,
    balls, strikes

PitcherFeatureProvider  (added here):
    pitcher_pitch_count  — cumulative pitches thrown by current pitcher in
                           this game BEFORE this plate appearance (0-indexed).
    home/away_sp_k_pct   — starting pitcher's K% from the PREVIOUS season.
    home/away_sp_bb_pct  — starting pitcher's BB% from the PREVIOUS season.

Look-ahead policy
-----------------
- Pitcher stats use ONLY the prior calendar year's Statcast data.
  For a game on any date in season Y, the stats come from season Y-1.
  No current-season stats are ever used, so there is zero look-ahead bias
  even for opening-day games.
- Pitchers with no prior-year data (rookies, 2015 season) receive league
  averages (K%=22.2%, BB%=8.3%).

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
# Includes pitcher (MLBAM ID) and events (at-bat outcome) for pitcher stats.
STATCAST_COLS = [
    'game_pk', 'at_bat_number', 'pitch_number',
    'inning', 'inning_topbot',
    'outs_when_up', 'on_1b', 'on_2b', 'on_3b',
    'home_score', 'away_score',
    'balls', 'strikes',
    'pitcher',   # MLBAM pitcher ID — needed for pitch count + starter lookup
    'events',    # at-bat outcome (strikeout / walk / …) — needed for K%/BB%
    'post_home_score', 'post_away_score',
]


# ---------------------------------------------------------------------------
# Data loading (with cache invalidation)
# ---------------------------------------------------------------------------

def load_year(year: int, cache_dir: Path) -> pd.DataFrame:
    """Load one season of Statcast data, re-downloading if the cache is stale."""
    cache_file = cache_dir / f'statcast_{year}.parquet'

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        # Invalidate cache if required columns are missing
        required_present = {'pitcher', 'events'}.issubset(df.columns)
        if required_present:
            log.info(f"{year}: loaded from cache ({len(df):,} rows)")
            return df
        log.info(f"{year}: cache is missing pitcher/events columns — re-downloading")
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
# Pitch count
# ---------------------------------------------------------------------------

def compute_pitch_counts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add `pitcher_pitch_count` — the number of pitches the current pitcher
    has thrown in this game BEFORE the current pitch (0-indexed cumcount).

    Sorting is done in-place; the returned DataFrame keeps the original index.
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
) -> pd.DataFrame:
    """
    Identify each game's starting pitchers and join their PREVIOUS-season
    K% and BB% onto every pitch in that game.

    Home starter  = first pitcher who appears while the AWAY team bats (Top half).
    Away starter  = first pitcher who appears while the HOME team bats (Bot half).

    Previous-season lookup: for a game in year Y, uses pitcher_stats_by_year[Y-1].
    Missing pitchers (rookies, first year of Statcast) receive league averages.
    No current-season data is ever used → zero look-ahead bias.
    """
    df_sorted = df.sort_values(['game_pk', 'at_bat_number', 'pitch_number'])

    # Home team is pitching when inning_topbot == 'Top'
    home_sp = (
        df_sorted[df_sorted['inning_topbot'] == 'Top']
        .groupby('game_pk')['pitcher'].first()
        .rename('home_sp_id')
    )
    # Away team is pitching when inning_topbot == 'Bot'
    away_sp = (
        df_sorted[df_sorted['inning_topbot'] == 'Bot']
        .groupby('game_pk')['pitcher'].first()
        .rename('away_sp_id')
    )

    game_year = df.groupby('game_pk')['year'].first()
    game_info = pd.DataFrame({'home_sp_id': home_sp, 'away_sp_id': away_sp, 'year': game_year})

    def lookup(pitcher_id, year: int) -> tuple[float, float]:
        stats = pitcher_stats_by_year.get(year - 1)
        if stats is not None and pitcher_id in stats.index:
            row = stats.loc[pitcher_id]
            return float(row['k_pct']), float(row['bb_pct'])
        return LEAGUE_AVG_K_PCT, LEAGUE_AVG_BB_PCT

    home_stats = game_info.apply(lambda r: lookup(r['home_sp_id'], r['year']), axis=1)
    away_stats = game_info.apply(lambda r: lookup(r['away_sp_id'], r['year']), axis=1)

    game_info['home_sp_k_pct']  = [x[0] for x in home_stats]
    game_info['home_sp_bb_pct'] = [x[1] for x in home_stats]
    game_info['away_sp_k_pct']  = [x[0] for x in away_stats]
    game_info['away_sp_bb_pct'] = [x[1] for x in away_stats]

    sp_cols = ['home_sp_k_pct', 'home_sp_bb_pct', 'away_sp_k_pct', 'away_sp_bb_pct']
    return df.join(game_info[sp_cols], on='game_pk')


# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------

def build_dataset(
    raw: pd.DataFrame,
    outcomes: pd.Series,
    gs_provider: GameStateFeatureProvider,
    p_provider:  PitcherFeatureProvider,
    pitcher_stats_by_year: dict[int, pd.DataFrame],
) -> pd.DataFrame:
    """
    Merge outcomes, compute pitch counts, join starter stats, then extract
    all model features. Returns a DataFrame with feature columns + home_won + game_pk.
    """
    # Merge outcomes
    df = raw.join(outcomes, on='game_pk').dropna(subset=['home_won'])

    # Pitcher pitch count (must happen before any row-reordering joins)
    df = compute_pitch_counts(df)

    # Starter quality (previous season)
    df = join_starter_stats(df, pitcher_stats_by_year)

    # Feature extraction
    gs_feats = gs_provider.get_features_batch(df)
    p_feats  = p_provider.get_features_batch(df)

    result = pd.concat([gs_feats, p_feats], axis=1)
    result['home_won'] = df['home_won'].astype(int).values
    result['game_pk']  = df['game_pk'].values
    return result.dropna(subset=gs_provider.feature_names + p_provider.feature_names)


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
    providers   = [gs_provider, p_provider]
    feature_cols = [f for p in providers for f in p.feature_names]

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
    # We also need the year BEFORE the earliest training year for pitcher stats
    prior_year = min(all_needed) - 1
    prior_years_needed = [prior_year] if prior_year in SEASON_DATES else []

    dfs_by_year = load_years(all_needed + prior_years_needed)

    # ---- Pitcher stats (previous season only) ----
    pitcher_stats_by_year: dict[int, pd.DataFrame] = {}
    for y in all_needed:
        pitcher_stats_by_year[y] = load_pitcher_stats(y, args.cache_dir, dfs_by_year)
    log.info("Pitcher stats loaded for years: %s", sorted(pitcher_stats_by_year.keys()))

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
    train_data = build_dataset(raw_train, outcomes_train, gs_provider, p_provider, pitcher_stats_by_year)
    test_data  = build_dataset(raw_test,  outcomes_test,  gs_provider, p_provider, pitcher_stats_by_year) if not raw_test.empty else pd.DataFrame()

    log.info("Train pitches: %d  Test pitches: %d", len(train_data), len(test_data))

    X_train = train_data[feature_cols];  y_train = train_data['home_won']
    X_test  = test_data[feature_cols]  if not test_data.empty else pd.DataFrame()
    y_test  = test_data['home_won']    if not test_data.empty else pd.Series()

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
