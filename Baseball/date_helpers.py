from datetime import datetime, timezone, timedelta
from typing import List


# Common date format constants
ISO_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
GAME_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
MINUTE_INTERVAL = timedelta(minutes=1)


def convert_utc_to_game_timestamp(timestamp_str: str) -> str:
    """
    Converts a UTC ISO timestamp to game timestamp format.
    
    Args:
        timestamp_str: Either ISO format ('2025-01-01T12:00:00Z') or 
                      game format ('20250101_120000')
    
    Returns:
        Timestamp in game format ('20250101_120000')
    """
    try:
        # Check if already in game format
        datetime.strptime(timestamp_str, GAME_TIMESTAMP_FORMAT)
        return timestamp_str
    except ValueError:
        # Convert from ISO UTC format
        dt_utc = datetime.strptime(timestamp_str, ISO_UTC_FORMAT).replace(tzinfo=timezone.utc)
        return dt_utc.strftime(GAME_TIMESTAMP_FORMAT)


def get_backtest_timestamps(start_time_str: str, end_time_str: str) -> List[str]:
    """
    Generate minute-by-minute timestamps between start and end times (inclusive).
    
    Args:
        start_time_str: Start time in game format ('20250101_120000')
        end_time_str: End time in game format ('20250101_120000')
    
    Returns:
        List of ISO UTC timestamps at 1-minute intervals
    """
    start_dt = datetime.strptime(start_time_str, GAME_TIMESTAMP_FORMAT)
    end_dt = datetime.strptime(end_time_str, GAME_TIMESTAMP_FORMAT)
    
    timestamps = []
    current = start_dt
    
    while current <= end_dt:
        timestamps.append(current.strftime(ISO_UTC_FORMAT))
        current += MINUTE_INTERVAL
    
    return timestamps


def unix_to_utc_timestamp(unix_timestamp: float) -> str:
    """
    Convert Unix timestamp to ISO UTC format.
    
    Args:
        unix_timestamp: Unix timestamp (seconds since epoch)
    
    Returns:
        ISO UTC timestamp string
    """
    dt_utc = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    return dt_utc.strftime(ISO_UTC_FORMAT)


def round_to_next_minute(timestamp_str: str) -> str:
    """
    Round timestamp up to the next minute boundary.
    
    Args:
        timestamp_str: ISO UTC timestamp string
    
    Returns:
        ISO UTC timestamp rounded to next minute
    """
    dt = datetime.strptime(timestamp_str, ISO_UTC_FORMAT)
    
    if dt.second == 0:
        return timestamp_str
    
    # Round up to next minute
    dt = dt.replace(second=0, microsecond=0) + MINUTE_INTERVAL
    return dt.strftime(ISO_UTC_FORMAT)


def add_minutes_to_timestamp(timestamp_str: str, minutes: int) -> str:
    """
    Add specified minutes to a timestamp.
    
    Args:
        timestamp_str: ISO UTC timestamp string
        minutes: Number of minutes to add (can be negative)
    
    Returns:
        New ISO UTC timestamp string
    """
    dt = datetime.strptime(timestamp_str, ISO_UTC_FORMAT).replace(tzinfo=timezone.utc)
    dt += timedelta(minutes=minutes)
    return dt.strftime(ISO_UTC_FORMAT)


def minutes_between_timestamps(ts1: str, ts2: str) -> int:
    """
    Calculate whole minutes between two timestamps.
    
    Args:
        ts1: First ISO UTC timestamp string
        ts2: Second ISO UTC timestamp string
    
    Returns:
        Number of whole minutes between timestamps (ts2 - ts1)
    """
    dt1 = datetime.strptime(ts1, ISO_UTC_FORMAT)
    dt2 = datetime.strptime(ts2, ISO_UTC_FORMAT)
    delta = dt2 - dt1
    return int(delta.total_seconds() // 60)