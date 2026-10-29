from typing import Literal, Optional
from pydantic import BaseModel, Field

IssueType = Literal["bug", "task", "improvement", "risk", "complaint", "other"]
IssuePriority = Literal["low", "medium", "high", "critical"]
IssueStatus = Literal["open", "in_progress", "resolved", "closed", "wont_fix"]


class IssueCreate(BaseModel):
    title: str
    type: IssueType = "task"
    priority: IssuePriority = "medium"
    description: Optional[str] = None
    project_id: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    due_date: Optional[str] = None
    tags: list[str] = []


class IssueUpdate(BaseModel):
    title: Optional[str] = None
    priority: Optional[IssuePriority] = None
    status: Optional[IssueStatus] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    due_date: Optional[str] = None
    resolution: Optional[str] = None
    tags: Optional[list[str]] = None


class CommentIn(BaseModel):
    issue_id: str
    text: str
