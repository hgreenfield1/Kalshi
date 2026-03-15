import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager


class SignalAnalysisDatabase:
    """Database for statistical analysis of trading signals, agnostic of strategy versions."""
    
    def __init__(self, db_path: str = "signal_analysis.db"):
        self.db_path = Path(db_path)
        self._init_database()
    
    def _init_database(self):
        """Initialize the database with signal analysis table."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    predicted_price REAL,
                    bid_price REAL,
                    ask_price REAL,
                    prediction_model_version TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for better query performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_game_id 
                ON signal_data(game_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_timestamp 
                ON signal_data(timestamp)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_model_version 
                ON signal_data(prediction_model_version)
            """)
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
    
    def populate_from_backtest(self, backtest_db_path: str, model_version: str = "1.1.0"):
        """
        Populate signal analysis database from backtest database.
        
        Args:
            backtest_db_path: Path to the backtest predictions database
            model_version: Model version to filter by
        """
        backtest_conn = sqlite3.connect(backtest_db_path)
        backtest_conn.row_factory = sqlite3.Row
        
        try:
            # Query backtest database for specified model version with deduplication
            cursor = backtest_conn.execute("""
                SELECT DISTINCT
                    game_id,
                    timestamp,
                    predicted_prob as predicted_price,
                    bid_price,
                    ask_price,
                    prediction_model_version
                FROM predictions 
                WHERE prediction_model_version = ?
                ORDER BY timestamp
            """, (model_version,))
            
            signals = [dict(row) for row in cursor.fetchall()]
            
            with self._get_connection() as conn:
                # Clear existing data for this model version
                conn.execute("""
                    DELETE FROM signal_data 
                    WHERE prediction_model_version = ?
                """, (model_version,))
                
                # Insert new signal data
                for signal in signals:
                    conn.execute("""
                        INSERT INTO signal_data (
                            game_id, timestamp, predicted_price, bid_price, ask_price,
                            prediction_model_version
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        signal['game_id'],
                        signal['timestamp'],
                        signal['predicted_price'],
                        signal['bid_price'],
                        signal['ask_price'],
                        signal['prediction_model_version']
                    ))
                
                logging.info(f"Populated {len(signals)} signal records for model version {model_version}")
                
        finally:
            backtest_conn.close()
    
    def get_signals_by_model(self, model_version: str) -> List[Dict[str, Any]]:
        """Get all signals for a specific model version."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM signal_data 
                WHERE prediction_model_version = ?
                ORDER BY timestamp
            """, (model_version,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_signals(self) -> List[Dict[str, Any]]:
        """Get all signals from the database."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM signal_data
                ORDER BY timestamp
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_signal_statistics(self, model_version: str = None) -> Dict[str, Any]:
        """Get statistical summary of signals."""
        with self._get_connection() as conn:
            if model_version:
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_signals,
                        COUNT(DISTINCT game_id) as total_games,
                        AVG(predicted_price) as avg_predicted_price,
                        AVG(bid_price) as avg_bid_price,
                        AVG(ask_price) as avg_ask_price,
                        AVG(ask_price - bid_price) as avg_spread,
                        MIN(predicted_price) as min_predicted_price,
                        MAX(predicted_price) as max_predicted_price
                    FROM signal_data 
                    WHERE prediction_model_version = ?
                """, (model_version,))
            else:
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_signals,
                        COUNT(DISTINCT game_id) as total_games,
                        AVG(predicted_price) as avg_predicted_price,
                        AVG(bid_price) as avg_bid_price,
                        AVG(ask_price) as avg_ask_price,
                        AVG(ask_price - bid_price) as avg_spread,
                        MIN(predicted_price) as min_predicted_price,
                        MAX(predicted_price) as max_predicted_price
                    FROM signal_data
                """)
            
            result = cursor.fetchone()
            return dict(result) if result else {}
    
    def get_model_versions(self) -> List[str]:
        """Get all unique model versions in the database."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT prediction_model_version 
                FROM signal_data 
                ORDER BY prediction_model_version
            """)
            return [row[0] for row in cursor.fetchall()]