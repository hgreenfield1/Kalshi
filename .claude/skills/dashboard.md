---
name: dashboard
description: Start and check the Kalshi MLB trading dashboard. Use when the user says "start the dashboard", "open the dashboard", "check dashboard status", or wants to monitor live trading.
version: 1.0.0
---

# Dashboard

Start and manage the Kalshi MLB trading dashboard.

## What to do

1. **Check if already running** — `curl -s http://localhost:8080/api/live/summary` — if it responds, report status and skip to step 4.

2. **Check if the frontend is built** — verify `dashboard/dist/index.html` exists. If not, build it first:
   ```
   cd C:/Users/henry/Kalshi/dashboard && npm run build
   ```

3. **Start the backend** in the background:
   ```
   cd C:/Users/henry/Kalshi && nohup python -m uvicorn Scripts.dashboard_api:app --host 0.0.0.0 --port 8080 > dashboard.log 2>&1 &
   ```
   Wait 2 seconds, then verify with `curl -s http://localhost:8080/api/live/summary`.

4. **Report**:
   - Confirm it's running and show the live summary JSON (total_pnl, active_count, pending_count, mode).
   - Remind the user to access it at `http://<tailscale-ip>:8080` from their phone. They can get the Tailscale IP by running `! tailscale ip`.
