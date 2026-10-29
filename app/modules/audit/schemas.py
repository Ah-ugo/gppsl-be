from typing import Any, Optional

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: str
    user: dict[str, Any]
    action: str
    entity: str
    entity_id: Optional[str] = None
    timestamp: str
    ip: Optional[str] = None
    summary: str
