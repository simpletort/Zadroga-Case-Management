from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import pytz

NYC_TZ = pytz.timezone("America/New_York")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def days_ago(n: int) -> datetime:
    return now_utc() - timedelta(days=n)


def to_firestore_timestamp(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
