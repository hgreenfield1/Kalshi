#!/usr/bin/env python3
"""
Simple timeseries analysis of trading signals using only standard library.
Analyzes if predicted_price has significance in predicting future bid and ask prices.
"""

import sqlite3
import math
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


class SimpleTimeseriesAnalyzer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.data = []
        
    def load_data(self):
        """Load signal data from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT 
                game_id,
                timestamp,
                predicted_price,
                bid_price,
                ask_price
            FROM signal_data 
            ORDER BY game_id, timestamp
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        # Convert to list of dictionaries with datetime objects
        for row in rows:
            try:
                # Skip rows with 'FINAL' timestamp (seems to be end-of-game markers)
                if row[1] == 'FINAL':
                    continue
                    
                # Parse timestamp
                ts_str = row[1].replace('Z', '') if row[1].endswith('Z') else row[1]
                timestamp = datetime.fromisoformat(ts_str)
                
                # Skip records with missing prices
                if row[2] is None or row[3] is None or row[4] is None:
                    continue
                
                record = {
                    'game_id': row[0],
                    'timestamp': timestamp,
                    'predicted_price': float(row[2]),
                    'bid_price': float(row[3]),
                    'ask_price': float(row[4]),
                    'mid_price': (float(row[3]) + float(row[4])) / 2
                }
                self.data.append(record)
            except Exception as e:
                continue  # Skip problematic rows silently
        
        unique_games = len(set(record['game_id'] for record in self.data))
        print(f"Loaded {len(self.data)} records from {unique_games} games")
        return self.data
    
    def calculate_correlation(self, x_values, y_values):
        """Calculate Pearson correlation coefficient manually."""
        if len(x_values) != len(y_values) or len(x_values) < 2:
            return 0, 1  # correlation, p_value
        
        n = len(x_values)
        
        # Calculate means
        mean_x = sum(x_values) / n
        mean_y = sum(y_values) / n
        
        # Calculate correlation coefficient
        numerator = sum((x_values[i] - mean_x) * (y_values[i] - mean_y) for i in range(n))
        sum_sq_x = sum((x_values[i] - mean_x) ** 2 for i in range(n))
        sum_sq_y = sum((y_values[i] - mean_y) ** 2 for i in range(n))
        
        if sum_sq_x == 0 or sum_sq_y == 0:
            return 0, 1
        
        correlation = numerator / math.sqrt(sum_sq_x * sum_sq_y)
        
        # Simple t-test for significance (approximation)
        if abs(correlation) < 0.001:
            p_value = 1.0
        else:
            t_stat = correlation * math.sqrt((n - 2) / (1 - correlation ** 2))
            # Very rough p-value approximation
            p_value = 2 * (1 - abs(t_stat) / (abs(t_stat) + math.sqrt(n - 2)))
        
        return correlation, p_value
    
    def analyze_predictive_power(self, time_intervals_minutes=[1, 2, 5, 10, 15, 30]):
        """Analyze predictive power at different time intervals."""
        
        # Group data by game
        games_data = defaultdict(list)
        for record in self.data:
            games_data[record['game_id']].append(record)
        
        # Sort each game's data by timestamp
        for game_id in games_data:
            games_data[game_id].sort(key=lambda x: x['timestamp'])
        
        results = {}
        
        for interval in time_intervals_minutes:
            print(f"Analyzing {interval}-minute interval...")
            
            # Collect pairs for analysis
            predicted_prices = []
            future_bids = []
            future_asks = []
            future_mids = []
            
            for game_id, game_records in games_data.items():
                for i, record in enumerate(game_records):
                    if record['predicted_price'] is None:
                        continue
                    
                    # Find future record
                    target_time = record['timestamp'] + timedelta(minutes=interval)
                    future_record = None
                    
                    # Look for the closest record after target time
                    for j in range(i + 1, len(game_records)):
                        if game_records[j]['timestamp'] >= target_time:
                            future_record = game_records[j]
                            break
                    
                    if future_record and all(future_record[key] is not None 
                                           for key in ['bid_price', 'ask_price']):
                        predicted_prices.append(record['predicted_price'])
                        future_bids.append(future_record['bid_price'])
                        future_asks.append(future_record['ask_price'])
                        future_mids.append(future_record['mid_price'])
            
            if len(predicted_prices) < 10:  # Need minimum samples
                print(f"Insufficient data for {interval}-minute interval")
                continue
            
            # Calculate correlations
            corr_bid, p_bid = self.calculate_correlation(predicted_prices, future_bids)
            corr_ask, p_ask = self.calculate_correlation(predicted_prices, future_asks)
            corr_mid, p_mid = self.calculate_correlation(predicted_prices, future_mids)
            
            # Calculate basic statistics
            mean_pred = sum(predicted_prices) / len(predicted_prices)
            mean_bid = sum(future_bids) / len(future_bids)
            mean_ask = sum(future_asks) / len(future_asks)
            mean_mid = sum(future_mids) / len(future_mids)
            
            # Calculate MAE (simple version)
            mae_bid = sum(abs(predicted_prices[i] - future_bids[i]) for i in range(len(predicted_prices))) / len(predicted_prices)
            mae_ask = sum(abs(predicted_prices[i] - future_asks[i]) for i in range(len(predicted_prices))) / len(predicted_prices)
            mae_mid = sum(abs(predicted_prices[i] - future_mids[i]) for i in range(len(predicted_prices))) / len(predicted_prices)
            
            results[interval] = {
                'n_samples': len(predicted_prices),
                'correlations': {
                    'bid': corr_bid,
                    'ask': corr_ask,
                    'mid': corr_mid
                },
                'p_values': {
                    'bid': p_bid,
                    'ask': p_ask,
                    'mid': p_mid
                },
                'means': {
                    'predicted': mean_pred,
                    'bid': mean_bid,
                    'ask': mean_ask,
                    'mid': mean_mid
                },
                'mae': {
                    'bid': mae_bid,
                    'ask': mae_ask,
                    'mid': mae_mid
                }
            }
        
        return results
    
    def generate_report(self, results):
        """Generate analysis report."""
        
        print("\n" + "="*80)
        print("TIMESERIES ANALYSIS REPORT")
        print("="*80)
        print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Records: {len(self.data):,}")
        
        unique_games = len(set(record['game_id'] for record in self.data))
        print(f"Total Games: {unique_games:,}")
        
        print("\n" + "-"*60)
        print("PREDICTIVE POWER ANALYSIS")
        print("-"*60)
        
        for interval in sorted(results.keys()):
            result = results[interval]
            
            print(f"\nTime Interval: {interval} minutes")
            print(f"Sample Size: {result['n_samples']:,}")
            
            print("\nCorrelations with Predicted Price:")
            print(f"  Bid Price:  {result['correlations']['bid']:.4f}")
            print(f"  Ask Price:  {result['correlations']['ask']:.4f}")
            print(f"  Mid Price:  {result['correlations']['mid']:.4f}")
            
            print("\nStatistical Significance (p-values):")
            print(f"  Bid Price:  {result['p_values']['bid']:.4f}")
            print(f"  Ask Price:  {result['p_values']['ask']:.4f}")
            print(f"  Mid Price:  {result['p_values']['mid']:.4f}")
            
            print("\nMean Absolute Error:")
            print(f"  Bid Price:  {result['mae']['bid']:.4f}")
            print(f"  Ask Price:  {result['mae']['ask']:.4f}")
            print(f"  Mid Price:  {result['mae']['mid']:.4f}")
            
            # Significance assessment
            significant_bid = result['p_values']['bid'] < 0.05
            significant_ask = result['p_values']['ask'] < 0.05
            significant_mid = result['p_values']['mid'] < 0.05
            
            print("\nSignificance Assessment:")
            print(f"  Bid Price:  {'SIGNIFICANT' if significant_bid else 'NOT SIGNIFICANT'}")
            print(f"  Ask Price:  {'SIGNIFICANT' if significant_ask else 'NOT SIGNIFICANT'}")
            print(f"  Mid Price:  {'SIGNIFICANT' if significant_mid else 'NOT SIGNIFICANT'}")
        
        # Summary insights
        print("\n" + "-"*60)
        print("KEY INSIGHTS")
        print("-"*60)
        
        if not results:
            print("No results to analyze")
            return
        
        # Find best correlations
        best_bid_interval = max(results.keys(), key=lambda x: abs(results[x]['correlations']['bid']))
        best_ask_interval = max(results.keys(), key=lambda x: abs(results[x]['correlations']['ask']))
        best_mid_interval = max(results.keys(), key=lambda x: abs(results[x]['correlations']['mid']))
        
        print(f"\nStrongest Correlations:")
        print(f"  Bid Price: {results[best_bid_interval]['correlations']['bid']:.4f} at {best_bid_interval} minutes")
        print(f"  Ask Price: {results[best_ask_interval]['correlations']['ask']:.4f} at {best_ask_interval} minutes")
        print(f"  Mid Price: {results[best_mid_interval]['correlations']['mid']:.4f} at {best_mid_interval} minutes")
        
        # Check if any relationships are strong
        max_corr = max([max(abs(results[i]['correlations']['bid']), 
                           abs(results[i]['correlations']['ask']), 
                           abs(results[i]['correlations']['mid'])) for i in results.keys()])
        
        if max_corr > 0.5:
            print(f"\n[STRONG] Strong predictive relationship found (max |correlation|: {max_corr:.4f})")
        elif max_corr > 0.3:
            print(f"\n[MODERATE] Moderate predictive relationship found (max |correlation|: {max_corr:.4f})")
        else:
            print(f"\n[WEAK] Weak predictive relationship (max |correlation|: {max_corr:.4f})")
        
        # Check significance across intervals
        significant_intervals = []
        for interval in results.keys():
            if any(p < 0.05 for p in results[interval]['p_values'].values()):
                significant_intervals.append(interval)
        
        if significant_intervals:
            print(f"\nStatistically significant relationships found at: {significant_intervals} minutes")
        else:
            print(f"\nNo statistically significant relationships found")
        
        # Practical interpretation
        print("\n" + "-"*60)
        print("PRACTICAL INTERPRETATION")
        print("-"*60)
        
        print("\nThis analysis examines whether the model's predicted price can forecast")
        print("future market bid/ask prices at different time horizons.")
        print("\nKey findings:")
        
        for interval in sorted(results.keys()):
            result = results[interval]
            corr_strength = max(abs(result['correlations']['bid']), 
                              abs(result['correlations']['ask']), 
                              abs(result['correlations']['mid']))
            
            if corr_strength > 0.3:
                print(f"  - At {interval} minutes: Model shows predictive power (correlation: {corr_strength:.3f})")
            elif corr_strength > 0.1:
                print(f"  - At {interval} minutes: Weak predictive signal (correlation: {corr_strength:.3f})")
            else:
                print(f"  - At {interval} minutes: No meaningful predictive power")


def main():
    """Run the timeseries analysis."""
    
    db_path = Path(__file__).parent / "signal_analysis.db"
    
    if not db_path.exists():
        print(f"Error: Signal database not found at {db_path}")
        print("Please run create_signal_db.py first")
        return 1
    
    print("Starting Simple Timeseries Analysis...")
    
    # Initialize analyzer
    analyzer = SimpleTimeseriesAnalyzer(str(db_path))
    
    # Load data
    print("Loading data...")
    analyzer.load_data()
    
    # Analyze predictive power
    print("Analyzing predictive power...")
    time_intervals = [1, 2, 5, 10, 15, 30]  # minutes
    results = analyzer.analyze_predictive_power(time_intervals)
    
    # Generate report
    analyzer.generate_report(results)
    
    return 0


if __name__ == "__main__":
    exit(main())