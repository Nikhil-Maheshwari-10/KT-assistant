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
from app.services.memory_service import memory_service

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
    logger.info(f"[CHAT] Q: {question[:120]}")

    # Persist user message immediately so it appears in the chat UI
    db_service.save_message(session_id, Message(role="user", content=question))

    # File manifest lives on the session object — no message scan needed
    file_manifest: list[str] = session.file_manifest

    # Stage 1: immediately write a pending memory turn so follow-up questions
    # can see this one in history even while summarization runs in background.
    memory_service.store_pending_turn(session_id, question)

    # Stage 2: retrieve Qdrant-based conversation history (compact summaries)
    # instead of raw Supabase messages — far more token-efficient.
    recent_history = memory_service.retrieve_history(session_id)

    async def _stream() -> AsyncGenerator[str, None]:
        import queue
        import threading
        
        q = queue.Queue()

        def _worker():
            try:
                intents = ai_engine.classify_intent(question)
                q.put(("intent", intents))

                intents_result, token_gen = ai_engine.route_and_stream(
                    question=question,
                    session=session,
                    session_id=session_id,
                    file_manifest=file_manifest,
                    vector_service=vector_service,
                    intents=intents,
                    history=recent_history,
                )
                q.put(("intents_result", intents_result))

                for token in token_gen:
                    q.put(("token", token))

                q.put(("done", None))
            except Exception as exc:
                logger.error(f"[CHAT] Worker error: {exc}", exc_info=True)
                q.put(("error", str(exc)))

        thread = threading.Thread(target=_worker)
        thread.start()

        full_parts: list[str] = []
        intents_result = []
        loop = asyncio.get_event_loop()

        while True:
            # wait for items from the queue without blocking the event loop
            item = await loop.run_in_executor(None, q.get)
            msg_type, data = item

            if msg_type == "intent":
                yield _sse({"type": "intent", "intents": data})
            elif msg_type == "intents_result":
                intents_result = data
            elif msg_type == "token":
                full_parts.append(data)
                yield _sse({"type": "token", "content": data})
            elif msg_type == "done":
                full_answer = "".join(full_parts)
                db_service.save_message(session_id, Message(role="assistant", content=full_answer))
                logger.info(f"[CHAT] A: {full_answer[:120]}{'...' if len(full_answer) > 120 else ''}")
                yield _sse({"type": "done", "full_answer": full_answer, "intents": intents_result, "status": "Success"})
                # Stage 3: summarize the Q&A pair in a background thread so it
                # doesn't block the SSE stream. The summary is stored in Qdrant
                # and used as history context for future questions in this session.
                import threading
                threading.Thread(
                    target=memory_service.summarize_and_store,
                    args=(session_id, question, full_answer, ai_engine),
                    daemon=True,
                ).start()
                break
            elif msg_type == "error":
                yield _sse({"type": "error", "message": data})
                yield _sse({"type": "done", "status": "Failed"})
                break

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
