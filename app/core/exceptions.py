"""
app/core/exceptions.py
Structured application exception hierarchy.

All exceptions inherit from AppException (which extends HTTPException) so
FastAPI's default handler and our custom global handler both work seamlessly.
The global handler in main.py logs all AppExceptions uniformly and returns
a consistent JSON error shape: {"error": "<message>"}.
"""
from fastapi import HTTPException
from typing import Optional
from app.core.messages import FRIENDLY_HTTP_MESSAGES


class AppException(HTTPException):
    """Base application exception — maps to a specific HTTP status code."""
    def __init__(self, message: Optional[str] = None, status_code: int = 500):
        if not message:
            message = FRIENDLY_HTTP_MESSAGES.get(status_code, "An unexpected error occurred.")
        super().__init__(status_code=status_code, detail=message)


class NotFoundException(AppException):
    """404 — Resource does not exist."""
    def __init__(self, message: Optional[str] = None):
        super().__init__(message=message, status_code=404)


class BadRequestException(AppException):
    """400 — Caller sent invalid input."""
    def __init__(self, message: Optional[str] = None):
        super().__init__(message=message, status_code=400)


class UnprocessableException(AppException):
    """422 — Input is syntactically valid but semantically unparseable."""
    def __init__(self, message: Optional[str] = None):
        super().__init__(message=message, status_code=422)


class RateLimitException(AppException):
    """429 — Too many requests (e.g. LLM quota exhausted)."""
    def __init__(self, message: Optional[str] = None):
        super().__init__(message=message, status_code=429)


class ServiceUnavailableException(AppException):
    """503 — Downstream service (Gemini, Qdrant, etc.) is unavailable."""
    def __init__(self, message: Optional[str] = None):
        super().__init__(message=message, status_code=503)


class GatewayTimeoutException(AppException):
    """504 — Downstream service took too long to respond."""
    def __init__(self, message: Optional[str] = None):
        super().__init__(message=message, status_code=504)


# ---------------------------------------------------------------------------
# Global exception handler — uniform error JSON shape
# ---------------------------------------------------------------------------

from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.logger import logger

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
