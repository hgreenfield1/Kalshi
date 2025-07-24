from datetime import datetime, timezone, timedelta


def convert_utc_to_game_timestamp(ts_str):
    """
    Converts a UTC ISO timestamp ('%Y-%m-%dT%H:%M:%SZ') to format as 'yyyymmdd_hhmmss'.
    If already in 'yyyymmdd_hhmmss' format, returns unchanged.
    """
    custom_fmt = "%Y%m%d_%H%M%S"
    iso_fmt = "%Y-%m-%dT%H:%M:%SZ"
    try:
        # Already in custom format
        datetime.strptime(ts_str, custom_fmt)
        return ts_str
    except ValueError:
        # Convert from UTC ISO to local time
        dt_utc = datetime.strptime(ts_str, iso_fmt).replace(tzinfo=timezone.utc)
        return dt_utc.strftime(custom_fmt)
    
def get_backtest_timestamps(start_time_str, end_time_str):
    """
    Returns a list of 60-second (1 minute) increments between start_time and end_time (inclusive),
    formatted as UTC ISO 8601 strings (e.g., '2025-06-13T19:15:54Z').
    Input timestamps are in the format 'yyyymmdd_hhmmss'.
    """
    fmt_in = "%Y%m%d_%H%M%S"
    fmt_out = "%Y-%m-%dT%H:%M:%SZ"
    start_dt = datetime.strptime(start_time_str, fmt_in)
    end_dt = datetime.strptime(end_time_str, fmt_in)
    increments = []
    current = start_dt
    while current < end_dt:
        increments.append(current.strftime(fmt_out))
        current += timedelta(seconds=60)
    increments.append(end_dt.strftime(fmt_out))
    return increments


def unix_to_utc_timestamp(unix_timestamp):
    """
    Converts a Unix timestamp to a UTC timestamp string in the format 'yyyymmdd_hhmmss'.
    """
    dt_utc = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def round_to_next_minute(ts):
    """
    Takes a timestamp string in the format 'yyyymmdd_hhmmss' and rounds it up to the next number of seconds divisible by 60.
    Returns the rounded timestamp string in the same format.
    """
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    dt = datetime.strptime(ts, fmt)
    if dt.second != 0:
        dt += timedelta(seconds=(60 - dt.second))
        dt = dt.replace(second=0)
    return dt.strftime(fmt)

def add_min_to_utc_timestamp(dt, minutes):
    dt = datetime.strptime(dt, '%Y-%m-%dT%H:%M:%SZ')
    dt = dt.replace(tzinfo=timezone.utc)

    dt = dt + timedelta(minutes=minutes)

    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def minutes_between_utc_timestamps(ts1, ts2):
    """
    Returns the number of whole minutes between two UTC timestamp strings in the format '%Y-%m-%dT%H:%M:%SZ'.
    """
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    dt1 = datetime.strptime(ts1, fmt)
    dt2 = datetime.strptime(ts2, fmt)
    delta = dt2 - dt1
    return int(delta.total_seconds() // 60)