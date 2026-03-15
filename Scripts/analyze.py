#!/usr/bin/env python3
"""Backtest analysis CLI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Core.database import BacktestDatabase
import pandas as pd
import numpy as np

def analyze_strategy(db: BacktestDatabase, strategy_version: str):
    """Analyze performance for a strategy version."""
    predictions = db.get_predictions_by_market_type('baseball')
    df = pd.DataFrame([p for p in predictions if p['strategy_version'] == strategy_version])

    if df.empty:
        print(f"No data for strategy {strategy_version}")
        return

    print(f"\n{'='*60}")
    print(f"Strategy: {strategy_version}")
    print(f"{'='*60}")

    # Basic stats
    print(f"Total predictions: {len(df)}")
    print(f"Unique markets: {df['market_id'].nunique()}")

    # Cash distribution
    final_cash = df.groupby('market_id')['cash'].last()
    print(f"\nCash Statistics:")
    print(f"  Mean: ${final_cash.mean():.2f}")
    print(f"  Median: ${final_cash.median():.2f}")
    print(f"  Min: ${final_cash.min():.2f}")
    print(f"  Max: ${final_cash.max():.2f}")
    print(f"  ROI: {(final_cash.mean() - 100):.2f}%")

    # Brier score
    df_valid = df[(df['predicted_prob'].notna()) & (df['actual_outcome'].notna())]
    if not df_valid.empty:
        probs = df_valid['predicted_prob'] / 100
        outcomes = df_valid['actual_outcome']
        brier = np.mean((probs - outcomes) ** 2)
        print(f"\nBrier Score: {brier:.4f}")

def main():
    db = BacktestDatabase()

    # Get all strategy versions
    conn = db._get_connection()
    with conn as c:
        cursor = c.execute("SELECT DISTINCT strategy_version FROM predictions ORDER BY strategy_version")
        versions = [row[0] for row in cursor.fetchall()]

    print(f"Found {len(versions)} strategy versions in database:")
    for v in versions:
        print(f"  - {v}")

    # Analyze each
    for version in versions:
        analyze_strategy(db, version)

if __name__ == "__main__":
    main()
