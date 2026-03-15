#!/usr/bin/env python3
"""
Script to create and populate the signal analysis database from backtest data.
Filters to Model Version 1.1.0 and extracts predicted price, bid price, and ask price.
"""

import sys
import logging
from pathlib import Path

# Add parent directory to path to import signal_database
sys.path.append(str(Path(__file__).parent))

from signal_database import SignalAnalysisDatabase

def main():
    """Create and populate signal analysis database."""
    logging.basicConfig(level=logging.INFO)
    
    # Paths
    backtest_db_path = Path(__file__).parent.parent.parent / "backtest_predictions.db"
    signal_db_path = Path(__file__).parent / "signal_analysis.db"
    
    if not backtest_db_path.exists():
        print(f"Error: Backtest database not found at {backtest_db_path}")
        return 1
    
    print(f"Creating signal analysis database at {signal_db_path}")
    print(f"Source: {backtest_db_path}")
    print("Filtering to Model Version: 1.1.0")
    print("Columns: predicted_price, bid_price, ask_price")
    
    # Create and populate database
    signal_db = SignalAnalysisDatabase(str(signal_db_path))
    
    try:
        signal_db.populate_from_backtest(str(backtest_db_path), model_version="1.1.0")
        
        # Get statistics
        stats = signal_db.get_signal_statistics("1.1.0")
        
        print("\nDatabase created successfully!")
        print(f"Total signals: {stats.get('total_signals', 0)}")
        print(f"Total games: {stats.get('total_games', 0)}")
        print(f"Average predicted price: {stats.get('avg_predicted_price', 0):.4f}")
        print(f"Average bid price: {stats.get('avg_bid_price', 0):.4f}")
        print(f"Average ask price: {stats.get('avg_ask_price', 0):.4f}")
        print(f"Average spread: {stats.get('avg_spread', 0):.4f}")
        
        return 0
        
    except Exception as e:
        print(f"Error creating database: {e}")
        logging.error(f"Database creation failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())