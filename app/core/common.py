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


DEFAULT_BRANCHES = ["Port Harcourt HQ", "Warri", "Abuja"]


def resolve_branch(branch: Optional[str], known_branches: Optional[list[str]] = None) -> Optional[str]:
    """Normalize any branch string (case, alias, partial like 'Port Harcourt' vs 'Port Harcourt HQ').

    Returns canonical branch name, or None if empty / 'all'.
    """
    if not branch or not str(branch).strip():
        return None
    b_clean = str(branch).strip()
    if b_clean.lower() in ("all", "all branches", "all_branches", "none", "*", "undefined", "null"):
        return None
    branches = known_branches or DEFAULT_BRANCHES
    for kb in branches:
        if b_clean.lower() == kb.lower():
            return kb
    for kb in branches:
        if kb.lower().startswith(b_clean.lower()) or b_clean.lower().startswith(kb.lower()):
            return kb
    if b_clean.lower() in ("ph", "phc", "ph_hq", "portharcourt"):
        for kb in branches:
            if "port harcourt" in kb.lower():
                return kb
    return b_clean


def branch_query(branch: Optional[str], field_name: str = "branch") -> dict[str, Any]:
    """Return a robust MongoDB query dict for branch filtering, supporting case & prefix matching."""
    import re
    b = resolve_branch(branch)
    if not b:
        return {}
    return {field_name: re.compile(f"^{re.escape(b)}", re.I)}


def user_allowed_branches(user: Optional[dict[str, Any]]) -> Optional[list[str]]:
    """Return list of canonical branch names the user may access, or None if unrestricted ('all')."""
    if not user:
        return None
    roles = set(user.get("roles") or [])
    if user.get("role"):
        roles.add(user["role"])
    # Super roles have unrestricted access across branches
    if roles & {"md", "admin", "director"}:
        return None

    access = user.get("branch_access")
    if not access:
        b = user.get("branch")
        canonical_single = resolve_branch(b)
        return [canonical_single] if canonical_single else None

    # Check for 'all' in branch_access
    if any(str(a).strip().lower() in ("all", "all branches", "*") for a in access):
        return None

    canonical: list[str] = []
    for a in access:
        res = resolve_branch(a)
        if res and res not in canonical:
            canonical.append(res)
    return canonical if canonical else None


def scoped_branch_query(
    user: Optional[dict[str, Any]],
    requested_branch: Optional[str] = None,
    field_name: str = "branch",
) -> dict[str, Any]:
    """Combines user branch access permissions with requested branch filter into a safe MongoDB query."""
    import re

    allowed = user_allowed_branches(user)

    if allowed is None:
        # User has full access to all branches
        return branch_query(requested_branch, field_name=field_name)

    # User is restricted to specific branch(es)
    if requested_branch:
        req_norm = resolve_branch(requested_branch)
        if req_norm and any(req_norm.lower() == a.lower() for a in allowed):
            return branch_query(req_norm, field_name=field_name)
        else:
            # Requested a branch they do not have access to
            return {field_name: "__NO_BRANCH_ACCESS__"}

    # No specific branch requested: restrict to all allowed branches
    if len(allowed) == 1:
        return branch_query(allowed[0], field_name=field_name)
    regexes = [re.compile(f"^{re.escape(b)}", re.I) for b in allowed]
    return {field_name: {"$in": regexes}} if regexes else {field_name: "__NO_BRANCH_ACCESS__"}

