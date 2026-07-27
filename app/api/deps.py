"""
app/api/deps.py
Shared FastAPI dependency functions used across all routers.

Usage in a router:
    from app.api.deps import get_session_or_404
    from fastapi import Depends

    @router.get("/{session_id}")
    async def my_endpoint(session: Session = Depends(get_session_or_404)):
        ...
"""
from fastapi import Path
from app.models.schemas import Session
from app.services.db_service import db_service
from app.core.exceptions import NotFoundException
from app.core.messages import SESSION_NOT_FOUND


async def get_session_or_404(session_id: str = Path(..., description="UUID of the KT session")) -> Session:
    """
    FastAPI dependency — loads a session from Supabase or raises 404.
    Replaces the duplicated `_get_or_404` helper that existed in every router.
    """
    session = db_service.get_session(session_id)
    if session is None:
        raise NotFoundException(SESSION_NOT_FOUND.format(session_id))
    return session
