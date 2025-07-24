import pandas as pd
import matplotlib.pyplot as plt

def plot_calibration_curve(prediction_log, n_bins: int = 10):
    df = pd.DataFrame(prediction_log)

    # Drop entries where outcome is not yet known
    df = df.dropna(subset=["actual_outcome"])

    # Bin predicted probabilities
    bins = pd.interval_range(start=0, end=100, freq=100 / n_bins, closed='left')
    df["prob_bin"] = pd.cut(df["predicted_prob"], bins=bins)
    df["bid_bin"] = pd.cut(df["bid_price"], bins=bins)
    df["ask_bin"] = pd.cut(df["ask_price"], bins=bins)

    # Compute average predicted prob and win rate per bin
    calibration = df.groupby("prob_bin", observed=False).agg(
        avg_predicted=("predicted_prob", "mean"),
        avg_bid=("bid_price", "mean"),
        avg_ask=("ask_price", "mean"),
        actual_win_rate=("actual_outcome", "mean"),
        count=("actual_outcome", "count"),
    ).dropna()

    # Plot
    plt.figure(figsize=(8, 6))
    plt.plot(calibration["avg_predicted"], calibration["actual_win_rate"], marker='o', label="Predicted Prob Calibration")
    plt.plot(calibration["avg_bid"], calibration["actual_win_rate"], marker='s', label="Bid Price Calibration")
    plt.plot(calibration["avg_ask"], calibration["actual_win_rate"], marker='^', label="Ask Price Calibration")
    plt.plot([0, 100], [0, 1], '--', color='gray', label="Perfectly Calibrated")
    plt.xlabel("Predicted Probability")
    plt.ylabel("Actual Win Rate")
    plt.title("Model Calibration Curve")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()