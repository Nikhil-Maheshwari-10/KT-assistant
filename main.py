"""
main.py — KT-Assistant single entry point & FastAPI app

  python main.py                     → start backend on http://localhost:8000
  streamlit run ui/streamlit.py      → start legacy Streamlit UI
  uvicorn main:app --reload          → dev mode with hot-reload
"""
import os
import sys
from contextlib import asynccontextmanager

# Project root on sys.path so all `app.*` imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.logger import logger
from app.services.db_service import db_service
from app.services.vector_service import vector_service
from app.api import sessions, ingest, chat, documents
from app.core.exceptions import AppException


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run maintenance tasks on startup, clean up on shutdown."""
    logger.info("KT-Assistant API starting up…")
    try:
        expired_ids = db_service.cleanup_expired_sessions(hours=6)
        active_ids = db_service.get_all_active_session_ids()
        zombie_count = vector_service.purge_zombie_vectors(active_ids)
        
        # Ensure memory collection exists
        vector_service.ensure_memory_collection()
        
        logger.info(
            f"Startup cleanup: {len(expired_ids)} expired sessions removed, "
            f"{zombie_count} zombie vectors purged."
        )
    except Exception as e:
        logger.warning(f"Startup cleanup failed (non-fatal): {e}")
    yield
    logger.info("KT-Assistant API shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KT-Assistant API",
    description=(
        "REST + SSE API for the KT-Assistant: AI-powered knowledge transfer engine. "
        "Ingest GitHub repos or documents, chat via streaming Q&A, "
        "and export professional KT documents as PDF or DOCX."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(ingest.router)
app.include_router(chat.router)
app.include_router(documents.router)


@app.get("/health", tags=["Health"])
async def health():
    """Simple liveness probe."""
    return {"status": "ok", "service": "KT-Assistant API"}


# ---------------------------------------------------------------------------
# Global exception handler — uniform error JSON shape
# ---------------------------------------------------------------------------

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Catches all AppException subclasses (NotFoundException, BadRequestException, etc.)
    and returns a consistent {"error": "..."} JSON body.
    Unexpected 5xx errors are logged at ERROR level; client 4xx errors at WARNING.
    """
    if exc.status_code >= 500:
        logger.error(f"[API] {exc.status_code} on {request.method} {request.url.path}: {exc.detail}")
    else:
        logger.warning(f"[API] {exc.status_code} on {request.method} {request.url.path}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


# ---------------------------------------------------------------------------
# Entry point — `python main.py`
# ---------------------------------------------------------------------------

def _is_running_via_streamlit() -> bool:
    """True when Streamlit Cloud re-executes this file."""
    if "streamlit" not in sys.modules and not any("streamlit" in arg for arg in sys.argv):
        return False
    try:
        import importlib
        mod = importlib.import_module("streamlit.runtime.scriptrunner")
        get_ctx = getattr(mod, "get_script_run_ctx", None)
        return get_ctx is not None and get_ctx() is not None
    except Exception:
        return False


if _is_running_via_streamlit():
    # Streamlit Cloud — delegate to the Streamlit UI module
    import runpy
    _ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "streamlit.py")
    runpy.run_path(_ui_path, run_name="__main__")

elif __name__ == "__main__":
    import uvicorn
    print("🚀 KT-Assistant API  →  http://localhost:8000")
    print("   Docs              →  http://localhost:8000/docs")
    print("   Press Ctrl+C to stop.\n")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
