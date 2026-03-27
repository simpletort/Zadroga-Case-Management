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
