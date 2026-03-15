from typing import List, Dict, Any
import pandas as pd
import numpy as np

class PerformanceTracker:
    """Calculate prediction market metrics."""

    def __init__(self):
        self.predictions = []

    def track_prediction(self, predicted_prob: float, actual_outcome: bool,
                        timestamp: str, metadata: Dict[str, Any] = None):
        """Record a prediction."""
        self.predictions.append({
            'predicted_prob': predicted_prob,
            'actual_outcome': 1 if actual_outcome else 0,
            'timestamp': timestamp,
            **(metadata or {})
        })

    def calculate_brier_score(self) -> float:
        """Calculate Brier score (lower is better)."""
        if not self.predictions:
            return None

        df = pd.DataFrame(self.predictions)
        # Convert predicted_prob from 0-100 to 0-1
        probs = df['predicted_prob'] / 100
        outcomes = df['actual_outcome']
        return np.mean((probs - outcomes) ** 2)

    def calculate_calibration(self, n_bins: int = 10) -> pd.DataFrame:
        """Calculate calibration curve data."""
        if not self.predictions:
            return None

        df = pd.DataFrame(self.predictions)
        probs = df['predicted_prob'] / 100
        outcomes = df['actual_outcome']

        # Create bins
        bins = np.linspace(0, 1, n_bins + 1)
        df['bin'] = pd.cut(probs, bins, include_lowest=True)

        # Calculate mean predicted vs actual per bin
        calibration = df.groupby('bin').agg({
            'predicted_prob': lambda x: (x / 100).mean(),
            'actual_outcome': 'mean'
        }).reset_index()

        return calibration

    def calculate_roi(self, initial_cash: float, final_cash: float) -> float:
        """Calculate return on investment."""
        return ((final_cash - initial_cash) / initial_cash) * 100
