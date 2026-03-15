import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any
from contextlib import contextmanager

class BacktestDatabase:
    """New database schema for multi-market backtesting."""

    def __init__(self, db_path: str = "backtest_predictions.db"):
        self.db_path = Path(db_path)
        self._init_database()

    def _init_database(self):
        """Initialize database with new schema."""
        with self._get_connection() as conn:
            # Main predictions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_type TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    predicted_prob REAL,
                    bid_price REAL,
                    ask_price REAL,
                    cash REAL NOT NULL,
                    positions INTEGER NOT NULL,
                    signal INTEGER,
                    actual_outcome BOOLEAN,
                    prediction_model_version TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_type
                ON predictions(market_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_id
                ON predictions(market_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy
                ON predictions(strategy_version)
            """)

    @contextmanager
    def _get_connection(self):
        """Context manager for connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logging.error(f"Database error: {e}")
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def save_predictions(self, market_type: str, predictions: List[Dict[str, Any]],
                        actual_outcome: bool, prediction_model_version: str,
                        strategy_version: str):
        """Save predictions to database."""
        if not predictions:
            logging.warning("No predictions to save")
            return

        market_id = predictions[0]['market_id']

        with self._get_connection() as conn:
            # Delete existing predictions for this market/strategy
            conn.execute("""
                DELETE FROM predictions
                WHERE market_id = ? AND strategy_version = ?
            """, (market_id, strategy_version))

            # Insert new predictions
            for pred in predictions:
                conn.execute("""
                    INSERT INTO predictions (
                        market_type, market_id, timestamp, predicted_prob,
                        bid_price, ask_price, cash, positions, signal,
                        actual_outcome, prediction_model_version, strategy_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    market_type,
                    pred['market_id'],
                    pred['timestamp'],
                    pred.get('mid_price'),
                    pred.get('bid_price'),
                    pred.get('ask_price'),
                    pred['cash'],
                    pred['positions'],
                    pred.get('signal'),
                    actual_outcome,
                    prediction_model_version,
                    strategy_version
                ))

        logging.info(f"Saved {len(predictions)} predictions for {market_id}")

    def get_predictions_by_market_type(self, market_type: str) -> List[Dict[str, Any]]:
        """Get all predictions for a market type."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM predictions
                WHERE market_type = ?
                ORDER BY timestamp
            """, (market_type,))
            return [dict(row) for row in cursor.fetchall()]
