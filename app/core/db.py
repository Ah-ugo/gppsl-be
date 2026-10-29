"""Async MongoDB access via Motor. `mongomock://` URLs give an in-memory database for tests."""
from typing import Any

from .config import get_settings

_client: Any = None
_db: Any = None


def get_db() -> Any:
    global _client, _db
    if _db is None:
        s = get_settings()
        if s.use_mock_db:
            from mongomock_motor import AsyncMongoMockClient
            _client = AsyncMongoMockClient()
        else:
            from motor.motor_asyncio import AsyncIOMotorClient
            _client = AsyncIOMotorClient(s.mongo_url, tz_aware=True)
        _db = _client[s.db_name]
    return _db


def reset_db() -> None:
    """Drop the cached client (used by tests to get a fresh in-memory database)."""
    global _client, _db
    _client, _db = None, None


async def init_indexes() -> None:
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.audit_log.create_index([("timestamp", -1)])
    await db.daily_reports.create_index("project_id")
    await db.attendance.create_index([("staff_id", 1), ("date", 1)])
    await db.invoices.create_index("client_id")
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.document_chunks.create_index("document_id")
