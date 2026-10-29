"""Issue tracker: tasks, bugs, complaints, risks, corrective items."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log
from app.modules.notifications import notify

from .schemas import CommentIn, IssueCreate, IssueUpdate

ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr")

router = APIRouter(tags=["issues"], dependencies=[Depends(get_current_user)])


@router.get("/issues")
async def list_issues(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    type: Optional[str] = None,
    project_id: Optional[str] = None,
    assignee_id: Optional[str] = None,
    overdue: bool = False,
    mine: bool = False,
    limit: int = Query(200, le=1000),
    user: dict = Depends(require_roles(*ALL)),
):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if priority:
        q["priority"] = priority
    if type:
        q["type"] = type
    if project_id:
        q["project_id"] = project_id
    if assignee_id:
        q["assignee_id"] = assignee_id
    if mine:
        q["$or"] = [{"assignee_id": user["id"]}, {"reporter_id": user["id"]}]
    if overdue:
        q["due_date"] = {"$lt": today().isoformat()}
        q["status"] = {"$in": ["open", "in_progress"]}
    rows = await get_db().issues.find(q).sort("created_at", -1).to_list(limit)
    return clean_many(rows)


@router.post("/issues", status_code=201)
async def create_issue(body: IssueCreate, request: Request, user: dict = Depends(require_roles(*ALL))):
    issue_number = await get_db().issues.count_documents({}) + 1
    doc = {
        "_id": new_id(),
        "number": f"#{issue_number:04d}",
        **body.model_dump(),
        "status": "open",
        "reporter_id": user["id"],
        "reporter_name": user["name"],
        "comments": [],
        "history": [{"action": "created", "by": user["name"], "at": utcnow_iso()}],
        "created_at": utcnow_iso(),
    }
    await get_db().issues.insert_one(doc)

    # Notify assignee if different from reporter
    if body.assignee_id and body.assignee_id != user["id"]:
        await notify([body.assignee_id], "Issue assigned to you",
                     f"{doc['number']}: {body.title}", "/issues")

    await log(user, "create", "issue", doc["_id"],
              f"Created issue {doc['number']}: {body.title} ({body.priority})", client_ip(request))
    return clean(doc)


@router.get("/issues/{issue_id}")
async def get_issue(issue_id: str, _: dict = Depends(require_roles(*ALL))):
    issue = await get_db().issues.find_one({"_id": issue_id})
    if not issue:
        raise HTTPException(404, "Issue not found")
    return clean(issue)


@router.patch("/issues/{issue_id}")
async def update_issue(issue_id: str, body: IssueUpdate, request: Request,
                        user: dict = Depends(require_roles(*ALL))):
    issue = await get_db().issues.find_one({"_id": issue_id})
    if not issue:
        raise HTTPException(404, "Issue not found")
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")

    new_status = patch.get("status")
    if new_status in ("resolved", "closed", "wont_fix") and not patch.get("resolution"):
        if not issue.get("resolution"):
            raise HTTPException(422, "Provide a resolution when closing/resolving an issue")

    history_entry = {"action": f"updated: {', '.join(patch.keys())}", "by": user["name"], "at": utcnow_iso()}
    patch["updated_at"] = utcnow_iso()

    await get_db().issues.update_one(
        {"_id": issue_id},
        {"$set": patch, "$push": {"history": history_entry}},
    )

    # Notify new assignee
    new_assignee = patch.get("assignee_id")
    if new_assignee and new_assignee != issue.get("assignee_id") and new_assignee != user["id"]:
        await notify([new_assignee], "Issue assigned to you",
                     f"{issue['number']}: {issue['title']}", "/issues")

    await log(user, "update", "issue", issue_id,
              f"Updated issue {issue['number']}: {', '.join(patch.keys())}", client_ip(request))
    return clean(await get_db().issues.find_one({"_id": issue_id}))


@router.delete("/issues/{issue_id}")
async def delete_issue(issue_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    issue = await get_db().issues.find_one({"_id": issue_id})
    if not issue:
        raise HTTPException(404, "Issue not found")
    await get_db().issues.delete_one({"_id": issue_id})
    await log(user, "delete", "issue", issue_id, f"Deleted issue {issue['number']}: {issue['title']}", client_ip(request))
    return {"ok": True}


@router.post("/issues/{issue_id}/comments", status_code=201)
async def add_comment(issue_id: str, body: CommentIn, request: Request,
                       user: dict = Depends(require_roles(*ALL))):
    issue = await get_db().issues.find_one({"_id": issue_id})
    if not issue:
        raise HTTPException(404, "Issue not found")
    comment = {
        "_id": new_id(), "text": body.text,
        "author_id": user["id"], "author_name": user["name"],
        "created_at": utcnow_iso(),
    }
    await get_db().issues.update_one(
        {"_id": issue_id},
        {"$push": {"comments": comment, "history": {"action": "commented", "by": user["name"], "at": utcnow_iso()}}},
    )
    # Notify reporter if a different person comments
    if issue.get("reporter_id") and issue["reporter_id"] != user["id"]:
        await notify([issue["reporter_id"]], f"New comment on {issue['number']}",
                     f"{user['name']}: {body.text[:80]}", f"/issues/{issue_id}")
    return comment


@router.get("/issues/summary/stats")
async def issues_stats(_: dict = Depends(require_roles(*ALL))):
    db = get_db()
    t = today().isoformat()
    total = await db.issues.count_documents({})
    open_c = await db.issues.count_documents({"status": {"$in": ["open", "in_progress"]}})
    overdue = await db.issues.count_documents(
        {"due_date": {"$lt": t}, "status": {"$in": ["open", "in_progress"]}}
    )
    by_priority = {}
    for p in ["critical", "high", "medium", "low"]:
        by_priority[p] = await db.issues.count_documents({"priority": p, "status": {"$in": ["open", "in_progress"]}})
    return {"total": total, "open": open_c, "overdue": overdue, "by_priority": by_priority}
