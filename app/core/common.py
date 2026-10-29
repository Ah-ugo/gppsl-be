"""Small helpers used by every module."""
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .config import get_settings


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def lagos_now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def today() -> date:
    """Today's date in Africa/Lagos."""
    return lagos_now().date()


def clean(doc: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Expose Mongo's _id as `id` and never leak secrets."""
    if doc is None:
        return None
    out = dict(doc)
    if "_id" in out:
        out["id"] = out.pop("_id")
    out.pop("password_hash", None)
    return out


def clean_many(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [clean(d) for d in docs]  # type: ignore[misc]
