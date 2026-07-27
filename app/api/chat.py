"""
app/api/routers/chat.py
Q&A chat endpoint — fully self-contained.

  POST /api/sessions/{session_id}/chat
       body: {"question": "..."}

SSE event format:
  data: {"type": "intent",  "intents": ["CONTENT"]}\\n\\n
  data: {"type": "token",   "content": "some text"}\\n\\n
  data: {"type": "done",    "full_answer": "...", "intents": [...], "status": "Success"}\\n\\n
  data: {"type": "error",   "message": "..."}\\n\\n
  data: {"type": "done",    "status": "Failed"}\\n\\n   ← on error
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.models.schemas import Session, Message
from app.core.config import settings
from app.core.logger import logger
from app.core.messages import CHAT_TIMEOUT
from app.api.deps import get_session_or_404
from app.services.db_service import db_service
from app.services.ai_engine import ai_engine
from app.services.vector_service import vector_service

router = APIRouter(prefix="/api/sessions/{session_id}/chat", tags=["Chat"])

# SSE headers — Connection: keep-alive prevents proxies from closing the stream prematurely
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Question about the codebase")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------

@router.post("")
async def chat(
    session_id: str,
    body: ChatRequest,
    session: Session = Depends(get_session_or_404),
):
    """
    Classifies question intent, retrieves context, and streams the LLM answer
    token-by-token via Server-Sent Events (SSE).

    The stream closes with a `done` event carrying `status: "Success"` on clean
    completion, or `status: "Failed"` if an error or timeout occurred.
    Times out after `settings.CHAT_TIMEOUT_SECONDS` seconds.
    """
    question = body.question.strip()
    timeout = settings.CHAT_TIMEOUT_SECONDS

    # Persist user message immediately so it appears in history regardless of outcome
    db_service.save_message(session_id, Message(role="user", content=question))

    # File manifest lives on the session object — no message scan needed
    file_manifest: list[str] = session.file_manifest

    async def _stream() -> AsyncGenerator[str, None]:
        full_parts: list[str] = []
        error_occurred = False

        try:
            intents = ai_engine.classify_intent(question)
            yield _sse({"type": "intent", "intents": intents})

            intents_result, token_gen = ai_engine.route_and_stream(
                question=question,
                session=session,
                session_id=session_id,
                file_manifest=file_manifest,
                vector_service=vector_service,
            )

            for token in token_gen:
                full_parts.append(token)
                yield _sse({"type": "token", "content": token})

            full_answer = "".join(full_parts)
            db_service.save_message(session_id, Message(role="assistant", content=full_answer))
            yield _sse({"type": "done", "full_answer": full_answer, "intents": intents_result, "status": "Success"})

        except Exception as exc:
            error_occurred = True
            logger.error(f"[CHAT] SSE error for session {session_id}: {exc}", exc_info=True)
            yield _sse({"type": "error", "message": str(exc)})
            yield _sse({"type": "done", "status": "Failed"})

    async def _stream_with_timeout() -> AsyncGenerator[str, None]:
        """
        Wraps _stream() with a per-chunk asyncio timeout.
        If any single yield takes longer than `timeout` seconds the stream
        is terminated with an error + done event so the client isn't left hanging.
        """
        gen = _stream()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                    yield chunk
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.error(f"[CHAT] Stream timed out after {timeout}s for session {session_id}")
                    yield _sse({"type": "error", "message": CHAT_TIMEOUT.format(timeout)})
                    yield _sse({"type": "done", "status": "Failed"})
                    break
        finally:
            await gen.aclose()

    return StreamingResponse(_stream_with_timeout(), media_type="text/event-stream", headers=_SSE_HEADERS)
