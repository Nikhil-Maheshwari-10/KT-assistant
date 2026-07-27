"""
app/core/exceptions.py
Structured application exception hierarchy.

All exceptions inherit from AppException (which extends HTTPException) so
FastAPI's default handler and our custom global handler both work seamlessly.
The global handler in main.py logs all AppExceptions uniformly and returns
a consistent JSON error shape: {"error": "<message>"}.
"""
from fastapi import HTTPException


class AppException(HTTPException):
    """Base application exception — maps to a specific HTTP status code."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(status_code=status_code, detail=message)


class NotFoundException(AppException):
    """404 — Resource does not exist."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=404)


class BadRequestException(AppException):
    """400 — Caller sent invalid input."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=400)


class UnprocessableException(AppException):
    """422 — Input is syntactically valid but semantically unparseable."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=422)


class ServiceUnavailableException(AppException):
    """503 — Downstream service (Gemini, Qdrant, etc.) is unavailable."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=503)
