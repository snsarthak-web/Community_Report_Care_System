"""Local-time helpers.

The database always stores UTC. The site shows Indian Standard Time (UTC+5:30) by default, so the day on every graph, "today",
"yesterday" and every displayed date/time matches the clock on the user's phone. Change the zone with the TZ_OFFSET_MINUTES
(and TZ_LABEL) environment variables. Pure functions: no Flask / database imports, so they are easy to test.
"""
from datetime import datetime, timedelta, time


def to_local(dt, minutes):
    return dt + timedelta(minutes=minutes) if dt else dt


def local_today(utc_now, minutes):
    return to_local(utc_now, minutes).date()


def local_day_start_utc(day, minutes):
    """UTC moment at which the local calendar `day` begins (used to filter the database)."""
    return datetime.combine(day, time.min) - timedelta(minutes=minutes)


def bucket_by_local_day(utc_times, minutes):
    """{'2026-11-08': 3, ...}: how many of the UTC timestamps fall on each local day."""
    out = {}
    for t in utc_times:
        k = to_local(t, minutes).date().isoformat()
        out[k] = out.get(k, 0) + 1
    return out


def day_label(utc_dt, utc_now, minutes):
    d, today = to_local(utc_dt, minutes).date(), local_today(utc_now, minutes)
    if d == today:
        return 'Today'
    if d == today - timedelta(days=1):
        return 'Yesterday'
    return to_local(utc_dt, minutes).strftime('%a, %d %b %Y')


def ago(utc_dt, utc_now, minutes):
    secs = int((utc_now - utc_dt).total_seconds())
    if secs < 60:
        return 'Just now'
    if secs < 3600:
        return f'{secs // 60} min ago'
    if secs < 86400:
        return f'{secs // 3600} h ago'
    if secs < 7 * 86400:
        return f'{secs // 86400} d ago'
    return to_local(utc_dt, minutes).strftime('%d %b %Y')
