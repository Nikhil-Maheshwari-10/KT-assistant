from fastapi import APIRouter

router = APIRouter()

@router.get("/", tags=["Root"])
async def root():
    """Simple friendly JSON message for the root endpoint."""
    return {
        "message": "Welcome to the KT-Assistant API! 🚀",
        "interactive_docs": "/docs",
        "system_health": "/health",
        "status": "online"
    }

@router.get("/health", tags=["Health"])
async def health():
    """Simple liveness probe."""
    return {"status": "ok", "service": "KT-Assistant API"}
