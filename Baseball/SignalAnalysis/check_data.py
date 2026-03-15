import sqlite3

conn = sqlite3.connect("signal_analysis.db")
cursor = conn.execute("SELECT timestamp, predicted_price, bid_price, ask_price FROM signal_data LIMIT 10")
rows = cursor.fetchall()

print("Sample data:")
for i, row in enumerate(rows):
    print(f"Row {i+1}: timestamp='{row[0]}', predicted_price={row[1]}, bid_price={row[2]}, ask_price={row[3]}")

conn.close()