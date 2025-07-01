import pandas as pd
import matplotlib.pyplot as plt

def plot_calibration_curve(prediction_log, n_bins: int = 10):
    df = pd.DataFrame(prediction_log)

    # Drop entries where outcome is not yet known
    df = df.dropna(subset=["actual_outcome"])

    # Bin predicted probabilities
    df["prob_bin"] = pd.cut(df["predicted_prob"], bins=n_bins)

    # Compute average predicted prob and win rate per bin
    calibration = df.groupby("prob_bin").agg(
        avg_predicted=("predicted_prob", "mean"),
        actual_win_rate=("actual_outcome", "mean"),
        count=("actual_outcome", "count")
    ).dropna()

    # Plot
    plt.figure(figsize=(8, 6))
    plt.plot(calibration["avg_predicted"], calibration["actual_win_rate"], marker='o', label="Calibration")
    plt.plot([0, 1], [0, 1], '--', color='gray', label="Perfectly Calibrated")
    plt.xlabel("Predicted Probability")
    plt.ylabel("Actual Win Rate")
    plt.title("Model Calibration Curve")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()