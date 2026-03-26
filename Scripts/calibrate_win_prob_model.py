"""
Calibrate the baseball win probability model against realized game outcomes.

Uses only pybaseball Statcast data — no Kalshi market data required. This
means calibration can be run on any historical season regardless of whether
Kalshi markets existed for those games.

Outputs:
    - Overall Brier score, log loss, ROC-AUC
    - Reliability table (predicted probability bucket vs actual win rate)
    - Stratified metrics by inning group, score differential, pitcher pitch count
    - Multi-panel calibration plot (PNG if --plot is given)

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

from Markets.Baseball.win_prob_model import StatcastWinProbModel, MODEL_PATH
from Scripts.train_win_prob_model import (
    load_year, load_pitcher_stats, build_dataset,
    compute_game_outcomes, SEASON_DATES,
)
from Markets.Baseball.game_state import (
    GameStateFeatureProvider, PitcherFeatureProvider, PROVIDER_REGISTRY,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Build full feature dataset for calibration
# ---------------------------------------------------------------------------

def build_calibration_data(
    years: list[int],
    cache_dir: Path,
    model: StatcastWinProbModel,
    sample_fraction: float = 1.0,
) -> pd.DataFrame:
    """
    Load Statcast data, compute all model features (including pitcher features),
    run model predictions, and return a results DataFrame.

    Columns: pred, actual, plus all feature columns (inning, score_diff,
    pitcher_pitch_count, etc.) for stratified analysis.
    """
    # Reconstruct providers from model metadata (same as training)
    provider_names = model.metadata.get('providers', ['GameStateFeatureProvider'])
    providers = []
    for name in provider_names:
        cls = PROVIDER_REGISTRY.get(name)
        if cls:
            providers.append(cls())
    if not providers:
        providers = [GameStateFeatureProvider()]

    gs_provider = next((p for p in providers if isinstance(p, GameStateFeatureProvider)), GameStateFeatureProvider())
    p_provider  = next((p for p in providers if isinstance(p, PitcherFeatureProvider)),  PitcherFeatureProvider())

    # Load raw data — also need prior year for pitcher stats
    all_needed = sorted(set(years + [min(years) - 1]))
    dfs_by_year = {}
    for y in all_needed:
        if y not in SEASON_DATES:
            continue
        df = load_year(y, cache_dir)
        if not df.empty:
            df['year'] = y
            dfs_by_year[y] = df

    # Pitcher stats (cached per year)
    pitcher_stats_by_year = {}
    for y in years:
        pitcher_stats_by_year[y] = load_pitcher_stats(y, cache_dir, dfs_by_year)

    # Build full dataset for each year and concatenate
    dfs = []
    for y in years:
        raw = dfs_by_year.get(y)
        if raw is None or raw.empty:
            log.warning(f"No data for {y}, skipping")
            continue
        outcomes = compute_game_outcomes(raw)
        log.info(f"{y}: {len(outcomes):,} games  home win rate: {outcomes.mean():.3f}")
        df = build_dataset(raw, outcomes, gs_provider, p_provider, pitcher_stats_by_year)
        dfs.append(df)

    if not dfs:
        log.error("No data loaded.")
        sys.exit(1)

    results = pd.concat(dfs, ignore_index=True)
    log.info(f"Total pitches: {len(results):,}")

    if sample_fraction < 1.0:
        game_pks = results['game_pk'].unique()
        n = max(1, int(len(game_pks) * sample_fraction))
        sampled = set(np.random.default_rng(42).choice(game_pks, n, replace=False))
        results = results[results['game_pk'].isin(sampled)].copy()
        log.info(f"Sampled {sample_fraction:.0%} -> {len(results):,} pitches from {n:,} games")

    # Run model predictions
    log.info("Running model predictions...")
    X = results[model.feature_cols]
    results['pred']   = model._model.predict_proba(X)[:, 1]
    results['actual'] = results['home_won'].astype(int)
    return results


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def report_calibration(results: pd.DataFrame):
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    pred   = results['pred'].values
    actual = results['actual'].values

    print("\n" + "=" * 60)
    print("OVERALL CALIBRATION")
    print("=" * 60)
    print(f"  Pitches evaluated : {len(pred):,}")
    print(f"  Home win rate     : {actual.mean():.3f}")
    print(f"  Mean prediction   : {pred.mean():.3f}")
    print(f"  Brier score       : {brier_score_loss(actual, pred):.4f}  (baseline 0.250)")
    print(f"  Log loss          : {log_loss(actual, pred):.4f}  (baseline 0.693)")
    print(f"  ROC-AUC           : {roc_auc_score(actual, pred):.4f}")

    # Reliability table
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

    # Inning group
    if 'inning' in results.columns:
        print("\n" + "-" * 60)
        print("BRIER SCORE BY INNING GROUP")
        inn   = results['inning'].values
        extra = results['is_extra_innings'].values if 'is_extra_innings' in results.columns else np.zeros(len(inn))
        for label, mask in [
            ('Innings 1-3',   (inn <= 3) & (extra == 0)),
            ('Innings 4-6',   (inn >= 4) & (inn <= 6) & (extra == 0)),
            ('Innings 7-9',   (inn >= 7) & (extra == 0)),
            ('Extra innings', extra == 1),
        ]:
            if mask.sum() >= 100:
                print(f"  {label:<20}  Brier={brier_score_loss(actual[mask], pred[mask]):.4f}  n={mask.sum():,}")

    # Score differential
    if 'score_diff' in results.columns:
        print("\n" + "-" * 60)
        print("BRIER SCORE BY SCORE DIFFERENTIAL")
        sd = results['score_diff'].values
        for label, mask in [
            ('Home leading 3+',   sd >= 3),
            ('Home leading 1-2',  (sd >= 1) & (sd <= 2)),
            ('Tied',              sd == 0),
            ('Home trailing 1-2', (sd <= -1) & (sd >= -2)),
            ('Home trailing 3+',  sd <= -3),
        ]:
            if mask.sum() >= 100:
                print(f"  {label:<22}  Brier={brier_score_loss(actual[mask], pred[mask]):.4f}  n={mask.sum():,}")

    # Pitcher pitch count
    if 'pitcher_pitch_count' in results.columns:
        print("\n" + "-" * 60)
        print("BRIER SCORE BY PITCHER PITCH COUNT")
        pc = results['pitcher_pitch_count'].values
        for label, mask in [
            ('0-30',  pc <= 30),
            ('31-60', (pc > 30) & (pc <= 60)),
            ('61-90', (pc > 60) & (pc <= 90)),
            ('91+',   pc > 90),
        ]:
            if mask.sum() >= 100:
                print(f"  {label:<20}  Brier={brier_score_loss(actual[mask], pred[mask]):.4f}  n={mask.sum():,}")

    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Multi-panel calibration plot
# ---------------------------------------------------------------------------

def plot_calibration(results: pd.DataFrame, output_path: Path):
    """
    Save a multi-panel calibration figure:
      Row 1: Overall reliability curve | Brier by inning group
      Row 2: Brier by score diff       | Brier by pitcher pitch count
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        from sklearn.calibration import calibration_curve
        from sklearn.metrics import brier_score_loss
    except ImportError:
        log.warning("matplotlib / sklearn not installed - skipping plot")
        return

    pred   = results['pred'].values
    actual = results['actual'].values

    fig = plt.figure(figsize=(14, 10))
    fig.suptitle("Win Probability Model — Calibration Report", fontsize=14, fontweight='bold', y=0.98)
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

    # ---- Panel 1: Overall reliability curve ----
    ax1 = fig.add_subplot(gs[0, 0])
    prob_true, prob_pred = calibration_curve(actual, pred, n_bins=20, strategy='quantile')
    ax1.plot(prob_pred, prob_true, 's-', color='steelblue', label='Model', markersize=5)
    ax1.plot([0, 1], [0, 1], 'k--', alpha=0.5, label='Perfect')
    ax1.fill_between(prob_pred, prob_true, prob_pred,
                     where=(prob_true < prob_pred), alpha=0.15, color='orange', label='Overconfident')
    ax1.fill_between(prob_pred, prob_true, prob_pred,
                     where=(prob_true > prob_pred), alpha=0.15, color='green', label='Underconfident')
    bs_overall = brier_score_loss(actual, pred)
    ax1.set_title(f"Overall Reliability\nBrier={bs_overall:.4f}", fontsize=11)
    ax1.set_xlabel("Mean predicted probability")
    ax1.set_ylabel("Fraction of home wins")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)
    ax1.set_xlim(0, 1); ax1.set_ylim(0, 1)

    # ---- Panel 2: Brier by inning group ----
    ax2 = fig.add_subplot(gs[0, 1])
    if 'inning' in results.columns:
        inn   = results['inning'].values
        extra = results['is_extra_innings'].values if 'is_extra_innings' in results.columns else np.zeros(len(inn))
        inning_groups = [
            ('1-3',   (inn <= 3) & (extra == 0)),
            ('4-6',   (inn >= 4) & (inn <= 6) & (extra == 0)),
            ('7-9',   (inn >= 7) & (extra == 0)),
            ('Extra', extra == 1),
        ]
        labels, briers, counts = [], [], []
        for label, mask in inning_groups:
            if mask.sum() >= 100:
                labels.append(label)
                briers.append(brier_score_loss(actual[mask], pred[mask]))
                counts.append(mask.sum())

        colors = ['#5b9bd5', '#70ad47', '#ffc000', '#ed7d31'][:len(labels)]
        bars = ax2.bar(labels, briers, color=colors, edgecolor='white', linewidth=0.5)
        ax2.axhline(0.25, color='red', linestyle='--', alpha=0.5, linewidth=1, label='Baseline (0.25)')
        ax2.axhline(bs_overall, color='black', linestyle=':', alpha=0.7, linewidth=1, label=f'Overall ({bs_overall:.3f})')
        for bar, count in zip(bars, counts):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.002,
                     f'n={count//1000:.0f}k', ha='center', va='bottom', fontsize=8)
        ax2.set_title("Brier Score by Inning Group", fontsize=11)
        ax2.set_ylabel("Brier score")
        ax2.set_ylim(0, 0.28)
        ax2.legend(fontsize=8)
        ax2.grid(axis='y', alpha=0.3)

    # ---- Panel 3: Brier by score differential ----
    ax3 = fig.add_subplot(gs[1, 0])
    if 'score_diff' in results.columns:
        sd = results['score_diff'].values
        score_groups = [
            ('Up 3+',   sd >= 3),
            ('Up 1-2',  (sd >= 1) & (sd <= 2)),
            ('Tied',    sd == 0),
            ('Dn 1-2',  (sd <= -1) & (sd >= -2)),
            ('Dn 3+',   sd <= -3),
        ]
        labels, briers, counts = [], [], []
        for label, mask in score_groups:
            if mask.sum() >= 100:
                labels.append(label)
                briers.append(brier_score_loss(actual[mask], pred[mask]))
                counts.append(mask.sum())

        colors = ['#5b9bd5', '#9dc3e6', '#a9d18e', '#f4b183', '#ed7d31'][:len(labels)]
        bars = ax3.bar(labels, briers, color=colors, edgecolor='white', linewidth=0.5)
        ax3.axhline(0.25, color='red', linestyle='--', alpha=0.5, linewidth=1, label='Baseline (0.25)')
        ax3.axhline(bs_overall, color='black', linestyle=':', alpha=0.7, linewidth=1, label=f'Overall ({bs_overall:.3f})')
        for bar, count in zip(bars, counts):
            ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.002,
                     f'n={count//1000:.0f}k', ha='center', va='bottom', fontsize=8)
        ax3.set_title("Brier Score by Score Differential\n(home perspective)", fontsize=11)
        ax3.set_ylabel("Brier score")
        ax3.set_ylim(0, 0.28)
        ax3.legend(fontsize=8)
        ax3.grid(axis='y', alpha=0.3)

    # ---- Panel 4: Brier by pitcher pitch count ----
    ax4 = fig.add_subplot(gs[1, 1])
    if 'pitcher_pitch_count' in results.columns:
        pc = results['pitcher_pitch_count'].values
        pc_groups = [
            ('0-30',  pc <= 30),
            ('31-60', (pc > 30) & (pc <= 60)),
            ('61-90', (pc > 60) & (pc <= 90)),
            ('91+',   pc > 90),
        ]
        labels, briers, counts = [], [], []
        for label, mask in pc_groups:
            if mask.sum() >= 100:
                labels.append(label)
                briers.append(brier_score_loss(actual[mask], pred[mask]))
                counts.append(mask.sum())

        colors = ['#5b9bd5', '#70ad47', '#ffc000', '#ed7d31'][:len(labels)]
        bars = ax4.bar(labels, briers, color=colors, edgecolor='white', linewidth=0.5)
        ax4.axhline(0.25, color='red', linestyle='--', alpha=0.5, linewidth=1, label='Baseline (0.25)')
        ax4.axhline(bs_overall, color='black', linestyle=':', alpha=0.7, linewidth=1, label=f'Overall ({bs_overall:.3f})')
        for bar, count in zip(bars, counts):
            ax4.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.002,
                     f'n={count//1000:.0f}k', ha='center', va='bottom', fontsize=8)
        ax4.set_title("Brier Score by Pitcher Pitch Count", fontsize=11)
        ax4.set_xlabel("Pitches thrown this game (before this PA)")
        ax4.set_ylabel("Brier score")
        ax4.set_ylim(0, 0.28)
        ax4.legend(fontsize=8)
        ax4.grid(axis='y', alpha=0.3)

    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    log.info(f"Calibration plot saved to {output_path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Calibrate win probability model on pybaseball data')
    parser.add_argument('--year',      type=int,  default=None)
    parser.add_argument('--years',     type=str,  default=None, help='Range e.g. 2022-2024')
    parser.add_argument('--cache-dir', type=Path, default=Path('D:/Data/statcast'))
    parser.add_argument('--model',     type=Path, default=MODEL_PATH)
    parser.add_argument('--sample',    type=float, default=1.0,
                        help='Fraction of games to sample (0-1).')
    parser.add_argument('--plot',      type=Path, default=None,
                        help='Path to save calibration PNG.')
    args = parser.parse_args()

    model = StatcastWinProbModel(model_path=args.model)

    if args.years:
        start_str, end_str = args.years.split('-')
        years = list(range(int(start_str), int(end_str) + 1))
    elif args.year:
        years = [args.year]
    else:
        years = [model.metadata.get('test_year', max(SEASON_DATES.keys()))]

    log.info(f"Evaluating on seasons: {years}")

    train_years = set(model.metadata.get('train_years', []))
    overlap = [y for y in years if y in train_years]
    if overlap:
        log.warning(
            f"Years {overlap} were used for training — calibration on these "
            "will be optimistic. Use a held-out year for honest evaluation."
        )

    results = build_calibration_data(years, args.cache_dir, model, args.sample)
    report_calibration(results)

    if args.plot:
        plot_calibration(results, args.plot)


if __name__ == '__main__':
    main()
