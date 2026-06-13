from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import pytz

NYC_TZ = pytz.timezone("America/New_York")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def months_ago(n: int) -> datetime:
    return now_utc() - relativedelta(months=n)


def days_ago(n: int) -> datetime:
    return now_utc() - timedelta(days=n)


def to_firestore_timestamp(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value) -> datetime | None:
    """
    Normalise a Firestore timestamp field to a timezone-aware datetime.

    Firestore returns datetime objects when using the Python SDK with a named
    database, but some documents written by other tools store the value as an
    ISO-8601 string.  This helper handles both cases and always returns a
    UTC-aware datetime (or None if the value is absent/unparseable).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
