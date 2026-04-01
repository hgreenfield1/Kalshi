---
name: live-trading
description: Start and manage the live trading runner. Use when the user says "start live trading", "start the trader", "run in paper mode", or "enable live orders".
version: 1.0.0
---

# Live Trading

Start and manage the live trading runner (`Scripts/run_live.py`).

## Prerequisites

- Private key file must exist at `C:\Users\henry\Kalshi\henry.txt` (PEM format RSA key from Kalshi API settings)
- `.env` must have `PROD_KEYID` and `PROD_KEYFILE` set (already configured)
- Default mode is **paper** (no real orders). Set `AUTO_EXECUTE=true` only for live trading.

## Check if already running

```bash
tasklist | grep python  # or check live_trading.log for recent output
tail -5 C:/Users/henry/Kalshi/live_trading.log
```

If the scheduler is already running, do not start a second instance.

## Start in paper mode (default)

```bash
cd C:/Users/henry/Kalshi && nohup python Scripts/run_live.py > live_trading.log 2>&1 &
```

## Start in live mode (real orders)

```bash
cd C:/Users/henry/Kalshi && AUTO_EXECUTE=true nohup python Scripts/run_live.py > live_trading.log 2>&1 &
```

## After starting

Wait 3 seconds, then check logs:
```bash
tail -20 C:/Users/henry/Kalshi/live_trading.log
```

Report:
- Whether it started successfully or errored
- Current mode (PAPER or LIVE)
- Daily loss limit

## Common errors

- `FileNotFoundError: henry.txt` — private key missing, user needs to re-download from Kalshi API dashboard
- Auth errors — key ID or key file mismatch in `.env`

## After the trader is running

Use the `dashboard` skill to start the monitoring UI, or use `/debug-live` if something looks wrong.
