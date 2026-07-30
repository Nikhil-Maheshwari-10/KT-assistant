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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logger import logger
from app.api import sessions, ingest, chat, documents, health
from app.core.exceptions import AppException, app_exception_handler
from app.core.scheduler import start_scheduler, stop_scheduler
from app.services.vector_service import vector_service


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run maintenance tasks on startup, clean up on shutdown."""
    logger.info("KT-Assistant API starting up…")
    try:
        # Ensure memory collection exists in Qdrant
        vector_service.ensure_memory_collection()
        
        # Start background task scheduler (fires cleanup immediately + every 6h)
        start_scheduler()
    except Exception as e:
        logger.warning(f"Startup tasks failed (non-fatal): {e}")
    yield
    stop_scheduler()
    logger.info("KT-Assistant API shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app setup
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

# Register exception handlers
app.add_exception_handler(AppException, app_exception_handler)

# Include routers
app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(ingest.router)
app.include_router(chat.router)
app.include_router(documents.router)


# ---------------------------------------------------------------------------
# Entry point
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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="warning", access_log=False)

