#!/usr/bin/env python3
"""
Database analysis tool for backtest results.
Replaces the CSV-based analyze.py with SQLite database querying.
"""

import logging
from typing import Dict, List, Any
from Baseball.database import BacktestDatabase
import pandas as pd
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO)


class BacktestAnalyzer:
    """Analyzer for backtest results stored in SQLite database."""
    
    def __init__(self, db_path: str = "backtest_predictions.db"):
        self.db = BacktestDatabase(db_path)
    
    def analyze_strategy_performance(self, strategy_version: str = None) -> Dict[str, Any]:
        """Analyze performance of a specific strategy version or all strategies."""
        if strategy_version:
            performance = self.db.get_strategy_performance(strategy_version)
            logging.info(f"Performance for strategy {strategy_version}:")
        else:
            # Analyze all strategies
            strategies = self.db.get_all_strategy_versions()
            performance = {}
            for strategy in strategies:
                perf = self.db.get_strategy_performance(strategy)
                performance[strategy] = perf
                logging.info(f"Performance for strategy {strategy}:")
                self._print_performance_metrics(perf)
            return performance
        
        self._print_performance_metrics(performance)
        return performance
    
    def _print_performance_metrics(self, metrics: Dict[str, Any]):
        """Print formatted performance metrics."""
        if not metrics:
            logging.info("  No data available")
            return
        
        logging.info(f"  Total Predictions: {metrics.get('total_predictions', 0)}")
        logging.info(f"  Total Games: {metrics.get('total_games', 0)}")
        
        accuracy = metrics.get('prediction_accuracy')
        if accuracy is not None:
            logging.info(f"  Prediction Accuracy: {accuracy:.2%}")
        
        avg_cash = metrics.get('avg_cash')
        if avg_cash is not None:
            logging.info(f"  Average Cash: ${avg_cash:.2f}")
        
        min_cash = metrics.get('min_cash')
        max_cash = metrics.get('max_cash')
        if min_cash is not None and max_cash is not None:
            logging.info(f"  Cash Range: ${min_cash:.2f} - ${max_cash:.2f}")
    
    def compare_strategies(self) -> Dict[str, Dict[str, Any]]:
        """Compare performance across all strategy versions."""
        strategies = self.db.get_all_strategy_versions()
        
        if not strategies:
            logging.info("No strategy data found in database")
            return {}
        
        logging.info("Strategy Comparison:")
        logging.info("=" * 50)
        
        comparison = {}
        for strategy in strategies:
            performance = self.db.get_strategy_performance(strategy)
            comparison[strategy] = performance
            
            logging.info(f"\nStrategy: {strategy}")
            self._print_performance_metrics(performance)
        
        return comparison
    
    def analyze_model_versions(self) -> Dict[str, List[Dict[str, Any]]]:
        """Analyze performance by prediction model version."""
        models = self.db.get_all_model_versions()
        
        if not models:
            logging.info("No model version data found in database")
            return {}
        
        logging.info("Model Version Analysis:")
        logging.info("=" * 50)
        
        model_analysis = {}
        for model in models:
            predictions = self.db.get_predictions_by_model_version(model)
            model_analysis[model] = predictions
            
            logging.info(f"\nModel Version: {model}")
            logging.info(f"  Total Predictions: {len(predictions)}")
            
            if predictions:
                games = set(p['game_id'] for p in predictions)
                logging.info(f"  Total Games: {len(games)}")
                
                # Calculate accuracy
                correct_predictions = 0
                total_with_outcome = 0
                
                for pred in predictions:
                    if pred['predicted_prob'] is not None and pred['actual_outcome'] is not None:
                        total_with_outcome += 1
                        predicted_win = pred['predicted_prob'] > 50
                        actual_win = bool(pred['actual_outcome'])
                        if predicted_win == actual_win:
                            correct_predictions += 1
                
                if total_with_outcome > 0:
                    accuracy = correct_predictions / total_with_outcome
                    logging.info(f"  Prediction Accuracy: {accuracy:.2%}")
        
        return model_analysis
    
    def get_game_details(self, game_id: str) -> List[Dict[str, Any]]:
        """Get detailed predictions for a specific game."""
        predictions = self.db.get_predictions_by_game(game_id)
        
        if not predictions:
            logging.info(f"No predictions found for game {game_id}")
            return []
        
        logging.info(f"Game Details for {game_id}:")
        logging.info("=" * 50)
        
        for i, pred in enumerate(predictions):
            logging.info(f"Prediction {i+1}:")
            logging.info(f"  Timestamp: {pred['timestamp']}")
            logging.info(f"  Predicted Probability: {pred['predicted_prob']}")
            logging.info(f"  Bid/Ask: {pred['bid_price']}/{pred['ask_price']}")
            logging.info(f"  Cash: ${pred['cash']:.2f}")
            logging.info(f"  Positions: {pred['positions']}")
            logging.info(f"  Signal: {pred['signal']}")
            logging.info(f"  Strategy: {pred['strategy_version']}")
            logging.info(f"  Model: {pred['prediction_model_version']}")
            logging.info("")
        
        return predictions
    
    def plot_calibration_curve(self, model_version: str = None, n_bins: int = 10):
        """Plot calibration curve showing how well predicted probabilities match actual outcomes."""
        # Get predictions from database
        if model_version:
            predictions = self.db.get_predictions_by_model_version(model_version)
        else:
            predictions = self.db.get_all_predictions()
        
        if not predictions:
            logging.warning("No prediction data found for calibration curve")
            return
        
        # Convert to DataFrame
        df = pd.DataFrame(predictions)
        
        # Drop entries where outcome is not yet known
        df = df.dropna(subset=["actual_outcome"])
        
        if df.empty:
            logging.warning("No predictions with known outcomes found for calibration curve")
            return
        
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
        
        title = "Model Calibration Curve"
        if model_version:
            title += f" - {model_version}"
        plt.title(title)
        
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.show()
    
    def database_summary(self):
        """Print overall database statistics."""
        stats = self.db.get_database_stats()
        
        logging.info("Database Summary:")
        logging.info("=" * 50)
        logging.info(f"Total Predictions: {stats.get('total_predictions', 0)}")
        logging.info(f"Total Games: {stats.get('total_games', 0)}")
        logging.info(f"Total Strategies: {stats.get('total_strategies', 0)}")
        logging.info(f"Total Models: {stats.get('total_models', 0)}")
        logging.info(f"Date Range: {stats.get('earliest_prediction', 'N/A')} to {stats.get('latest_prediction', 'N/A')}")


def main():
    """Main analysis function."""
    analyzer = BacktestAnalyzer()
    
    # Print database summary
    analyzer.database_summary()
    
    # Compare all strategies
    analyzer.compare_strategies()
    
    # Analyze model versions
    analyzer.analyze_model_versions()


if __name__ == "__main__":
    main()