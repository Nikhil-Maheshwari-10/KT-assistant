"""
app/api/routers/ingest.py
Context ingestion endpoints — fully self-contained.

  GET  /api/sessions/{session_id}/ingest/branches   → ?url=<github_url>
  POST /api/sessions/{session_id}/ingest/github     → SSE stream
  POST /api/sessions/{session_id}/ingest/file       → multipart PDF/TXT

SSE event format (newline-delimited JSON):
  data: {"type": "progress",    "message": "..."}\\n\\n
  data: {"type": "topic_update","topic_id": "t1", "score": 72}\\n\\n
  data: {"type": "done",        "session": {...}, "status": "Success"}\\n\\n
  data: {"type": "error",       "message": "..."}\\n\\n
  data: {"type": "done",        "status": "Failed"}\\n\\n   ← on error/timeout
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, UploadFile, File, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.models.schemas import Session, Message, TopicKnowledge
from app.core.config import settings
from app.core.logger import logger
from app.core.messages import (
    INGEST_INVALID_URL, INGEST_NO_BRANCHES, INGEST_REPO_ERROR,
    INGEST_FILE_UNSUPPORTED, INGEST_FILE_EMPTY, INGEST_SERVICE_BUSY,
    CHAT_TIMEOUT,
)
from app.core.exceptions import BadRequestException, UnprocessableException, ServiceUnavailableException
from app.api.deps import get_session_or_404
from app.services.db_service import db_service
from app.services.ai_engine import ai_engine
from app.services.vector_service import vector_service
from app.services.github_service import fetch_branches, fetch_repo_content, parse_github_url, process_zip_file
from app.services.doc_processor import extract_text_from_file, chunk_text

router = APIRouter(prefix="/api/sessions/{session_id}/ingest", tags=["Ingest"])

# ---------------------------------------------------------------------------
# Concurrency Semaphore
# ---------------------------------------------------------------------------
# Caps concurrent ingest operations to prevent Gemini free-tier 429 cascades.
# Each ingest fires multiple LLM + embedding calls; 3 concurrent is safe on
# the free tier (100 embed req/min, ~1 RPM for large analysis calls).
from app.core.config import settings

_INGEST_SEMAPHORE = asyncio.Semaphore(settings.INGEST_MAX_CONCURRENCY)

# SSE headers — Connection: keep-alive prevents proxies from closing the stream prematurely
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class IngestGitHubRequest(BaseModel):
    github_url: str = Field(..., description="Full or shorthand GitHub repo URL")
    branch: str = Field(..., description="Branch to ingest")
    github_token: Optional[str] = Field(None, description="GitHub PAT for private repositories")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _process_knowledge(session: Session, text: str) -> None:
    """Runs AI analysis across all topics and persists results."""
    all_results = ai_engine.multi_topic_validate_and_score(session, text)
    for topic in session.topics:
        if topic.id not in all_results:
            continue
        data = all_results[topic.id]
        old_score = topic.confidence_score
        topic.knowledge = TopicKnowledge(**data.get("knowledge", {}))
        topic.confidence_score = data.get("confidence_score", 0)
        topic.missing_sections = data.get("missing_sections", [])
        if topic.confidence_score != old_score:
            logger.info(f"[INGEST] Topic '{topic.name}': {old_score}% → {topic.confidence_score}%")
        if topic.confidence_score >= settings.KT_CONFIDENCE_THRESHOLD and not topic.is_complete:
            topic.is_complete = True
            summary_text = json.dumps(topic.knowledge.model_dump(), indent=2)
            embedding = ai_engine.get_embedding(f"Topic: {topic.name}\nContent: {summary_text}")
            vector_service.upsert_topic_summary(session.id, topic.name, summary_text, embedding)
    session.overall_confidence = int(
        sum(t.confidence_score for t in session.topics) / len(session.topics)
    )
    db_service.save_session(session)


def _index_chunks(session_id: str, chunks: list) -> None:
    """Embeds and indexes content chunks into Qdrant for RAG Q&A."""
    if not chunks:
        return
    embeddings = ai_engine.get_embeddings_batch([c["content"] for c in chunks])
    vector_service.upsert_content_chunks(session_id, chunks, embeddings)
    logger.info(f"[INGEST] Indexed {len(chunks)} chunks for session {session_id}")


# ---------------------------------------------------------------------------
# GET /branches
# ---------------------------------------------------------------------------

@router.get("/branches")
async def list_branches(
    request: Request,
    session_id: str,
    url: str = Query(..., description="GitHub repo URL e.g. https://github.com/owner/repo"),
    session: Session = Depends(get_session_or_404),
):
    """Returns the branch list for a GitHub repository."""
    parsed = parse_github_url(url)
    if not parsed:
        raise BadRequestException(INGEST_INVALID_URL.format(url))
    owner, repo, _ = parsed
    token = request.query_params.get("token")
    branches = await asyncio.to_thread(fetch_branches, url, token=token)
    if not branches:
        from app.core.exceptions import NotFoundException
        from app.core.messages import INGEST_NO_BRANCHES
        if token:
            msg = f"No branches found for '{owner}/{repo}'. Check the URL or ensure your PAT token is correct and has access."
        else:
            msg = INGEST_NO_BRANCHES.format(f"{owner}/{repo}")
        raise NotFoundException(msg)
    return {"branches": branches, "owner": owner, "repo": repo}


# ---------------------------------------------------------------------------
# POST /github  (SSE)
# ---------------------------------------------------------------------------

@router.post("/github")
async def ingest_github(
    session_id: str,
    body: IngestGitHubRequest,
    session: Session = Depends(get_session_or_404),
):
    """
    Ingests a GitHub repository and streams SSE progress events.

    Concurrent ingest operations are capped by a semaphore — if the service
    is at capacity, the client receives an immediate error SSE so it doesn't hang.
    Times out after `settings.INGEST_TIMEOUT_SECONDS` seconds.
    """
    timeout = settings.INGEST_TIMEOUT_SECONDS

    async def _stream() -> AsyncGenerator[str, None]:
        # ── Fast-fail if semaphore is saturated ──────────────────────────────
        if _INGEST_SEMAPHORE._value <= 0:
            logger.warning(f"[INGEST] Semaphore saturated — rejecting request for session {session_id}")
            yield _sse({"type": "error", "message": INGEST_SERVICE_BUSY})
            yield _sse({"type": "done", "status": "Failed"})
            return

        async with _INGEST_SEMAPHORE:
            logger.info(f"[INGEST] Semaphore acquired — slots free: {_INGEST_SEMAPHORE._value}/3 for session {session_id}")
            try:
                parsed = parse_github_url(body.github_url)
                if not parsed:
                    yield _sse({"type": "error", "message": INGEST_INVALID_URL.format(body.github_url)})
                    yield _sse({"type": "done", "status": "Failed"})
                    return

                owner, repo, _ = parsed
                final_url = f"https://github.com/{owner}/{repo}/tree/{body.branch}"
                yield _sse({"type": "progress", "message": f"Fetching files from {owner}/{repo} ({body.branch})…"})

                ingest_result = await asyncio.to_thread(fetch_repo_content, final_url, token=body.github_token)
                if not ingest_result.success:
                    # Surface a more helpful message for private repos
                    err_msg = ingest_result.error
                    if "private" in (err_msg or "").lower() or "not found" in (err_msg or "").lower():
                        if body.github_token:
                            err_msg = (err_msg or "") + " | Check the URL or ensure your PAT token is correct and has access."
                        else:
                            err_msg = (err_msg or "") + " | If this is a private repository, enable the 'Private Repository' option and provide a PAT token."
                    yield _sse({"type": "error", "message": INGEST_REPO_ERROR.format(err_msg), "is_private": True})
                    yield _sse({"type": "done", "status": "Failed"})
                    return

                yield _sse({
                    "type": "progress",
                    "message": f"Fetched {len(ingest_result.files_fetched)} files ({ingest_result.total_chars / 1024:.1f} KB). Running AI analysis…",
                })

                await asyncio.to_thread(db_service.save_message, session_id, Message(
                    role="assistant",
                    content=(
                        f"🐙 **GitHub Repository Ingested:** `{ingest_result.owner}/{ingest_result.repo}` "
                        f"(branch: `{ingest_result.branch}`)\n\n"
                        f"I've successfully analyzed the codebase. Feel free to ask me anything about its architecture, flow, or code details!"
                    ),
                ))
                # Persist file manifest on the session — single source of truth.
                # Inject a special tag at the beginning so the UI knows the repo and branch name.
                session.file_manifest = [f"__REPO__:{ingest_result.repo} ({ingest_result.branch})"] + ingest_result.files_fetched

                all_results = await asyncio.to_thread(ai_engine.multi_topic_validate_and_score, session, ingest_result.aggregated_text)
                for topic in session.topics:
                    if topic.id not in all_results:
                        continue
                    data = all_results[topic.id]
                    topic.knowledge = TopicKnowledge(**data.get("knowledge", {}))
                    topic.confidence_score = data.get("confidence_score", 0)
                    topic.missing_sections = data.get("missing_sections", [])
                    yield _sse({
                        "type": "topic_update",
                        "topic_id": topic.id,
                        "topic_name": topic.name,
                        "score": topic.confidence_score,
                        "missing_sections": topic.missing_sections,
                    })
                    if topic.confidence_score >= settings.KT_CONFIDENCE_THRESHOLD and not topic.is_complete:
                        topic.is_complete = True
                        summary_text = json.dumps(topic.knowledge.model_dump(), indent=2)
                        embedding = await asyncio.to_thread(ai_engine.get_embedding, f"Topic: {topic.name}\nContent: {summary_text}")
                        await asyncio.to_thread(vector_service.upsert_topic_summary, session_id, topic.name, summary_text, embedding)
                        yield _sse({"type": "progress", "message": f"✅ '{topic.name}' indexed for Q&A."})

                session.overall_confidence = int(
                    sum(t.confidence_score for t in session.topics) / len(session.topics)
                )
                await asyncio.to_thread(db_service.save_session, session)

                if ingest_result.chunks:
                    yield _sse({"type": "progress", "message": f"Indexing {len(ingest_result.chunks)} content chunks…"})
                    await asyncio.to_thread(_index_chunks, session_id, ingest_result.chunks)

                logger.info(f"[INGEST] GitHub repo ingested: {ingest_result.summary}")
                yield _sse({
                    "type": "done",
                    "files_fetched": len(ingest_result.files_fetched),
                    "file_manifest": ingest_result.files_fetched,
                    "owner": ingest_result.owner,
                    "repo": ingest_result.repo,
                    "branch": ingest_result.branch,
                    "session": session.model_dump(mode="json"),
                    "status": "Success",
                })

            except Exception as exc:
                logger.error(f"[INGEST] GitHub SSE error for session {session_id}: {exc}", exc_info=True)
                yield _sse({"type": "error", "message": str(exc)})
                yield _sse({"type": "done", "status": "Failed"})

    async def _stream_with_timeout() -> AsyncGenerator[str, None]:
        """Per-chunk timeout wrapper — prevents indefinitely hung SSE streams."""
        gen = _stream()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                    yield chunk
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.error(f"[INGEST] Stream timed out after {timeout}s for session {session_id}")
                    yield _sse({"type": "error", "message": CHAT_TIMEOUT.format(timeout)})
                    yield _sse({"type": "done", "status": "Failed"})
                    break
        finally:
            await gen.aclose()

    return StreamingResponse(_stream_with_timeout(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ---------------------------------------------------------------------------
# POST /file
# ---------------------------------------------------------------------------

@router.post("/file")
async def ingest_file(
    session_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session_or_404),
):
    """Accepts a ZIP archive upload, runs AI analysis, and streams SSE progress."""
    if not file.filename.endswith(".zip"):
        raise BadRequestException(INGEST_FILE_UNSUPPORTED)

    # Read zip bytes synchronously into memory
    zip_bytes = await file.read()

    timeout = settings.INGEST_TIMEOUT_SECONDS

    async def _stream() -> AsyncGenerator[str, None]:
        if _INGEST_SEMAPHORE._value <= 0:
            logger.warning(f"[INGEST] Semaphore saturated — rejecting zip upload for session {session_id}")
            yield _sse({"type": "error", "message": INGEST_SERVICE_BUSY})
            yield _sse({"type": "done", "status": "Failed"})
            return

        async with _INGEST_SEMAPHORE:
            logger.info(f"[INGEST] Semaphore acquired for zip upload session {session_id}")
            try:
                yield _sse({"type": "progress", "message": f"Extracting {file.filename}…"})

                ingest_result = await asyncio.to_thread(process_zip_file, zip_bytes, file.filename)
                if not ingest_result.success:
                    yield _sse({"type": "error", "message": INGEST_REPO_ERROR.format(ingest_result.error)})
                    yield _sse({"type": "done", "status": "Failed"})
                    return

                yield _sse({
                    "type": "progress",
                    "message": f"Extracted {len(ingest_result.files_fetched)} files ({ingest_result.total_chars / 1024:.1f} KB). Running AI analysis…",
                })

                await asyncio.to_thread(db_service.save_message, session_id, Message(
                    role="assistant",
                    content=(
                        f"🐙 **ZIP Archive Ingested:** `{ingest_result.repo}`\n\n"
                        f"I've successfully analyzed the codebase. Feel free to ask me anything about its architecture, flow, or code details!"
                    ),
                ))

                session.file_manifest = [f"__REPO__:{ingest_result.repo} (zip)"] + ingest_result.files_fetched

                all_results = await asyncio.to_thread(ai_engine.multi_topic_validate_and_score, session, ingest_result.aggregated_text)
                for topic in session.topics:
                    if topic.id not in all_results:
                        continue
                    data = all_results[topic.id]
                    topic.knowledge = TopicKnowledge(**data.get("knowledge", {}))
                    topic.confidence_score = data.get("confidence_score", 0)
                    topic.missing_sections = data.get("missing_sections", [])
                    yield _sse({
                        "type": "topic_update",
                        "topic_id": topic.id,
                        "topic_name": topic.name,
                        "score": topic.confidence_score,
                        "missing_sections": topic.missing_sections,
                    })
                    if topic.confidence_score >= settings.KT_CONFIDENCE_THRESHOLD and not topic.is_complete:
                        topic.is_complete = True
                        summary_text = json.dumps(topic.knowledge.model_dump(), indent=2)
                        embedding = await asyncio.to_thread(ai_engine.get_embedding, f"Topic: {topic.name}\nContent: {summary_text}")
                        await asyncio.to_thread(vector_service.upsert_topic_summary, session_id, topic.name, summary_text, embedding)
                        yield _sse({"type": "progress", "message": f"✅ '{topic.name}' indexed for Q&A."})

                session.overall_confidence = int(
                    sum(t.confidence_score for t in session.topics) / len(session.topics)
                )
                await asyncio.to_thread(db_service.save_session, session)

                if ingest_result.chunks:
                    yield _sse({"type": "progress", "message": f"Indexing {len(ingest_result.chunks)} content chunks…"})
                    await asyncio.to_thread(_index_chunks, session_id, ingest_result.chunks)

                logger.info(f"[INGEST] ZIP archive ingested: {ingest_result.summary}")
                yield _sse({
                    "type": "done",
                    "files_fetched": len(ingest_result.files_fetched),
                    "file_manifest": ingest_result.files_fetched,
                    "owner": ingest_result.owner,
                    "repo": ingest_result.repo,
                    "branch": ingest_result.branch,
                    "session": session.model_dump(mode="json"),
                    "status": "Success",
                })

            except Exception as exc:
                logger.error(f"[INGEST] ZIP SSE error for session {session_id}: {exc}", exc_info=True)
                yield _sse({"type": "error", "message": str(exc)})
                yield _sse({"type": "done", "status": "Failed"})

    async def _stream_with_timeout() -> AsyncGenerator[str, None]:
        gen = _stream()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                    yield chunk
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.error(f"[INGEST] Stream timed out after {timeout}s for session {session_id}")
                    yield _sse({"type": "error", "message": CHAT_TIMEOUT.format(timeout)})
                    yield _sse({"type": "done", "status": "Failed"})
                    break
        finally:
            await gen.aclose()

    return StreamingResponse(_stream_with_timeout(), media_type="text/event-stream", headers=_SSE_HEADERS)
