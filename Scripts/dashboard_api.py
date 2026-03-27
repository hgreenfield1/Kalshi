#!/usr/bin/env python3
"""
Dashboard API — FastAPI backend for the Kalshi MLB trading dashboard.
Serves live state files, backtest data, and an SSE stream.

Run with:
    uvicorn dashboard_api:app --host 0.0.0.0 --port 8080 --reload
"""

import asyncio
import json
import math
import os
import sqlite3
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
LIVE_STATE_DIR = ROOT / "live_state"
DB_PATH = ROOT / "backtest_predictions.db"
DIST_DIR = ROOT / "dashboard" / "dist"

app = FastAPI(title="Kalshi Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_str() -> str:
    # Use local time so the date matches the scheduler file (which uses local date)
    return datetime.now().strftime("%Y%m%d")


def _scheduler_path(date_str: str) -> Path:
    return LIVE_STATE_DIR / f"scheduler_{date_str}.json"


def _game_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_")
    return LIVE_STATE_DIR / f"game_{safe}.json"


def _read_json(path: Path) -> Optional[Dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _calc_pnl(portfolio: Dict) -> float:
    """P&L = current cash - 100 (starting cash), adjusted for open positions."""
    cash = portfolio.get("cash", 100.0)
    return round(cash - 100.0, 2)


def _get_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Backtest database not found")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _build_where(
    strategy: Optional[str],
    model: Optional[str],
    start: Optional[str],
    end: Optional[str],
) -> tuple[str, list]:
    clauses, params = [], []
    if strategy:
        clauses.append("strategy_version = ?")
        params.append(strategy)
    if model:
        clauses.append("prediction_model_version = ?")
        params.append(model)
    if start:
        clauses.append("timestamp >= ?")
        params.append(start)
    if end:
        clauses.append("timestamp <= ?")
        params.append(end)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# ---------------------------------------------------------------------------
# Live — Schedule
# ---------------------------------------------------------------------------

@app.get("/api/live/schedule")
def get_schedule(date_str: Optional[str] = Query(None, alias="date")):
    """Today's games from scheduler_{YYYYMMDD}.json"""
    ds = date_str or _today_str()
    path = _scheduler_path(ds)
    data = _read_json(path)
    if data is None:
        return {"date": ds, "games": [], "auto_execute": False, "daily_pnl": 0}

    entries = data.get("entries", [])
    games = []
    for e in entries:
        ticker = e.get("market_ticker", "")
        game_data = None
        if ticker:
            game_data = _read_json(_game_path(ticker))

        pnl = 0.0
        position = 0
        trade_count = 0
        if game_data:
            portfolio = game_data.get("portfolio", {})
            pnl = _calc_pnl(portfolio)
            position = portfolio.get("positions", 0)
            trade_count = len(portfolio.get("trade_history", []))

        games.append({
            "game_id": e.get("game_id"),
            "market_ticker": ticker,
            "home_team": e.get("home_team"),
            "away_team": e.get("away_team"),
            "scheduled_start": e.get("scheduled_start"),
            "status": e.get("status", "pending"),
            "pnl": pnl,
            "position": position,
            "trade_count": trade_count,
            "pregame_win_probability": game_data.get("pregame_win_probability") if game_data else None,
        })

    return {
        "date": ds,
        "auto_execute": data.get("auto_execute", False),
        "daily_pnl": data.get("daily_pnl", 0),
        "daily_loss_limit": data.get("daily_loss_limit", 50.0),
        "games": games,
    }


# ---------------------------------------------------------------------------
# Live — Summary
# ---------------------------------------------------------------------------

@app.get("/api/live/summary")
def get_summary():
    """Aggregate all game files for today."""
    ds = _today_str()
    sched = _read_json(_scheduler_path(ds))
    if not sched:
        return {
            "total_pnl": 0,
            "active_count": 0,
            "pending_count": 0,
            "done_count": 0,
            "total_trades": 0,
            "mode": "paper",
            "daily_loss_limit": 50.0,
        }

    total_pnl = 0.0
    active_count = 0
    pending_count = 0
    done_count = 0
    total_trades = 0

    for e in sched.get("entries", []):
        status = e.get("status", "pending")
        if status == "running":
            active_count += 1
        elif status in ("pending", "armed"):
            pending_count += 1
        elif status in ("done", "no_market", "skipped"):
            done_count += 1

        ticker = e.get("market_ticker", "")
        if ticker:
            gd = _read_json(_game_path(ticker))
            if gd:
                total_pnl += _calc_pnl(gd.get("portfolio", {}))
                total_trades += len(gd.get("portfolio", {}).get("trade_history", []))

    return {
        "total_pnl": round(total_pnl, 2),
        "active_count": active_count,
        "pending_count": pending_count,
        "done_count": done_count,
        "total_trades": total_trades,
        "mode": "live" if sched.get("auto_execute") else "paper",
        "daily_loss_limit": sched.get("daily_loss_limit", 50.0),
    }


# ---------------------------------------------------------------------------
# Live — Single Game
# ---------------------------------------------------------------------------

@app.get("/api/live/games/{ticker:path}")
def get_game(ticker: str):
    """Single game state file."""
    path = _game_path(ticker)
    data = _read_json(path)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Game state not found: {ticker}")
    return data


# ---------------------------------------------------------------------------
# Live — Historical
# ---------------------------------------------------------------------------

@app.get("/api/live/historical")
def get_historical():
    """List all scheduler files except today."""
    today = _today_str()
    results = []
    for p in sorted(LIVE_STATE_DIR.glob("scheduler_*.json"), reverse=True):
        ds = p.stem.replace("scheduler_", "")
        if ds == today:
            continue
        data = _read_json(p)
        if not data:
            continue
        games_count = len(data.get("entries", []))
        results.append({
            "date": ds,
            "games_count": games_count,
            "total_pnl": data.get("daily_pnl", 0),
            "auto_execute": data.get("auto_execute", False),
        })
    return {"dates": results}


@app.get("/api/live/historical/{date_str}")
def get_historical_date(date_str: str):
    """Schedule + per-game state for a past date."""
    return get_schedule(date_str)


# ---------------------------------------------------------------------------
# Live — SSE Stream
# ---------------------------------------------------------------------------

@app.get("/api/live/stream")
async def sse_stream():
    """Server-Sent Events: emit game updates when files change."""

    async def event_generator():
        last_mtimes: Dict[str, float] = {}

        # Send initial heartbeat
        yield "data: {\"type\": \"connected\"}\n\n"

        while True:
            await asyncio.sleep(5)
            try:
                ds = _today_str()
                sched_path = _scheduler_path(ds)
                changed_events = []

                # Check scheduler file
                if sched_path.exists():
                    mtime = sched_path.stat().st_mtime
                    key = str(sched_path)
                    if last_mtimes.get(key) != mtime:
                        last_mtimes[key] = mtime
                        sched_data = _read_json(sched_path)
                        if sched_data:
                            changed_events.append(json.dumps({
                                "type": "schedule_update",
                                "data": sched_data,
                            }))

                # Check each game file
                for gf in LIVE_STATE_DIR.glob("game_*.json"):
                    mtime = gf.stat().st_mtime
                    key = str(gf)
                    if last_mtimes.get(key) != mtime:
                        last_mtimes[key] = mtime
                        gd = _read_json(gf)
                        if gd:
                            changed_events.append(json.dumps({
                                "type": "game_update",
                                "ticker": gd.get("ticker"),
                                "portfolio": gd.get("portfolio"),
                                "strategy_state": gd.get("strategy_state"),
                                "tick_history": gd.get("strategy_state", {}).get("tick_history", []),
                                "saved_at": gd.get("saved_at"),
                            }))

                for evt in changed_events:
                    yield f"data: {evt}\n\n"

                # Heartbeat every cycle to keep connection alive
                yield "data: {\"type\": \"heartbeat\"}\n\n"

            except Exception as e:
                yield f"data: {{\"type\": \"error\", \"message\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Backtest — Filters
# ---------------------------------------------------------------------------

@app.get("/api/backtest/filters")
def backtest_filters():
    with _get_db() as conn:
        strategies = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT strategy_version FROM predictions ORDER BY strategy_version"
            ).fetchall()
        ]
        models = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT prediction_model_version FROM predictions ORDER BY prediction_model_version"
            ).fetchall()
        ]
    return {"strategies": strategies, "models": models}


# ---------------------------------------------------------------------------
# Backtest — Metrics
# ---------------------------------------------------------------------------

@app.get("/api/backtest/metrics")
def backtest_metrics(
    strategy: Optional[str] = None,
    model: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    where, params = _build_where(strategy, model, start, end)
    final_where = (where + " AND " if where else "WHERE ") + 'timestamp = "FINAL"'

    with _get_db() as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) as total_games,
                SUM(cash - 100.0) as total_pnl,
                AVG(cash - 100.0) as avg_pnl,
                AVG(CASE WHEN cash > 100.0 THEN 1.0 ELSE 0.0 END) as win_rate,
                AVG((cash - 100.0) / 100.0 * 100) as avg_roi
            FROM predictions
            {final_where}
            """,
            params,
        ).fetchone()

        # total trades = signals != 0
        sig_filter = "signal IS NOT NULL AND signal != 0 AND signal != '0'"
        trades_where = (where + " AND " + sig_filter) if where else ("WHERE " + sig_filter)
        trow = conn.execute(
            f"SELECT COUNT(*) as total_trades FROM predictions {trades_where}",
            params,
        ).fetchone()

    if not row:
        return {}

    total_pnl = row["total_pnl"] or 0.0
    avg_pnl = row["avg_pnl"] or 0.0
    win_rate = row["win_rate"] or 0.0
    avg_roi = row["avg_roi"] or 0.0
    total_games = row["total_games"] or 0

    # Sharpe: get all per-game PnLs
    with _get_db() as conn:
        pnls = [
            r[0] - 100.0
            for r in conn.execute(
                f"SELECT cash FROM predictions {final_where}", params
            ).fetchall()
            if r[0] is not None
        ]

    std_dev = 0.0
    sharpe = 0.0
    if len(pnls) > 1:
        mean = sum(pnls) / len(pnls)
        std_dev = math.sqrt(sum((p - mean) ** 2 for p in pnls) / len(pnls))
        sharpe = mean / std_dev if std_dev > 0 else 0.0

    return {
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 4),
        "win_rate": round(win_rate, 4),
        "avg_roi": round(avg_roi, 4),
        "sharpe": round(sharpe, 4),
        "std_dev": round(std_dev, 4),
        "total_games": total_games,
        "total_trades": trow["total_trades"] if trow else 0,
    }


# ---------------------------------------------------------------------------
# Backtest — Games table
# ---------------------------------------------------------------------------

@app.get("/api/backtest/games")
def backtest_games(
    strategy: Optional[str] = None,
    model: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 500,
):
    where, params = _build_where(strategy, model, start, end)
    final_where = (where + " AND " if where else "WHERE ") + 'timestamp = "FINAL"'

    with _get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                f.game_id,
                f.cash as final_cash,
                (f.cash - 100.0) as pnl,
                f.actual_outcome,
                f.strategy_version,
                f.prediction_model_version as model_version,
                g.start_time,
                g.trade_count
            FROM predictions f
            JOIN (
                SELECT
                    game_id,
                    MIN(timestamp) as start_time,
                    COUNT(CASE WHEN signal IS NOT NULL AND signal != 0 AND signal != '0' THEN 1 END) as trade_count
                FROM predictions
                WHERE timestamp != 'FINAL'
                GROUP BY game_id
            ) g ON f.game_id = g.game_id
            {final_where}
            ORDER BY g.start_time DESC
            LIMIT {limit}
            """,
            params,
        ).fetchall()

    return {"games": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Backtest — Cumulative PnL
# ---------------------------------------------------------------------------

@app.get("/api/backtest/cumulative_pnl")
def backtest_cumulative_pnl(
    strategy: Optional[str] = None,
    model: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    where, params = _build_where(strategy, model, start, end)
    final_where = (where + " AND " if where else "WHERE ") + 'timestamp = "FINAL"'

    with _get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                f.game_id,
                g.start_time as date,
                (f.cash - 100.0) as pnl
            FROM predictions f
            JOIN (
                SELECT game_id, MIN(timestamp) as start_time
                FROM predictions
                WHERE timestamp != 'FINAL'
                GROUP BY game_id
            ) g ON f.game_id = g.game_id
            {final_where}
            ORDER BY g.start_time ASC
            """,
            params,
        ).fetchall()

    cumulative = 0.0
    result = []
    for r in rows:
        cumulative += r["pnl"] or 0.0
        result.append({
            "game_id": r["game_id"],
            "date": r["date"],
            "pnl": round(r["pnl"] or 0.0, 4),
            "cumulative_pnl": round(cumulative, 4),
        })

    return {"series": result}


# ---------------------------------------------------------------------------
# Backtest — PnL Distribution
# ---------------------------------------------------------------------------

@app.get("/api/backtest/distribution")
def backtest_distribution(
    strategy: Optional[str] = None,
    model: Optional[str] = None,
):
    where, params = _build_where(strategy, model, None, None)
    final_where = (where + " AND " if where else "WHERE ") + 'timestamp = "FINAL"'

    with _get_db() as conn:
        rows = conn.execute(
            f"SELECT cash FROM predictions {final_where}", params
        ).fetchall()

    pnls = [round((r[0] - 100.0), 4) for r in rows if r[0] is not None]
    return {"pnls": pnls}


# ---------------------------------------------------------------------------
# Backtest — Single Game Detail
# ---------------------------------------------------------------------------

@app.get("/api/backtest/game/{game_id}")
def backtest_game_detail(game_id: str):
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM predictions
            WHERE game_id = ? AND timestamp != 'FINAL'
            ORDER BY timestamp ASC
            """,
            [game_id],
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Game not found: {game_id}")

    return {"ticks": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Static files (must be last — catches everything not matched above)
# ---------------------------------------------------------------------------

if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")
else:
    @app.get("/")
    def root():
        return {
            "message": "Dashboard API is running. Frontend not built yet.",
            "hint": "cd dashboard && npm run build",
        }
