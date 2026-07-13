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

    Handles:
    - Python datetime (naive or aware)
    - google.cloud.firestore DatetimeWithNanoseconds (subclass of datetime)
    - ISO-8601 strings
    - google.protobuf Timestamp objects (has .seconds attribute)
    Always returns a UTC-aware datetime or None.
    """
    if value is None:
        return None
    # datetime and DatetimeWithNanoseconds (Firestore subclass of datetime)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    # Protobuf Timestamp object
    if hasattr(value, "seconds"):
        return datetime.fromtimestamp(value.seconds, tz=timezone.utc)
    # ISO-8601 string
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
