#!/usr/bin/env python3
"""
Simple HTTP server API for backtest database viewer.
Serves data from the SQLite database to the web interface.
"""

import json
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import logging
from typing import Dict, List, Any, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BacktestAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for backtest data API."""
    
    def __init__(self, *args, db_path="backtest_predictions.db", **kwargs):
        self.db_path = Path(db_path)
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests."""
        try:
            parsed_url = urlparse(self.path)
            path = parsed_url.path
            query_params = parse_qs(parsed_url.query)
            
            # CORS headers for web browsers
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
            
            if path == '/api/predictions':
                response = self.get_predictions(query_params)
            elif path == '/api/games':
                response = self.get_games(query_params)
            elif path == '/api/strategies':
                response = self.get_strategies()
            elif path == '/api/models':
                response = self.get_models()
            elif path == '/api/stats':
                response = self.get_database_stats()
            elif path == '/api/performance':
                response = self.get_performance_metrics(query_params)
            elif path == '/api/calibration':
                response = self.get_calibration_data(query_params)
            else:
                response = {'error': 'Endpoint not found'}
            
            self.wfile.write(json.dumps(response, default=str).encode())
            
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            self.send_error(500, f"Internal server error: {e}")
    
    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def get_connection(self):
        """Get database connection."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_predictions(self, query_params: Dict[str, List[str]]) -> Dict[str, Any]:
        """Get predictions with optional filters."""
        with self.get_connection() as conn:
            # Build query with filters
            where_clauses = []
            params = []
            
            if 'game_id' in query_params and query_params['game_id'][0]:
                where_clauses.append('game_id = ?')
                params.append(query_params['game_id'][0])
            
            if 'strategy_version' in query_params and query_params['strategy_version'][0]:
                where_clauses.append('strategy_version = ?')
                params.append(query_params['strategy_version'][0])
            
            if 'model_version' in query_params and query_params['model_version'][0]:
                where_clauses.append('prediction_model_version = ?')
                params.append(query_params['model_version'][0])
            
            if 'start_date' in query_params and query_params['start_date'][0]:
                where_clauses.append('timestamp >= ?')
                params.append(query_params['start_date'][0])
            
            if 'end_date' in query_params and query_params['end_date'][0]:
                where_clauses.append('timestamp <= ?')
                params.append(query_params['end_date'][0])
            
            where_clause = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''
            
            # Get limit parameter
            limit = int(query_params.get('limit', [10000])[0])
            
            query = f"""
                SELECT * FROM predictions 
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params.append(limit)
            
            cursor = conn.execute(query, params)
            predictions = [dict(row) for row in cursor.fetchall()]
            
            return {
                'predictions': predictions,
                'count': len(predictions)
            }
    
    def get_games(self, query_params: Dict[str, List[str]] = None) -> Dict[str, Any]:
        """Get all unique game IDs with optional filters."""
        with self.get_connection() as conn:
            # Build filters
            where_clauses = []
            params = []
            
            if query_params:
                if 'strategy_version' in query_params and query_params['strategy_version'][0]:
                    where_clauses.append('strategy_version = ?')
                    params.append(query_params['strategy_version'][0])
                
                if 'model_version' in query_params and query_params['model_version'][0]:
                    where_clauses.append('prediction_model_version = ?')
                    params.append(query_params['model_version'][0])
            
            where_clause = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''
            
            cursor = conn.execute(f"""
                SELECT DISTINCT game_id, 
                       MIN(timestamp) as start_time,
                       MAX(timestamp) as end_time,
                       COUNT(*) as prediction_count,
                       MAX(actual_outcome) as outcome
                FROM predictions 
                {where_clause}
                GROUP BY game_id
                ORDER BY start_time DESC
            """, params)
            
            games = [dict(row) for row in cursor.fetchall()]
            return {'games': games}
    
    def get_strategies(self) -> Dict[str, Any]:
        """Get all strategy versions."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT strategy_version,
                       COUNT(*) as prediction_count,
                       COUNT(DISTINCT game_id) as game_count
                FROM predictions 
                GROUP BY strategy_version
                ORDER BY strategy_version
            """)
            
            strategies = [dict(row) for row in cursor.fetchall()]
            return {'strategies': strategies}
    
    def get_models(self) -> Dict[str, Any]:
        """Get all model versions."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT prediction_model_version,
                       COUNT(*) as prediction_count,
                       COUNT(DISTINCT game_id) as game_count
                FROM predictions 
                GROUP BY prediction_model_version
                ORDER BY prediction_model_version
            """)
            
            models = [dict(row) for row in cursor.fetchall()]
            return {'models': models}
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get general database statistics."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_predictions,
                    COUNT(DISTINCT game_id) as total_games,
                    COUNT(DISTINCT strategy_version) as total_strategies,
                    COUNT(DISTINCT prediction_model_version) as total_models,
                    MIN(created_at) as earliest_prediction,
                    MAX(created_at) as latest_prediction,
                    MIN(timestamp) as earliest_game_time,
                    MAX(timestamp) as latest_game_time
                FROM predictions
            """)
            
            result = cursor.fetchone()
            return dict(result) if result else {}
    
    def get_performance_metrics(self, query_params: Dict[str, List[str]]) -> Dict[str, Any]:
        """Get performance metrics with optional filters."""
        with self.get_connection() as conn:
            # Build filters
            where_clauses = []
            params = []
            
            if 'strategy_version' in query_params and query_params['strategy_version'][0]:
                where_clauses.append('strategy_version = ?')
                params.append(query_params['strategy_version'][0])
            
            if 'model_version' in query_params and query_params['model_version'][0]:
                where_clauses.append('prediction_model_version = ?')
                params.append(query_params['model_version'][0])
            
            where_clause = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''
            
            # Performance metrics query
            cursor = conn.execute(f"""
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
                    MAX(cash) as max_cash,
                    (MAX(cash) - 100.0) / 100.0 * 100 as roi_percent,
                    COUNT(CASE WHEN signal IS NOT NULL AND signal != 0 THEN 1 END) as total_trades,
                    AVG(CASE WHEN actual_outcome IS NOT NULL THEN actual_outcome END) as win_rate
                FROM predictions 
                {where_clause}
            """, params)
            
            result = cursor.fetchone()
            return dict(result) if result else {}
    
    def get_calibration_data(self, query_params: Dict[str, List[str]]) -> Dict[str, Any]:
        """Get calibration curve data for model predictions."""
        with self.get_connection() as conn:
            # Build filters
            where_clauses = []
            params = []
            
            if 'strategy_version' in query_params and query_params['strategy_version'][0]:
                where_clauses.append('strategy_version = ?')
                params.append(query_params['strategy_version'][0])
            
            if 'model_version' in query_params and query_params['model_version'][0]:
                where_clauses.append('prediction_model_version = ?')
                params.append(query_params['model_version'][0])
            
            where_clause = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''
            where_clause += ' AND actual_outcome IS NOT NULL' + (' AND ' if where_clauses else ' WHERE ')
            where_clause += 'predicted_prob IS NOT NULL AND bid_price IS NOT NULL AND ask_price IS NOT NULL'
            
            # Get raw data for calibration calculation
            cursor = conn.execute(f"""
                SELECT predicted_prob, bid_price, ask_price, actual_outcome
                FROM predictions 
                {where_clause}
                ORDER BY predicted_prob
            """, params)
            
            data = cursor.fetchall()
            
            if not data:
                logger.warning(f"No calibration data found with query: {where_clause}, params: {params}")
                return {'calibration_points': [], 'message': 'No data available for calibration'}
            
            logger.info(f"Found {len(data)} data points for calibration")
            
            # Calculate calibration bins (10 bins from 0-100)
            n_bins = 10
            bin_size = 100 / n_bins
            calibration_points = []
            
            for i in range(n_bins):
                bin_min = i * bin_size
                bin_max = (i + 1) * bin_size
                
                # Get data points in this bin
                if i == n_bins - 1:  # Last bin includes the maximum value
                    bin_data = [row for row in data if bin_min <= row[0] <= bin_max]
                else:
                    bin_data = [row for row in data if bin_min <= row[0] < bin_max]
                
                if len(bin_data) < 3:  # Skip bins with too few data points (reduced from 5 to 3)
                    continue
                
                # Calculate averages for this bin
                avg_predicted = sum(row[0] for row in bin_data) / len(bin_data)
                avg_bid = sum(row[1] for row in bin_data) / len(bin_data)
                avg_ask = sum(row[2] for row in bin_data) / len(bin_data)
                actual_win_rate = sum(row[3] for row in bin_data) / len(bin_data) * 100  # Convert to percentage
                count = len(bin_data)
                
                calibration_points.append({
                    'bin_min': bin_min,
                    'bin_max': bin_max,
                    'avg_predicted': avg_predicted,
                    'avg_bid': avg_bid,
                    'avg_ask': avg_ask,
                    'actual_win_rate': actual_win_rate,
                    'count': count
                })
            
            return {
                'calibration_points': calibration_points,
                'total_predictions': len(data)
            }


def create_handler_class(db_path: str):
    """Create a handler class with the specified database path."""
    class Handler(BacktestAPIHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, db_path=db_path, **kwargs)
    return Handler


def start_server(port: int = 8000, db_path: str = "backtest_predictions.db"):
    """Start the HTTP server."""
    handler_class = create_handler_class(db_path)
    server = HTTPServer(('localhost', port), handler_class)
    
    logger.info(f"Starting backtest API server on http://localhost:{port}")
    logger.info(f"Using database: {db_path}")
    logger.info("API endpoints:")
    logger.info("  /api/predictions - Get prediction data")
    logger.info("  /api/games - Get game list")
    logger.info("  /api/strategies - Get strategy versions")
    logger.info("  /api/models - Get model versions")
    logger.info("  /api/stats - Get database statistics")
    logger.info("  /api/performance - Get performance metrics")
    logger.info("  /api/calibration - Get model calibration data")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        server.shutdown()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Backtest API Server')
    parser.add_argument('--port', type=int, default=8000, help='Port to run server on')
    parser.add_argument('--db', default='backtest_predictions.db', help='Database file path')
    
    args = parser.parse_args()
    start_server(args.port, args.db)