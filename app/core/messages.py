"""
app/core/messages.py
Centralized string constants for all API error and success messages.
Import these instead of hardcoding strings in routers.
"""

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
SESSION_NOT_FOUND         = "Session '{}' not found."

# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
INGEST_INVALID_URL        = "Cannot parse GitHub URL: '{}'. Use https://github.com/owner/repo format."
INGEST_NO_BRANCHES        = "No branches found for '{}'. Check the URL or ensure the repo is public."
INGEST_REPO_ERROR         = "Repository fetch failed: {}"
INGEST_FILE_UNSUPPORTED   = "Only PDF and TXT files are supported."
INGEST_FILE_EMPTY         = "Could not extract text from '{}'."
INGEST_SERVICE_BUSY       = "Ingest service is at capacity. Please retry in a moment."

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
CHAT_TIMEOUT              = "Response timed out after {}s. Please try again."
CHAT_NO_CONTEXT           = "No content ingested yet. Please upload a repository or document first."

# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
DOCUMENT_NOT_FOUND        = "No document generated yet. Call POST /generate first."
DOCUMENT_NO_CONTENT       = "No content has been ingested yet for this session."
DOCUMENT_PDF_ERROR        = "PDF generation failed (Playwright error)."
DOCUMENT_DOCX_ERROR       = "DOCX generation failed (Pandoc error): {}"

# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------
INTERNAL_ERROR            = "An internal error occurred. Please try again."
