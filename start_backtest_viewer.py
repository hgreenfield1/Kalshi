#!/usr/bin/env python3
"""
Launch script for the backtest viewer application.
Starts the API server and optionally opens the web interface.
"""

import subprocess
import webbrowser
import time
import os
import sys
from pathlib import Path

def main():
    # Check if database exists
    db_path = Path("backtest_predictions.db")
    if not db_path.exists():
        print(f"Error: Database file '{db_path}' not found!")
        print("Make sure you have run backtests and created the database.")
        return 1
    
    # Start the API server
    print("Starting backtest API server...")
    
    try:
        # Start server in background
        server_process = subprocess.Popen([
            sys.executable, "backtest_api.py"
        ], cwd=os.getcwd())
        
        # Wait a moment for server to start
        time.sleep(2)
        
        # Open web browser
        viewer_path = Path("backtest_viewer.html").resolve()
        print(f"Opening web interface: file://{viewer_path}")
        webbrowser.open(f"file://{viewer_path}")
        
        print("\n" + "="*60)
        print("BACKTEST VIEWER STARTED")
        print("="*60)
        print(f"API Server: http://localhost:8000")
        print(f"Web Interface: file://{viewer_path}")
        print("\nPress Ctrl+C to stop the server")
        print("="*60)
        
        # Wait for user to stop
        server_process.wait()
        
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server_process.terminate()
        server_process.wait()
        print("Server stopped.")
        
    except Exception as e:
        print(f"Error starting server: {e}")
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())