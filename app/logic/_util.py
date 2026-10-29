"""Tiny helpers shared by the pure logic modules. Standard library only."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional, Union

DateLike = Union[date, datetime, str, None]


def to_date(value: DateLike) -> Optional[date]:
    """Accept date, datetime or ISO string (YYYY-MM-DD or full ISO) and return a date."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def to_datetime(value: Any) -> Optional[datetime]:
    """Accept datetime or ISO string and return a naive-or-aware datetime unchanged."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))


def naive_utc(value: datetime) -> datetime:
    """Return a naive datetime in UTC so aware and naive values can be subtracted."""
    if value.tzinfo is None:
        return value
    from datetime import timezone
    return value.astimezone(timezone.utc).replace(tzinfo=None)
