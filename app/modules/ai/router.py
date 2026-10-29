from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.common import new_id, utcnow_iso
from app.core.db import get_db
from app.core.deps import get_current_user, require_roles

from . import service

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(get_current_user)])


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatBody(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    history: list[Turn] = []
    session_id: Optional[str] = None  # Omit to start a new session


@router.post("/chat")
async def chat(body: ChatBody, user: dict = Depends(get_current_user)):
    db = get_db()
    session_id = body.session_id or new_id()

    # Load existing session history from MongoDB if session_id was provided
    stored_history: list[dict] = []
    if body.session_id:
        session = await db.chat_sessions.find_one({"_id": body.session_id, "user_id": user["id"]})
        if session:
            stored_history = session.get("history", [])

    # Merge stored + client-provided history (stored is authoritative)
    history = stored_history if stored_history else [t.model_dump() for t in body.history]

    result = await service.chat(body.question, history, user)

    # Persist updated history to MongoDB
    new_history = history + [
        {"role": "user", "content": body.question},
        {"role": "assistant", "content": result["answer"]},
    ]
    # Keep last 40 turns to avoid unbounded growth
    new_history = new_history[-40:]

    await db.chat_sessions.update_one(
        {"_id": session_id},
        {
            "$set": {
                "user_id": user["id"],
                "user_name": user.get("name"),
                "history": new_history,
                "updated_at": utcnow_iso(),
            },
            "$setOnInsert": {"created_at": utcnow_iso()},
        },
        upsert=True,
    )

    result["session_id"] = session_id
    return result


@router.get("/chat/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    """Lists the user's recent chat sessions."""
    db = get_db()
    sessions = (
        await db.chat_sessions.find(
            {"user_id": user["id"]},
            {"history": 0},  # Don't send full history in list
        )
        .sort("updated_at", -1)
        .to_list(20)
    )
    return [
        {
            "session_id": s["_id"],
            "updated_at": s.get("updated_at"),
            "created_at": s.get("created_at"),
            "turn_count": len(s.get("history", [])),
        }
        for s in sessions
    ]


@router.get("/chat/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    """Returns the full history of a chat session."""
    db = get_db()
    session = await db.chat_sessions.find_one({"_id": session_id, "user_id": user["id"]})
    if not session:
        raise HTTPException(404, "Session not found")
    return {"session_id": session["_id"], "history": session.get("history", []), "updated_at": session.get("updated_at")}


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    """Deletes a chat session."""
    db = get_db()
    await db.chat_sessions.delete_one({"_id": session_id, "user_id": user["id"]})
    return {"ok": True}


@router.get("/summary/daily")
async def daily(branch: Optional[str] = None, _: dict = Depends(require_roles("md", "admin"))):
    return await service.daily(branch or None)


@router.get("/summary/project/{project_id}")
async def project(project_id: str, user: dict = Depends(require_roles("md", "admin", "supervisor", "finance"))):
    out = await service.project_summary(project_id, user)
    if not out:
        raise HTTPException(404, "Project not found")
    return out
