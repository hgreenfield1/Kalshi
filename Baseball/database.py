import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager


class BacktestDatabase:
    """Database manager for backtest predictions and results."""
    
    def __init__(self, db_path: str = "backtest_predictions.db"):
        self.db_path = Path(db_path)
        self._init_database()
    
    def _init_database(self):
        """Initialize the database with required tables."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
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
            
            # Create indexes for better query performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_game_id 
                ON predictions(game_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON predictions(timestamp)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_version 
                ON predictions(strategy_version)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_model_version 
                ON predictions(prediction_model_version)
            """)
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logging.error(f"Database operation failed: {e}")
            raise
        else:
            conn.commit()
        finally:
            conn.close()
    
    def save_predictions(self, predictions: List[Dict[str, Any]], actual_outcome: bool, 
                        prediction_model_version: str, strategy_version: str):
        """
        Save prediction data to the database.
        
        Args:
            predictions: List of prediction dictionaries
            actual_outcome: Whether the home team won
            prediction_model_version: Version of the prediction model used
            strategy_version: Version of the trading strategy used
        """
        if not predictions:
            logging.warning("No predictions to save")
            return
        
        with self._get_connection() as conn:
            for prediction in predictions:
                conn.execute("""
                    INSERT INTO predictions (
                        game_id, timestamp, predicted_prob, bid_price, ask_price,
                        cash, positions, signal, actual_outcome,
                        prediction_model_version, strategy_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    prediction['game_id'],
                    prediction['timestamp'],
                    prediction['mid_price'],
                    prediction['bid_price'],
                    prediction['ask_price'],
                    prediction['cash'],
                    prediction['positions'],
                    prediction['signal'],
                    actual_outcome,
                    prediction_model_version,
                    strategy_version
                ))
        
        logging.info(f"Saved {len(predictions)} predictions to database")
    
    def get_predictions_by_game(self, game_id: str) -> List[Dict[str, Any]]:
        """Get all predictions for a specific game."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM predictions WHERE game_id = ?
                ORDER BY timestamp
            """, (game_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_predictions_by_strategy_version(self, strategy_version: str) -> List[Dict[str, Any]]:
        """Get all predictions for a specific strategy version."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM predictions WHERE strategy_version = ?
                ORDER BY timestamp
            """, (strategy_version,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_predictions_by_model_version(self, model_version: str) -> List[Dict[str, Any]]:
        """Get all predictions for a specific model version."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM predictions WHERE prediction_model_version = ?
                ORDER BY timestamp
            """, (model_version,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_predictions(self) -> List[Dict[str, Any]]:
        """Get all predictions from the database."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM predictions
                ORDER BY timestamp
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_strategy_performance(self, strategy_version: str) -> Dict[str, Any]:
        """Get performance metrics for a strategy version."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_predictions,
                    COUNT(DISTINCT game_id) as total_games,
                    AVG(CASE WHEN predicted_prob IS NOT NULL THEN 
                        CASE WHEN actual_outcome = 1 AND predicted_prob > 50 THEN 1
                             WHEN actual_outcome = 0 AND predicted_prob < 50 THEN 1
                             ELSE 0 END
                    END) as prediction_accuracy,
                    AVG(cash) as avg_cash,
                    MIN(cash) as min_cash,
                    MAX(cash) as max_cash
                FROM predictions 
                WHERE strategy_version = ?
            """, (strategy_version,))
            
            result = cursor.fetchone()
            return dict(result) if result else {}
    
    def get_all_strategy_versions(self) -> List[str]:
        """Get all unique strategy versions in the database."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT strategy_version 
                FROM predictions 
                ORDER BY strategy_version
            """)
            return [row[0] for row in cursor.fetchall()]
    
    def get_all_model_versions(self) -> List[str]:
        """Get all unique prediction model versions in the database."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT prediction_model_version 
                FROM predictions 
                ORDER BY prediction_model_version
            """)
            return [row[0] for row in cursor.fetchall()]
    
    def delete_predictions_by_strategy(self, strategy_version: str) -> int:
        """Delete all predictions for a strategy version. Returns number of deleted rows."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM predictions WHERE strategy_version = ?
            """, (strategy_version,))
            return cursor.rowcount
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get general database statistics."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_predictions,
                    COUNT(DISTINCT game_id) as total_games,
                    COUNT(DISTINCT strategy_version) as total_strategies,
                    COUNT(DISTINCT prediction_model_version) as total_models,
                    MIN(created_at) as earliest_prediction,
                    MAX(created_at) as latest_prediction
                FROM predictions
            """)
            
            result = cursor.fetchone()
            return dict(result) if result else {}