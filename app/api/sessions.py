"""
app/api/routers/sessions.py
Session lifecycle endpoints — fully self-contained.

  POST   /api/sessions                       → create new session
  GET    /api/sessions                       → list sessions (scoped to X-User-Id)
  GET    /api/sessions/{session_id}          → load existing session
  GET    /api/sessions/{session_id}/messages → chat history
  DELETE /api/sessions/{session_id}          → delete session + vectors
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.models.schemas import Session, Topic, Message
from app.core.logger import logger
from app.services.db_service import db_service
from app.services.vector_service import vector_service
from app.services.memory_service import memory_service
from app.api.deps import get_session_or_404

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


# ---------------------------------------------------------------------------
# Response models (local — only used here)
# ---------------------------------------------------------------------------

class CreateSessionResponse(BaseModel):
    session_id: str
    topics: List[Topic]
    message: str = "Session created successfully."


class MessagesResponse(BaseModel):
    session_id: str
    messages: List[Message]


class SuccessResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _default_topics() -> List[Topic]:
    return [
        Topic(id="t1", name="System Overview", missing_sections=["definition", "purpose"]),
        Topic(id="t2", name="Architecture & Data Flow", missing_sections=["inputs / outputs", "monitoring / deployment"]),
        Topic(id="t3", name="Operations & Reliability", missing_sections=["failure cases", "edge cases", "operational steps"]),
    ]


# ---------------------------------------------------------------------------
# POST /api/sessions
# ---------------------------------------------------------------------------

@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(x_user_id: Optional[str] = Header(default=None)):
    """Creates a new KT session with three default topics, scoped to the requesting user."""
    session_id = str(uuid.uuid4())
    topics = _default_topics()
    session = Session(id=session_id, topics=topics, user_id=x_user_id)
    db_service.save_session(session)
    logger.info(f"API: New session created — {session_id} (user: {x_user_id})")
    return CreateSessionResponse(session_id=session_id, topics=topics)


# ---------------------------------------------------------------------------
# GET /api/sessions
# ---------------------------------------------------------------------------

@router.get("")
async def list_sessions(x_user_id: Optional[str] = Header(default=None)):
    """Returns a lightweight list of sessions for the requesting user only."""
    sessions = db_service.get_all_sessions_details(user_id=x_user_id)
    return {"sessions": sessions}


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}
# ---------------------------------------------------------------------------

@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: str,
    session: Session = Depends(get_session_or_404),
):
    """Returns the full session state (topics, confidence scores, status)."""
    return session


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/messages
# ---------------------------------------------------------------------------

@router.get("/{session_id}/messages", response_model=MessagesResponse)
async def get_messages(
    session_id: str,
    session: Session = Depends(get_session_or_404),
):
    """Returns all chat messages for this session ordered by timestamp."""
    messages: List[Message] = db_service.get_messages(session_id)
    return MessagesResponse(session_id=session_id, messages=messages)


# ---------------------------------------------------------------------------
# DELETE /api/sessions/{session_id}
# ---------------------------------------------------------------------------

@router.delete("/{session_id}", response_model=SuccessResponse)
async def delete_session(
    session_id: str,
):
    """Deletes the session from Supabase, purges Qdrant vectors, and drops conversation memory."""
    db_service.delete_session_data(session_id)
    vector_service.delete_session_vectors(session_id)
    memory_service.delete_session_memory(session_id)
    logger.info(f"[API] Session {session_id} deleted.")
    return SuccessResponse(message=f"Session '{session_id}' and all associated data deleted.")
