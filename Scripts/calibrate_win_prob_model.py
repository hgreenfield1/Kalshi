"""
Calibrate the baseball win probability model against realized game outcomes.

Uses only pybaseball Statcast data — no Kalshi market data required. This
means calibration can be run on any historical season regardless of whether
Kalshi markets existed for those games.

Calibration tests the live win probability model in isolation: given the
on-field game state at each pitch, how often does the model's predicted
P(home wins) match the actual observed win rate?

Outputs:
    - Overall Brier score, log loss, ROC-AUC
    - Reliability table (predicted probability bucket vs actual win rate)
    - Stratified metrics by inning group and score differential
    - Optional: reliability diagram saved as PNG

Usage:
    python Scripts/calibrate_win_prob_model.py
    python Scripts/calibrate_win_prob_model.py --year 2024
    python Scripts/calibrate_win_prob_model.py --year 2023 --plot calibration_2023.png
    python Scripts/calibrate_win_prob_model.py --years 2022-2024 --sample 0.2
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from Markets.Baseball.game_state import GameStateFeatureProvider
from Markets.Baseball.win_prob_model import StatcastWinProbModel, MODEL_PATH
from Scripts.train_win_prob_model import load_year, compute_game_outcomes, SEASON_DATES

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


def run_calibration(
    raw: pd.DataFrame,
    model: StatcastWinProbModel,
    provider: GameStateFeatureProvider,
    sample_fraction: float = 1.0,
) -> pd.DataFrame:
    """
    Compute model predictions for every pitch and return a results DataFrame.

    Columns: pred (model probability), actual (home_won label), plus all
    feature columns for stratified analysis.
    """
    # Game outcomes
    outcomes = compute_game_outcomes(raw)
    log.info(f"Games: {len(outcomes):,}  Home win rate: {outcomes.mean():.3f}")

    # Merge outcomes and compute features
    df = raw.join(outcomes, on='game_pk').dropna(subset=['home_won'])

    if sample_fraction < 1.0:
        game_pks = df['game_pk'].unique()
        n = int(len(game_pks) * sample_fraction)
        sampled = set(np.random.default_rng(42).choice(game_pks, n, replace=False))
        df = df[df['game_pk'].isin(sampled)]
        log.info(f"Sampled {sample_fraction:.0%} → {len(df):,} pitches from {n:,} games")

    features = provider.get_features_batch(df)
    X = features[model.feature_cols]

    log.info(f"Running model predictions on {len(X):,} pitches...")
    proba = model._model.predict_proba(X)[:, 1]

    results = features.copy()
    results['pred'] = proba
    results['actual'] = df['home_won'].astype(int).values
    return results


def report_calibration(results: pd.DataFrame):
    """Print calibration metrics to stdout."""
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    pred = results['pred'].values
    actual = results['actual'].values

    print("\n" + "=" * 60)
    print("OVERALL CALIBRATION")
    print("=" * 60)
    print(f"  Pitches evaluated : {len(pred):,}")
    print(f"  Home win rate     : {actual.mean():.3f}")
    print(f"  Mean prediction   : {pred.mean():.3f}")
    print(f"  Brier score       : {brier_score_loss(actual, pred):.4f}  (baseline 0.25)")
    print(f"  Log loss          : {log_loss(actual, pred):.4f}  (baseline 0.693)")
    print(f"  ROC-AUC           : {roc_auc_score(actual, pred):.4f}")

    # Reliability table: 20 equal-count buckets
    print("\n" + "-" * 60)
    print("RELIABILITY  (predicted bucket -> actual win rate)")
    print(f"  {'Pred range':>18}  {'Midpoint':>8}  {'Actual':>8}  {'Error':>8}  {'N':>8}")
    print("-" * 60)
    labels = pd.qcut(pred, q=20, duplicates='drop')
    cal = (
        pd.DataFrame({'pred': pred, 'actual': actual})
        .groupby(labels)['actual']
        .agg(['mean', 'count'])
    )
    for bucket, row in cal.iterrows():
        mid = (bucket.left + bucket.right) / 2
        err = mid - row['mean']
        print(f"  {str(bucket):>18}  {mid:8.2f}  {row['mean']:8.3f}  {err:+8.3f}  {int(row['count']):8,}")

    # Stratified by inning group
    if 'inning' in results.columns and 'is_extra_innings' in results.columns:
        print("\n" + "-" * 60)
        print("BRIER SCORE BY INNING GROUP")
        inning = results['inning'].values
        extra = results['is_extra_innings'].values
        groups = [
            ('Innings 1-3',   (inning <= 3) & (extra == 0)),
            ('Innings 4-6',   (inning >= 4) & (inning <= 6) & (extra == 0)),
            ('Innings 7-9',   (inning >= 7) & (extra == 0)),
            ('Extra innings', extra == 1),
        ]
        for label, mask in groups:
            if mask.sum() >= 100:
                bs = brier_score_loss(actual[mask], pred[mask])
                print(f"  {label:<20}  Brier={bs:.4f}  n={mask.sum():,}")

    # Stratified by score differential
    if 'score_diff' in results.columns:
        print("\n" + "-" * 60)
        print("BRIER SCORE BY SCORE DIFFERENTIAL")
        sd = results['score_diff'].values
        groups = [
            ('Home leading 3+', sd >= 3),
            ('Home leading 1-2', (sd >= 1) & (sd <= 2)),
            ('Tied',             sd == 0),
            ('Home trailing 1-2', (sd <= -1) & (sd >= -2)),
            ('Home trailing 3+', sd <= -3),
        ]
        for label, mask in groups:
            if mask.sum() >= 100:
                bs = brier_score_loss(actual[mask], pred[mask])
                print(f"  {label:<22}  Brier={bs:.4f}  n={mask.sum():,}")

    print("=" * 60 + "\n")


def plot_reliability(results: pd.DataFrame, output_path: Path):
    """Save a reliability diagram to a PNG file."""
    try:
        import matplotlib.pyplot as plt
        from sklearn.calibration import calibration_curve
    except ImportError:
        log.warning("matplotlib not installed — skipping plot")
        return

    pred = results['pred'].values
    actual = results['actual'].values

    fig, ax = plt.subplots(figsize=(7, 7))
    prob_true, prob_pred = calibration_curve(actual, pred, n_bins=20, strategy='quantile')
    ax.plot(prob_pred, prob_true, 's-', label='Model', color='steelblue')
    ax.plot([0, 1], [0, 1], 'k--', label='Perfect calibration', alpha=0.5)
    ax.set_xlabel('Mean predicted probability')
    ax.set_ylabel('Fraction of home team wins')
    ax.set_title('Win Probability Model — Reliability Diagram')
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    log.info(f"Reliability diagram saved to {output_path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description='Calibrate win probability model on pybaseball data')
    parser.add_argument(
        '--year', type=int, default=None,
        help='Single season to evaluate (default: test_year stored in model metadata)'
    )
    parser.add_argument(
        '--years', type=str, default=None,
        help='Range of seasons, e.g. 2022-2024'
    )
    parser.add_argument('--cache-dir', type=Path, default=Path('D:/Data/statcast'))
    parser.add_argument('--model', type=Path, default=MODEL_PATH)
    parser.add_argument('--sample', type=float, default=1.0,
                        help='Fraction of games to sample (0-1). Use <1 for faster runs.')
    parser.add_argument('--plot', type=Path, default=None,
                        help='Path to save reliability diagram PNG (optional)')
    args = parser.parse_args()

    # Load model
    model = StatcastWinProbModel(model_path=args.model)
    provider = GameStateFeatureProvider()

    # Determine which years to evaluate
    if args.years:
        start_str, end_str = args.years.split('-')
        years = list(range(int(start_str), int(end_str) + 1))
    elif args.year:
        years = [args.year]
    else:
        # Default to the test year that was held out during training
        years = [model.metadata.get('test_year', max(SEASON_DATES.keys()))]

    log.info(f"Evaluating on seasons: {years}")

    # Warn if any evaluation year was in the training set
    train_years = set(model.metadata.get('train_years', []))
    overlap = [y for y in years if y in train_years]
    if overlap:
        log.warning(
            f"Years {overlap} were used for training — calibration on these "
            "will be optimistic. Use a held-out year for honest evaluation."
        )

    # Load data
    dfs = []
    for year in years:
        if year not in SEASON_DATES:
            log.warning(f"No dates configured for {year}, skipping")
            continue
        df = load_year(year, args.cache_dir)
        if not df.empty:
            dfs.append(df)

    if not dfs:
        log.error("No data loaded.")
        sys.exit(1)

    raw = pd.concat(dfs, ignore_index=True)
    log.info(f"Total pitches loaded: {len(raw):,}")

    # Run calibration
    results = run_calibration(raw, model, provider, sample_fraction=args.sample)

    # Report
    report_calibration(results)

    # Optional plot
    if args.plot:
        plot_reliability(results, args.plot)


if __name__ == '__main__':
    main()
