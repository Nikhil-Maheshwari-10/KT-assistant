"""
GitHub Repository Ingestion Service (Phase 1 — Public Repos)

Fetches relevant files from a public GitHub repository and aggregates
them into a single text blob suitable for feeding into process_knowledge().
"""

import re
import requests
import zipfile
import io
from typing import Optional
from dataclasses import dataclass, field
from app.core.config import settings
from app.core.logger import logger
from app.services.doc_processor import chunk_text


# ---------------------------------------------------------------------------
# Configuration (sourced from settings / .env — see app/core/config.py)
# ---------------------------------------------------------------------------

# GitHub API base
GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

# File patterns — ordered by priority (checked top-to-bottom)
HIGH_PRIORITY_PATTERNS = [
    r"^README(\..+)?$",                  # README, README.md, README.rst …
    r"^readme(\..+)?$",
    r"^docs?/.*\.(md|rst|txt)$",         # docs/ folder markdown
    r"^wiki/.*\.(md|rst|txt)$",
    r"^ARCHITECTURE(\..+)?$",
    r"^CONTRIBUTING(\..+)?$",
    r"^CHANGELOG(\..+)?$",
]

MEDIUM_PRIORITY_PATTERNS = [
    r".*docker-compose.*\.(yml|yaml)$",
    r"^docker-compose\.(yml|yaml)$",
    r"^pyproject\.toml$",
    r"^package\.json$",
    r"^requirements.*\.txt$",
    r"^setup\.(py|cfg)$",
    r"^Makefile$",
    r"^\.env\.example$",
    r".*\.(yml|yaml)$",                  # any YAML
    r".*\.(toml)$",
]

LOW_PRIORITY_PATTERNS = [
    # All source files at ANY depth in the repo
    r".*\.(py|ts|js|jsx|tsx|go|java|rb|rs|cs|cpp|c|h|hpp|swift|kt|scala|php|sh|bash)$",
]

SKIP_PATTERNS = [
    r"node_modules/",
    r"\.git/",
    r"\.venv/",
    r"venv/",
    r"__pycache__/",
    r"\.pytest_cache/",
    r"dist/",
    r"build/",
    r"\.lock$",
    r"poetry\.lock$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"\.(png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|mp4|mp3|zip|tar|gz|bin|exe|so|dylib)$",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GitHubIngestResult:
    owner: str
    repo: str
    branch: str
    files_fetched: list = field(default_factory=list)
    total_chars: int = 0
    aggregated_text: str = ""
    chunks: list = field(default_factory=list)  # List of {file_path, content, chunk_index}
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def summary(self) -> str:
        kb = self.total_chars / 1024
        return f"{self.owner}/{self.repo} — {len(self.files_fetched)} files, {kb:.1f} KB, {len(self.chunks)} chunks"


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def parse_github_url(url: str) -> Optional[tuple[str, str, Optional[str]]]:
    """
    Parses a GitHub URL into (owner, repo, branch_or_None).
    Handles formats:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/tree/branch
      - github.com/owner/repo
    Returns None if the URL is not a recognisable GitHub URL.
    """
    url = url.strip().rstrip("/")
    # Normalise: strip protocol
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)

    # If it's a full URL, strip the domain. Otherwise assume it's owner/repo
    if url.startswith("github.com/"):
        url = url[len("github.com/"):]

    parts = url.split("/")
    if len(parts) < 2:
        return None

    owner = parts[0]
    repo = parts[1].removesuffix(".git")

    branch = None
    if len(parts) >= 4 and parts[2] == "tree":
        branch = "/".join(parts[3:])

    return owner, repo, branch


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------

def _get_priority(path: str) -> int:
    """Returns 0 (skip), 1 (low), 2 (medium), 3 (high). Higher = fetch first."""
    for pat in SKIP_PATTERNS:
        if re.search(pat, path, re.IGNORECASE):
            return 0

    for pat in HIGH_PRIORITY_PATTERNS:
        if re.match(pat, path, re.IGNORECASE):
            return 3

    for pat in MEDIUM_PRIORITY_PATTERNS:
        if re.match(pat, path, re.IGNORECASE):
            return 2

    for pat in LOW_PRIORITY_PATTERNS:
        if re.match(pat, path, re.IGNORECASE):
            return 1

    return 0  # skip everything else


# ---------------------------------------------------------------------------
# Core fetching logic
# ---------------------------------------------------------------------------

def _build_headers(token: Optional[str] = None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_default_branch(owner: str, repo: str, token: Optional[str] = None) -> str:
    """Fetches the default branch name from the repo metadata."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        resp = requests.get(url, headers=_build_headers(token), timeout=10)
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")
    except Exception as e:
        logger.warning(f"Could not determine default branch for {owner}/{repo}: {e}. Falling back to 'main'.")
        return "main"


def fetch_branches(github_url: str, token: Optional[str] = None) -> list[str]:
    """Fetches all branches for a given GitHub repository URL."""
    parsed = parse_github_url(github_url)
    if not parsed:
        return []
        
    owner, repo, _ = parsed
    url = f"{GITHUB_API}/repos/{owner}/{repo}/branches"
    
    try:
        resp = requests.get(url, headers=_build_headers(token), timeout=10)
        resp.raise_for_status()
        return [branch["name"] for branch in resp.json()]
    except Exception as e:
        logger.warning(f"Could not fetch branches for {owner}/{repo}: {e}")
        return []


def _get_repo_tree(owner: str, repo: str, branch: str, token: Optional[str]) -> list[dict]:
    """Fetches the full recursive file tree from GitHub."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    resp = requests.get(url, headers=_build_headers(token), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("truncated"):
        logger.warning(f"GitHub tree for {owner}/{repo} was truncated — very large repo. Results may be partial.")
    return [item for item in data.get("tree", []) if item.get("type") == "blob"]


def _fetch_raw_file(owner: str, repo: str, branch: str, path: str, token: Optional[str]) -> Optional[str]:
    """Fetches raw file content. Returns None if fetch fails or file is too large."""
    url = f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}"
    try:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        content = resp.text
        if len(content.encode("utf-8")) > settings.MAX_FILE_BYTES:
            # Truncate to avoid token blowout
            content = content[: settings.MAX_FILE_BYTES] + "\n\n[... file truncated for length ...]"
        return content
    except Exception as e:
        logger.warning(f"Failed to fetch {path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_repo_content(github_url: str, token: Optional[str] = None) -> GitHubIngestResult:
    """
    Main entry point. Given a GitHub URL (public repo), fetches relevant
    files and returns a GitHubIngestResult with aggregated text ready for
    feeding into process_knowledge().

    Args:
        github_url: Any recognisable GitHub URL (with or without https://).
        token:      Optional GitHub Personal Access Token (for private repos in Phase 2).

    Returns:
        GitHubIngestResult — check .success before using .aggregated_text.
    """
    # 1. Parse URL
    parsed = parse_github_url(github_url)
    if not parsed:
        return GitHubIngestResult(
            owner="", repo="", branch="",
            error=f"Could not parse GitHub URL: '{github_url}'. Expected format: https://github.com/owner/repo"
        )

    owner, repo, branch_hint = parsed
    logger.info(f"GitHub ingestion started for {owner}/{repo}")

    # 2. Resolve branch
    branch = branch_hint or _get_default_branch(owner, repo, token)
    result = GitHubIngestResult(owner=owner, repo=repo, branch=branch)

    # 3. Fetch file tree
    try:
        tree = _get_repo_tree(owner, repo, branch, token)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        if status == 404:
            result.error = f"Repository '{owner}/{repo}' not found or is private. Check the URL."
        elif status == 403:
            result.error = "GitHub API rate limit exceeded. Please wait a few minutes and try again."
        else:
            result.error = f"GitHub API error ({status}): {e}"
        return result
    except Exception as e:
        result.error = f"Could not reach GitHub: {e}"
        return result

    # 4. Score and sort files by priority
    scored = []
    for item in tree:
        path = item.get("path", "")
        size = item.get("size", 0)
        priority = _get_priority(path)
        if priority > 0:
            scored.append((priority, size, path))

    # Sort: highest priority first, then smallest size (to pack more in budget)
    scored.sort(key=lambda x: (-x[0], x[1]))

    # 5. Fetch content up to limits
    sections = []
    total_chars = 0
    skipped_budget = 0

    logger.info(f"Total files to scan: {len(scored)} (after skip-pattern filtering)")

    for priority, size, path in scored:
        if len(result.files_fetched) >= settings.MAX_FILES:
            skipped_budget += 1
            logger.info(f"Reached max file limit ({settings.MAX_FILES}). Remaining skipped: {len(scored) - len(result.files_fetched) - skipped_budget + 1}")
            break
        if total_chars >= settings.MAX_TOTAL_CHARS:
            skipped_budget += 1
            logger.info(f"Reached character budget ({settings.MAX_TOTAL_CHARS:,} chars / {settings.MAX_TOTAL_CHARS/1024:.0f} KB). Stopping fetch.")
            break

        content = _fetch_raw_file(owner, repo, branch, path, token)
        if not content:
            continue

        header = f"\n\n{'='*60}\n📄 FILE: {path}\n{'='*60}\n"
        section = header + content
        sections.append(section)
        result.files_fetched.append(path)
        total_chars += len(section)
        logger.info(f"  [{len(result.files_fetched):>3}] Fetched: {path} ({len(content):,} chars)")

        # Chunk this file's content for Qdrant RAG indexing
        if len(result.chunks) < settings.MAX_CHUNKS:
            file_chunks = chunk_text(content, source_name=path)
            remaining = settings.MAX_CHUNKS - len(result.chunks)
            result.chunks.extend(file_chunks[:remaining])

    if not sections:
        result.error = "No relevant files could be fetched from this repository."
        return result

    # 6. Build preamble + aggregated text
    preamble = (
        f"# GitHub Repository: {owner}/{repo} (branch: {branch})\n\n"
        f"The following content was automatically extracted from the repository "
        f"to assist with Knowledge Transfer documentation.\n"
        f"Files included: {', '.join(result.files_fetched)}\n"
    )

    result.aggregated_text = preamble + "".join(sections)
    result.total_chars = total_chars
    logger.info(f"GitHub ingestion complete: {result.summary}")
    return result

def process_zip_file(zip_bytes: bytes, filename: str) -> GitHubIngestResult:
    result = GitHubIngestResult(owner="local", repo=filename, branch="zip")
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            file_list = z.namelist()
            scored = []
            for path in file_list:
                # Skip directories
                if path.endswith('/'):
                    continue
                
                size = z.getinfo(path).file_size
                priority = _get_priority(path)
                if priority > 0:
                    scored.append((priority, size, path))
            
            # Sort: highest priority first, then smallest size
            scored.sort(key=lambda x: (-x[0], x[1]))
            
            sections = []
            total_chars = 0
            skipped_budget = 0
            
            logger.info(f"Total files in ZIP to scan: {len(scored)}")
            
            for priority, size, path in scored:
                if len(result.files_fetched) >= settings.MAX_FILES:
                    skipped_budget += 1
                    break
                if total_chars >= settings.MAX_TOTAL_CHARS:
                    skipped_budget += 1
                    break
                    
                # Read content
                try:
                    raw_bytes = z.read(path)
                    # Try to decode as utf-8, fallback to latin-1
                    try:
                        content = raw_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        content = raw_bytes.decode('latin-1')
                        
                    # Basic binary check on content
                    if '\0' in content:
                        continue
                        
                except Exception as e:
                    logger.warning(f"Failed to read {path} from zip: {e}")
                    continue
                    
                if not content.strip():
                    continue

                header = f"\n\n{'='*60}\n📄 FILE: {path}\n{'='*60}\n"
                section = header + content
                sections.append(section)
                result.files_fetched.append(path)
                total_chars += len(section)
                logger.info(f"  [{len(result.files_fetched):>3}] Extracted: {path} ({len(content):,} chars)")
                
                # Chunk this file's content
                if len(result.chunks) < settings.MAX_CHUNKS:
                    file_chunks = chunk_text(content, source_name=path)
                    remaining = settings.MAX_CHUNKS - len(result.chunks)
                    result.chunks.extend(file_chunks[:remaining])
            
            if not sections:
                result.error = "No relevant text files could be extracted from this ZIP archive."
                return result
                
            preamble = (
                f"# ZIP Archive: {filename}\n\n"
                f"The following content was automatically extracted from the uploaded archive "
                f"to assist with Knowledge Transfer documentation.\n"
                f"Files included: {', '.join(result.files_fetched)}\n"
            )
            
            result.aggregated_text = preamble + "".join(sections)
            result.total_chars = total_chars
            logger.info(f"ZIP ingestion complete: {result.summary}")
            
    except zipfile.BadZipFile:
        result.error = "The uploaded file is not a valid ZIP archive."
    except Exception as e:
        result.error = f"Error processing ZIP archive: {str(e)}"
        
    return result
