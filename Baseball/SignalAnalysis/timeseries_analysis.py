#!/usr/bin/env python3
"""
Timeseries analysis of trading signals to analyze if predicted_price has significance
in predicting future bid and ask prices over different time intervals.
"""

import sqlite3
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import warnings
from pathlib import Path
import sys
import math

warnings.filterwarnings('ignore')

class TimeseriesAnalyzer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.df = None
        
    def load_data(self):
        """Load signal data from database and prepare for analysis."""
        conn = sqlite3.connect(self.db_path)
        
        query = """
        SELECT 
            game_id,
            timestamp,
            predicted_price,
            bid_price,
            ask_price,
            prediction_model_version
        FROM signal_data 
        ORDER BY game_id, timestamp
        """
        
        self.df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Convert timestamp strings to datetime objects manually
        timestamps = []
        for ts in self.df['timestamp']:
            timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
        self.df['timestamp'] = timestamps
        
        # Calculate mid price and spread
        mid_prices = []
        spreads = []
        for i in range(len(self.df)):
            bid = self.df['bid_price'][i]
            ask = self.df['ask_price'][i]
            mid_prices.append((bid + ask) / 2)
            spreads.append(ask - bid)
        
        self.df['mid_price'] = mid_prices
        self.df['spread'] = spreads
        
        print(f"Loaded {len(self.df)} records from {self.df['game_id'].nunique()} games")
        return self.df
    
    def create_lagged_features(self, time_intervals_minutes=[1, 2, 5, 10, 15, 30]):
        """Create lagged features for future bid/ask prices at different time intervals."""
        
        results = []
        
        for game_id in self.df['game_id'].unique():
            game_data = self.df[self.df['game_id'] == game_id].copy()
            game_data = game_data.sort_values('timestamp')
            
            for interval in time_intervals_minutes:
                future_time = game_data['timestamp'] + pd.Timedelta(minutes=interval)
                
                # Find future bid/ask prices
                future_bid = []
                future_ask = []
                future_mid = []
                
                for i, row in game_data.iterrows():
                    target_time = row['timestamp'] + pd.Timedelta(minutes=interval)
                    
                    # Find closest record after target time
                    future_records = game_data[game_data['timestamp'] >= target_time]
                    
                    if len(future_records) > 0:
                        closest_record = future_records.iloc[0]
                        future_bid.append(closest_record['bid_price'])
                        future_ask.append(closest_record['ask_price'])
                        future_mid.append(closest_record['mid_price'])
                    else:
                        future_bid.append(np.nan)
                        future_ask.append(np.nan)
                        future_mid.append(np.nan)
                
                game_data[f'future_bid_{interval}m'] = future_bid
                game_data[f'future_ask_{interval}m'] = future_ask
                game_data[f'future_mid_{interval}m'] = future_mid
            
            results.append(game_data)
        
        self.df_lagged = pd.concat(results, ignore_index=True)
        print(f"Created lagged features for {len(time_intervals_minutes)} time intervals")
        return self.df_lagged
    
    def analyze_predictive_power(self, time_intervals_minutes=[1, 2, 5, 10, 15, 30]):
        """Analyze the predictive power of predicted_price for future bid/ask prices."""
        
        results = {}
        
        for interval in time_intervals_minutes:
            bid_col = f'future_bid_{interval}m'
            ask_col = f'future_ask_{interval}m'
            mid_col = f'future_mid_{interval}m'
            
            # Remove NaN values
            valid_data = self.df_lagged[[
                'predicted_price', bid_col, ask_col, mid_col
            ]].dropna()
            
            if len(valid_data) == 0:
                continue
            
            # Correlation analysis
            corr_bid = valid_data['predicted_price'].corr(valid_data[bid_col])
            corr_ask = valid_data['predicted_price'].corr(valid_data[ask_col])
            corr_mid = valid_data['predicted_price'].corr(valid_data[mid_col])
            
            # Statistical significance tests
            _, p_bid = stats.pearsonr(valid_data['predicted_price'], valid_data[bid_col])
            _, p_ask = stats.pearsonr(valid_data['predicted_price'], valid_data[ask_col])
            _, p_mid = stats.pearsonr(valid_data['predicted_price'], valid_data[mid_col])
            
            # Linear regression analysis
            X = valid_data[['predicted_price']]
            
            # Bid price prediction
            lr_bid = LinearRegression().fit(X, valid_data[bid_col])
            pred_bid = lr_bid.predict(X)
            r2_bid = lr_bid.score(X, valid_data[bid_col])
            mse_bid = mean_squared_error(valid_data[bid_col], pred_bid)
            mae_bid = mean_absolute_error(valid_data[bid_col], pred_bid)
            
            # Ask price prediction
            lr_ask = LinearRegression().fit(X, valid_data[ask_col])
            pred_ask = lr_ask.predict(X)
            r2_ask = lr_ask.score(X, valid_data[ask_col])
            mse_ask = mean_squared_error(valid_data[ask_col], pred_ask)
            mae_ask = mean_absolute_error(valid_data[ask_col], pred_ask)
            
            # Mid price prediction
            lr_mid = LinearRegression().fit(X, valid_data[mid_col])
            pred_mid = lr_mid.predict(X)
            r2_mid = lr_mid.score(X, valid_data[mid_col])
            mse_mid = mean_squared_error(valid_data[mid_col], pred_mid)
            mae_mid = mean_absolute_error(valid_data[mid_col], pred_mid)
            
            results[interval] = {
                'n_samples': len(valid_data),
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
                'r_squared': {
                    'bid': r2_bid,
                    'ask': r2_ask,
                    'mid': r2_mid
                },
                'mse': {
                    'bid': mse_bid,
                    'ask': mse_ask,
                    'mid': mse_mid
                },
                'mae': {
                    'bid': mae_bid,
                    'ask': mae_ask,
                    'mid': mae_mid
                },
                'coefficients': {
                    'bid': lr_bid.coef_[0],
                    'ask': lr_ask.coef_[0],
                    'mid': lr_mid.coef_[0]
                },
                'intercepts': {
                    'bid': lr_bid.intercept_,
                    'ask': lr_ask.intercept_,
                    'mid': lr_mid.intercept_
                }
            }
        
        return results
    
    def create_visualizations(self, results, output_dir="plots"):
        """Create visualizations of the analysis results."""
        
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # Extract data for plotting
        intervals = list(results.keys())
        
        corr_bid = [results[i]['correlations']['bid'] for i in intervals]
        corr_ask = [results[i]['correlations']['ask'] for i in intervals]
        corr_mid = [results[i]['correlations']['mid'] for i in intervals]
        
        r2_bid = [results[i]['r_squared']['bid'] for i in intervals]
        r2_ask = [results[i]['r_squared']['ask'] for i in intervals]
        r2_mid = [results[i]['r_squared']['mid'] for i in intervals]
        
        p_bid = [results[i]['p_values']['bid'] for i in intervals]
        p_ask = [results[i]['p_values']['ask'] for i in intervals]
        p_mid = [results[i]['p_values']['mid'] for i in intervals]
        
        # Plot correlations
        plt.figure(figsize=(12, 8))
        
        plt.subplot(2, 2, 1)
        plt.plot(intervals, corr_bid, 'bo-', label='Bid Price')
        plt.plot(intervals, corr_ask, 'ro-', label='Ask Price')
        plt.plot(intervals, corr_mid, 'go-', label='Mid Price')
        plt.xlabel('Time Interval (minutes)')
        plt.ylabel('Correlation with Predicted Price')
        plt.title('Correlation vs Time Interval')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        # Plot R-squared
        plt.subplot(2, 2, 2)
        plt.plot(intervals, r2_bid, 'bo-', label='Bid Price')
        plt.plot(intervals, r2_ask, 'ro-', label='Ask Price')
        plt.plot(intervals, r2_mid, 'go-', label='Mid Price')
        plt.xlabel('Time Interval (minutes)')
        plt.ylabel('R-squared')
        plt.title('R-squared vs Time Interval')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        # Plot p-values (log scale)
        plt.subplot(2, 2, 3)
        plt.semilogy(intervals, p_bid, 'bo-', label='Bid Price')
        plt.semilogy(intervals, p_ask, 'ro-', label='Ask Price')
        plt.semilogy(intervals, p_mid, 'go-', label='Mid Price')
        plt.axhline(y=0.05, color='k', linestyle='--', alpha=0.5, label='p=0.05')
        plt.axhline(y=0.01, color='k', linestyle='--', alpha=0.5, label='p=0.01')
        plt.xlabel('Time Interval (minutes)')
        plt.ylabel('P-value (log scale)')
        plt.title('Statistical Significance vs Time Interval')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        # Plot sample sizes
        plt.subplot(2, 2, 4)
        n_samples = [results[i]['n_samples'] for i in intervals]
        plt.plot(intervals, n_samples, 'ko-')
        plt.xlabel('Time Interval (minutes)')
        plt.ylabel('Number of Samples')
        plt.title('Sample Size vs Time Interval')
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_path / 'timeseries_analysis.png', dpi=300, bbox_inches='tight')
        plt.show()
        
    def generate_report(self, results):
        """Generate a comprehensive analysis report."""
        
        print("\n" + "="*80)
        print("TIMESERIES ANALYSIS REPORT")
        print("="*80)
        print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Records: {len(self.df):,}")
        print(f"Total Games: {self.df['game_id'].nunique():,}")
        print(f"Model Version: {self.df['prediction_model_version'].iloc[0]}")
        
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
            print(f"  Bid Price:  {result['p_values']['bid']:.2e}")
            print(f"  Ask Price:  {result['p_values']['ask']:.2e}")
            print(f"  Mid Price:  {result['p_values']['mid']:.2e}")
            
            print("\nR-squared (Explained Variance):")
            print(f"  Bid Price:  {result['r_squared']['bid']:.4f}")
            print(f"  Ask Price:  {result['r_squared']['ask']:.4f}")
            print(f"  Mid Price:  {result['r_squared']['mid']:.4f}")
            
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
        
        # Find best correlations
        best_bid_interval = max(results.keys(), key=lambda x: results[x]['correlations']['bid'])
        best_ask_interval = max(results.keys(), key=lambda x: results[x]['correlations']['ask'])
        best_mid_interval = max(results.keys(), key=lambda x: results[x]['correlations']['mid'])
        
        print(f"\nStrongest Correlations:")
        print(f"  Bid Price: {results[best_bid_interval]['correlations']['bid']:.4f} at {best_bid_interval} minutes")
        print(f"  Ask Price: {results[best_ask_interval]['correlations']['ask']:.4f} at {best_ask_interval} minutes")
        print(f"  Mid Price: {results[best_mid_interval]['correlations']['mid']:.4f} at {best_mid_interval} minutes")
        
        # Check if any relationships are strong
        max_corr = max([max(results[i]['correlations'].values()) for i in results.keys()])
        if max_corr > 0.5:
            print(f"\n✓ Strong predictive relationship found (max correlation: {max_corr:.4f})")
        elif max_corr > 0.3:
            print(f"\n⚠ Moderate predictive relationship found (max correlation: {max_corr:.4f})")
        else:
            print(f"\n✗ Weak predictive relationship (max correlation: {max_corr:.4f})")
        
        # Check significance across intervals
        significant_intervals = []
        for interval in results.keys():
            if any(p < 0.05 for p in results[interval]['p_values'].values()):
                significant_intervals.append(interval)
        
        if significant_intervals:
            print(f"\nStatistically significant relationships found at: {significant_intervals} minutes")
        else:
            print(f"\nNo statistically significant relationships found")

def main():
    """Run the complete timeseries analysis."""
    
    db_path = Path(__file__).parent / "signal_analysis.db"
    
    if not db_path.exists():
        print(f"Error: Signal database not found at {db_path}")
        print("Please run create_signal_db.py first")
        return 1
    
    print("Starting Timeseries Analysis...")
    
    # Initialize analyzer
    analyzer = TimeseriesAnalyzer(str(db_path))
    
    # Load and prepare data
    print("Loading data...")
    analyzer.load_data()
    
    # Create lagged features
    print("Creating lagged features...")
    time_intervals = [1, 2, 5, 10, 15, 30]  # minutes
    analyzer.create_lagged_features(time_intervals)
    
    # Analyze predictive power
    print("Analyzing predictive power...")
    results = analyzer.analyze_predictive_power(time_intervals)
    
    # Create visualizations
    print("Creating visualizations...")
    analyzer.create_visualizations(results)
    
    # Generate report
    analyzer.generate_report(results)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())