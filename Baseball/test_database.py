#!/usr/bin/env python3
"""
Test suite for the refactored backtest database system.
"""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from Baseball.database import BacktestDatabase
from Baseball.Strategies.backtest_strategies import SimpleBacktestStrategy
from Baseball.BaseballGame import BaseballGame


class TestBacktestDatabase(unittest.TestCase):
    """Test cases for BacktestDatabase functionality."""
    
    def setUp(self):
        """Set up test database with temporary file."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db = BacktestDatabase(self.temp_db.name)
    
    def tearDown(self):
        """Clean up temporary database file."""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
    
    def test_database_initialization(self):
        """Test that database initializes correctly with proper schema."""
        # Verify that the predictions table exists
        with self.db._get_connection() as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='predictions'
            """)
            self.assertIsNotNone(cursor.fetchone())
            
            # Verify indexes exist
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND name LIKE 'idx_%'
            """)
            indexes = cursor.fetchall()
            self.assertGreaterEqual(len(indexes), 4)  # Should have at least 4 indexes
    
    def test_save_and_retrieve_predictions(self):
        """Test saving predictions and retrieving them."""
        test_predictions = [
            {
                'game_id': 'test_game_1',
                'timestamp': '2025-01-01T12:00:00Z',
                'mid_price': 65.5,
                'bid_price': 64.0,
                'ask_price': 66.0,
                'cash': 105.5,
                'positions': 2,
                'signal': 1
            },
            {
                'game_id': 'test_game_1',
                'timestamp': '2025-01-01T12:01:00Z',
                'mid_price': 67.2,
                'bid_price': 66.0,
                'ask_price': 68.0,
                'cash': 103.2,
                'positions': 1,
                'signal': -1
            }
        ]
        
        # Save predictions
        self.db.save_predictions(
            predictions=test_predictions,
            actual_outcome=True,
            prediction_model_version="1.0.0",
            strategy_version="1.1.0"
        )
        
        # Retrieve by game ID
        retrieved = self.db.get_predictions_by_game('test_game_1')
        self.assertEqual(len(retrieved), 2)
        self.assertEqual(retrieved[0]['game_id'], 'test_game_1')
        self.assertEqual(retrieved[0]['predicted_prob'], 65.5)  # mid_price maps to predicted_prob
        self.assertTrue(retrieved[0]['actual_outcome'])
        
        # Retrieve by strategy version
        strategy_predictions = self.db.get_predictions_by_strategy_version('1.1.0')
        self.assertEqual(len(strategy_predictions), 2)
        
        # Retrieve by model version
        model_predictions = self.db.get_predictions_by_model_version('1.0.0')
        self.assertEqual(len(model_predictions), 2)
    
    def test_strategy_performance_metrics(self):
        """Test strategy performance calculation."""
        # Add test data with mixed outcomes
        test_predictions = [
            {
                'game_id': 'game1', 'timestamp': '2025-01-01T12:00:00Z',
                'mid_price': 75.0, 'bid_price': 74.0, 'ask_price': 76.0,
                'cash': 110.0, 'positions': 1, 'signal': 1
            },
            {
                'game_id': 'game2', 'timestamp': '2025-01-02T12:00:00Z',
                'mid_price': 25.0, 'bid_price': 24.0, 'ask_price': 26.0,
                'cash': 95.0, 'positions': -1, 'signal': -1
            }
        ]
        
        # Save predictions for winning games (predicted > 50, actual = True)
        self.db.save_predictions(test_predictions[:1], True, "1.0.0", "test_v1")
        # Save predictions for losing games (predicted < 50, actual = False)  
        self.db.save_predictions(test_predictions[1:], False, "1.0.0", "test_v1")
        
        performance = self.db.get_strategy_performance('test_v1')
        
        self.assertEqual(performance['total_predictions'], 2)
        self.assertEqual(performance['total_games'], 2)
        self.assertEqual(performance['prediction_accuracy'], 1.0)  # Both predictions correct
        self.assertEqual(performance['avg_cash'], 102.5)  # (110 + 95) / 2
    
    def test_database_stats(self):
        """Test overall database statistics."""
        # Add some test data
        test_predictions = [{
            'game_id': 'stats_test', 'timestamp': '2025-01-01T12:00:00Z',
            'mid_price': 50.0, 'bid_price': 49.0, 'ask_price': 51.0,
            'cash': 100.0, 'positions': 0, 'signal': 0
        }]
        
        self.db.save_predictions(test_predictions, True, "model_v1", "strategy_v1")
        self.db.save_predictions(test_predictions, False, "model_v2", "strategy_v2")
        
        stats = self.db.get_database_stats()
        
        self.assertEqual(stats['total_predictions'], 2)
        self.assertEqual(stats['total_games'], 1)  # Same game_id
        self.assertEqual(stats['total_strategies'], 2)
        self.assertEqual(stats['total_models'], 2)
    
    def test_empty_predictions_handling(self):
        """Test handling of empty prediction lists."""
        # Should not raise an error
        self.db.save_predictions([], True, "1.0.0", "1.0.0")
        
        # Should return empty list
        result = self.db.get_predictions_by_game('nonexistent')
        self.assertEqual(len(result), 0)


class TestStrategyIntegration(unittest.TestCase):
    """Test integration between strategies and database."""
    
    def setUp(self):
        """Set up test strategy with temporary database."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.strategy = SimpleBacktestStrategy(self.temp_db.name)
    
    def tearDown(self):
        """Clean up temporary database file."""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
    
    def test_strategy_versions(self):
        """Test that strategy has correct version properties."""
        self.assertEqual(self.strategy.version, "1.1.0")
        self.assertEqual(self.strategy.prediction_model_version, "1.1.0")
    
    def test_prediction_logging(self):
        """Test that strategies log predictions correctly."""
        # Mock a game
        mock_game = Mock()
        mock_game.game_id = "test_game_123"
        mock_game.pregame_winProbability = 55.0
        mock_game.winProbability = 60.0
        mock_game.pctPlayed = 0.3
        mock_game.net_score = 0
        
        # Simulate trading
        self.strategy.trade("2025-01-01T12:00:00Z", mock_game, 59.0, 61.0)
        
        # Check that prediction was logged
        self.assertEqual(len(self.strategy.prediction_log), 1)
        prediction = self.strategy.prediction_log[0]
        self.assertEqual(prediction['game_id'], "test_game_123")
        self.assertIsNotNone(prediction['mid_price'])
    
    def test_post_process_saves_to_db(self):
        """Test that post_process saves predictions to database."""
        # Add a mock prediction
        self.strategy.prediction_log = [{
            'game_id': 'test_save',
            'timestamp': '2025-01-01T12:00:00Z',
            'mid_price': 65.0,
            'bid_price': 64.0,
            'ask_price': 66.0,
            'cash': 100.0,
            'positions': 0,
            'signal': None
        }]
        
        # Mock game with final score
        mock_game = Mock()
        mock_game.net_score = 3  # Home team wins
        
        # Process and save
        self.strategy.post_process(mock_game, save_to_db=True)
        
        # Verify data was saved
        predictions = self.strategy.db.get_predictions_by_game('test_save')
        self.assertEqual(len(predictions), 1)
        self.assertTrue(predictions[0]['actual_outcome'])  # Home team won


class TestAnalyzer(unittest.TestCase):
    """Test the database analyzer functionality."""
    
    def setUp(self):
        """Set up test database with sample data."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db = BacktestDatabase(self.temp_db.name)
        
        # Add sample data
        sample_predictions = [
            {
                'game_id': 'analyzer_test_1',
                'timestamp': '2025-01-01T12:00:00Z',
                'mid_price': 70.0,
                'bid_price': 69.0,
                'ask_price': 71.0,
                'cash': 105.0,
                'positions': 1,
                'signal': 1
            }
        ]
        
        self.db.save_predictions(sample_predictions, True, "analyzer_model_1.0", "analyzer_strategy_1.0")
    
    def tearDown(self):
        """Clean up temporary database file."""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
    
    def test_analyzer_import(self):
        """Test that analyzer can be imported and initialized."""
        from Baseball.analyze_database import BacktestAnalyzer
        analyzer = BacktestAnalyzer(self.temp_db.name)
        self.assertIsNotNone(analyzer)
        
        # Test that it can retrieve data
        stats = analyzer.db.get_database_stats()
        self.assertEqual(stats['total_predictions'], 1)


def run_manual_integration_test():
    """Run a manual integration test with the full strategy."""
    print("Running manual integration test...")
    
    # Create temporary database
    temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    temp_db.close()
    
    try:
        # Initialize strategy
        strategy = SimpleBacktestStrategy(temp_db.name)
        print(f"Strategy version: {strategy.version}")
        print(f"Model version: {strategy.prediction_model_version}")
        
        # Mock a complete game scenario
        mock_game = Mock()
        mock_game.game_id = "integration_test_game"
        mock_game.pregame_winProbability = 52.0
        mock_game.winProbability = 58.0
        mock_game.pctPlayed = 0.5
        mock_game.net_score = 2  # Home team winning
        
        # Simulate several trading decisions
        timestamps = [
            "2025-01-01T19:00:00Z",
            "2025-01-01T19:30:00Z", 
            "2025-01-01T20:00:00Z",
            "2025-01-01T20:30:00Z"
        ]
        
        bid_ask_pairs = [(57, 59), (56, 58), (55, 57), (54, 56)]
        
        for ts, (bid, ask) in zip(timestamps, bid_ask_pairs):
            strategy.trade(ts, mock_game, bid, ask)
        
        print(f"Generated {len(strategy.prediction_log)} predictions")
        print(f"Final cash: ${strategy.cash:.2f}")
        print(f"Final positions: {strategy.positions}")
        
        # Save to database
        strategy.post_process(mock_game, save_to_db=True)
        
        # Verify data was saved
        predictions = strategy.db.get_predictions_by_game("integration_test_game")
        print(f"Saved {len(predictions)} predictions to database")
        
        # Test analyzer
        from Baseball.analyze_database import BacktestAnalyzer
        analyzer = BacktestAnalyzer(temp_db.name)
        performance = analyzer.analyze_strategy_performance("1.1.0")
        
        print("Integration test completed successfully!")
        return True
        
    except Exception as e:
        print(f"Integration test failed: {e}")
        return False
    finally:
        # Clean up
        if os.path.exists(temp_db.name):
            os.unlink(temp_db.name)


if __name__ == "__main__":
    print("Running backtest database system tests...")
    print("=" * 50)
    
    # Run unit tests
    unittest.main(verbosity=2, exit=False)
    
    print("\n" + "=" * 50)
    print("Running manual integration test...")
    
    # Run integration test
    success = run_manual_integration_test()
    
    if success:
        print("\n✅ All tests passed! The refactored system is working correctly.")
    else:
        print("\n❌ Integration test failed. Please check the implementation.")