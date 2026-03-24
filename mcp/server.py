"""
MemFabric - Self-Organizing Memory Layer for LLMs
A self-hosted MCP server that gives any LLM persistent, self-organizing memory.
"""

import io
import os
import json
import logging
import secrets
import time
import zipfile
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import uvicorn

# --- Configuration ---

DATA_DIR = Path(os.environ.get("MEMFABRIC_DATA_DIR", "/data"))
MEMORY_DIR = DATA_DIR / "memory"
SYSTEM_DIR = DATA_DIR / "system"
RULES_FILE = SYSTEM_DIR / "rules.md"
STATUS_FILE = SYSTEM_DIR / "status.json"
PORT = int(os.environ.get("PORT", 8000))
AUTH_TOKEN = os.environ.get("MEMFABRIC_TOKEN", "")
SERVER_URL = os.environ.get("MEMFABRIC_SERVER_URL", f"http://localhost:{PORT}")
LOG_FILE = DATA_DIR / "log.txt"

# --- Logging ---

logger = logging.getLogger("memfabric")
logger.setLevel(logging.INFO)
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_formatter)
logger.addHandler(_stream_handler)


def _setup_file_logging():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _file_handler = logging.FileHandler(LOG_FILE)
        _file_handler.setFormatter(_formatter)
        logger.addHandler(_file_handler)
    except OSError:
        logger.warning("Could not create log file at %s, logging to stdout only", LOG_FILE)


_setup_file_logging()

# --- Server Description ---

SERVER_DESCRIPTION = """\
You have persistent memory across all conversations via MemFabric.

EVERY CONVERSATION:
1. Call get_rules() first to check onboarding status.
2. Call list_memories() to see what you already know.
3. Read any files relevant to the current topic.
4. Throughout the conversation, store new facts automatically.

WHAT TO STORE (always, without asking):
- Preferences and opinions: "I like X", "I prefer Y", "X is my favorite"
- Personal facts: moved to Berlin, started new job, has a daughter
- People: names, roles, relationships the user mentions
- Decisions: "we chose Postgres", "I decided to learn Rust"
- Projects and goals: timelines, status updates, plans
- Interests: favorite books, papers, hobbies, topics they care about

WHEN TO ASK before storing:
- Ambiguous statements where it's unclear if the user wants it remembered
- Sensitive topics where the user might not want a record

WHEN NOT TO STORE:
- Small talk, greetings, one-off questions about general knowledge
- Temporary task details (formatting requests, quick calculations)

HOW TO STORE:
- Call list_memories() before writing to find existing files to append to.
- Use remember() to append a dated entry to an existing or new file.
- Use update_memory() only to replace outdated content.
- Filenames must be semantic kebab-case: "career-goals", "favorite-papers", "family-context".

EXAMPLES:
- "Attention Is All You Need is my favorite paper" → remember("favorite-papers", ...)
- "I just moved to Berlin" → remember("about-{name}", ...) or update existing profile
- "We decided to use Postgres" → remember("project-tech-decisions", ...)
- "My daughter started kindergarten" → remember("family", ...)
- "I prefer dark mode in everything" → remember("preferences", ...)

ONBOARDING (only when is_onboarded is false):
Call start(), then have a natural conversation to learn about the user.
Store their profile and set is_onboarded to true when done."""

# --- Default Rules ---

DEFAULT_RULES = """\
# Memory Rules

## Status
is_onboarded: false

## What to store
- Anything that might be useful in future conversations
- Preferences, decisions, opinions, and the reasoning behind them
- People the user mentions and context about them
- Projects, goals, and their status
- Ideas, hypotheses, and evolving thinking
- Life context (family, location, work, interests)
- Things the user explicitly asks to remember

## What to skip
- Small talk and pleasantries
- One-off questions with no lasting relevance
- Anything the user explicitly says to forget
- Temporary task details (formatting requests, one-off calculations)

## How to store
- Keep entries lean: capture the insight, not the full conversation
- When storing a decision, include the reasoning
- When storing a person, include relationship context
- Write so it's useful months from now when context is lost

## File naming
- Use lowercase kebab-case
- Be specific and semantic
- The filename alone should tell you what's inside

## Language
- Write memory entries in English

## Reorganization
- Reorganize when files_since_last_reorganize exceeds threshold
- Prefer merging over accumulating many small overlapping files
- When merging, synthesize a coherent document, don't just concatenate
"""

DEFAULT_STATUS = {
    "files_since_last_reorganize": 0,
    "last_reorganize_date": None,
    "reorganize_threshold": 10,
}

# --- Initialize ---


def _ensure_dirs():
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        if not RULES_FILE.exists():
            RULES_FILE.write_text(DEFAULT_RULES)
        if not STATUS_FILE.exists():
            STATUS_FILE.write_text(json.dumps(DEFAULT_STATUS, indent=2))
    except OSError as e:
        # At import time, paths may not exist yet (tests monkeypatch them).
        # Log and continue — tools will fail clearly if dirs are truly missing.
        logger.debug("_ensure_dirs skipped: %s", e)


_ensure_dirs()

# --- Storage Helpers ---


def _read_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        _ensure_dirs()
        return DEFAULT_STATUS.copy()


def _write_status(status: dict):
    STATUS_FILE.write_text(json.dumps(status, indent=2))


def _increment_file_count():
    status = _read_status()
    status["files_since_last_reorganize"] = (
        status.get("files_since_last_reorganize", 0) + 1
    )
    _write_status(status)


def _memory_path(filename: str) -> Path:
    name = filename.removesuffix(".md")
    return MEMORY_DIR / f"{name}.md"


def _sanitize_filename(filename: str) -> str:
    name = filename.removesuffix(".md")
    sanitized = ""
    for c in name.lower():
        if c.isalnum() or c == "-":
            sanitized += c
        elif c in (" ", "_"):
            sanitized += "-"
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized.strip("-")


def _count_entries(filepath: Path) -> int:
    if not filepath.exists():
        return 0
    content = filepath.read_text()
    count = content.count("\n## ")
    if content.startswith("## "):
        count += 1
    return count


def _first_content_line(filepath: Path) -> str:
    if not filepath.exists():
        return ""
    content = filepath.read_text()
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:100]
    return ""


# --- OAuth Provider ---


class MemFabricOAuthProvider(OAuthAuthorizationServerProvider):
    """In-memory OAuth 2.0 provider with login gate. When MEMFABRIC_TOKEN is
    set, the authorize step redirects to a login page where the user must
    enter the token before the OAuth flow completes. Also accepts the static
    MEMFABRIC_TOKEN as a valid Bearer token for non-OAuth clients."""

    def __init__(self):
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._pending_auths: dict[str, dict] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info
        logger.info("oauth=register client_id=%s", client_info.client_id)

    def _create_auth_code(self, client_id: str, params: AuthorizationParams) -> str:
        """Generate an authorization code and store it."""
        code = secrets.token_hex(20)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            scopes=params.scopes or [],
            expires_at=time.time() + 600,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return code

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if AUTH_TOKEN:
            # Require login — store pending auth and redirect to login page
            pending_id = secrets.token_hex(16)
            self._pending_auths[pending_id] = {
                "client_id": client.client_id,
                "params": params,
                "created_at": time.time(),
            }
            logger.info("oauth=authorize_pending client_id=%s pending=%s", client.client_id, pending_id)
            return f"{SERVER_URL}/login?pending={pending_id}"

        # No token configured — auto-approve (development mode)
        code = self._create_auth_code(client.client_id, params)
        logger.info("oauth=authorize_auto client_id=%s", client.client_id)
        return construct_redirect_uri(
            str(params.redirect_uri), code=code, state=params.state
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self._auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        access = secrets.token_hex(32)
        refresh = secrets.token_hex(32)

        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + 3600,
            resource=authorization_code.resource,
        )
        self._refresh_tokens[refresh] = RefreshToken(
            token=refresh,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
        )
        self._auth_codes.pop(authorization_code.code, None)

        logger.info("oauth=token_exchange client_id=%s", client.client_id)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=refresh,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return self._refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self._refresh_tokens.pop(refresh_token.token, None)

        access = secrets.token_hex(32)
        new_refresh = secrets.token_hex(32)
        effective_scopes = scopes or refresh_token.scopes

        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=int(time.time()) + 3600,
        )
        self._refresh_tokens[new_refresh] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=effective_scopes,
        )

        logger.info("oauth=refresh client_id=%s", client.client_id)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=new_refresh,
            scope=" ".join(effective_scopes) if effective_scopes else None,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        # Accept static MEMFABRIC_TOKEN for non-OAuth clients
        if AUTH_TOKEN and token == AUTH_TOKEN:
            return AccessToken(token=token, client_id="static", scopes=[])

        access = self._access_tokens.get(token)
        if access and access.expires_at is not None and access.expires_at < int(time.time()):
            self._access_tokens.pop(token, None)
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
        else:
            self._access_tokens.pop(token.token, None)
        logger.info("oauth=revoke token_type=%s", type(token).__name__)


_oauth_provider = MemFabricOAuthProvider()

# --- MCP Server ---

_server_host = SERVER_URL.split("://", 1)[-1].rstrip("/")

mcp = FastMCP(
    "MemFabric",
    instructions=SERVER_DESCRIPTION,
    auth=AuthSettings(
        issuer_url=SERVER_URL,
        resource_server_url=SERVER_URL,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["claudeai"],
            default_scopes=["claudeai"],
        ),
    ),
    auth_server_provider=_oauth_provider,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{_server_host}:*", _server_host, "localhost:*", "127.0.0.1:*"],
        allowed_origins=[f"{SERVER_URL}:*", SERVER_URL, "http://localhost:*", "http://127.0.0.1:*"],
    ),
)

# --- Tools ---


@mcp.tool()
def start() -> str:
    """Start onboarding. Call this when get_rules() shows is_onboarded: false.

    Begins a friendly conversation to learn about the user. Ask one or two questions at a time, not all at once. Learn their name, age, location, family, work, and preferred language.

    After the conversation, call remember() to store their profile in a file named "about-{name}", then call edit_rules() to set is_onboarded: true. Only needs to happen once."""
    logger.info("tool=start onboarding initiated")
    return (
        "Welcome! I'm your memory layer. I work across all your AI tools, "
        "so anything I learn here, your other tools will know too.\n\n"
        "Let me learn a bit about you first. What should I call you?"
    )


@mcp.tool()
def remember(filename: str, content: str, entry_date: Optional[str] = None) -> dict:
    """Store a fact, preference, decision, or any information worth keeping across conversations. This is the primary write tool — call it whenever the user shares something memorable.

    Always call list_memories() first to check if a relevant file exists. If it does, use that filename to append. If not, create a new one. Each call appends a dated entry; existing entries are preserved.

    Use semantic kebab-case filenames that describe the content. Good: "favorite-papers", "career-goals", "family-context". Bad: "misc-notes", "march-2026", "conversation-5".

    Write lean content — capture the insight or fact, not the full conversation.

    Args:
        filename: semantic kebab-case filename without .md extension, e.g. "favorite-papers"
        content: the entry text to store
        entry_date: ISO date string (YYYY-MM-DD), defaults to today
    """
    safe_name = _sanitize_filename(filename)
    if not safe_name:
        logger.warning("tool=remember error='invalid filename' input=%r", filename)
        return {"error": "Invalid filename"}

    filepath = _memory_path(safe_name)
    if entry_date:
        try:
            date.fromisoformat(entry_date)
        except ValueError:
            return {"error": f"Invalid date format: '{entry_date}'. Use YYYY-MM-DD."}
    date_str = entry_date or date.today().isoformat()
    is_new = not filepath.exists()

    entry = f"\n## {date_str}\n{content}\n"

    if is_new:
        title = safe_name.replace("-", " ").title()
        filepath.write_text(f"# {title}\n{entry}")
        _increment_file_count()
    else:
        with open(filepath, "a") as f:
            f.write(entry)

    entry_count = _count_entries(filepath)

    logger.info(
        "tool=remember file=%s date=%s is_new=%s entries=%d",
        safe_name, date_str, is_new, entry_count,
    )
    return {
        "status": "stored",
        "filename": safe_name,
        "is_new_file": is_new,
        "entry_count": entry_count,
    }


@mcp.tool()
def list_memories() -> list[dict]:
    """List all memory files with metadata. Call this at the start of every conversation and before calling remember() to check for existing files. Returns filenames, entry counts, last updated dates, and sizes. Filenames are semantic, so scan them to decide which to read with read_memory()."""
    logger.info("tool=list_memories")
    memories = []
    for filepath in sorted(MEMORY_DIR.glob("*.md")):
        stat = filepath.stat()
        memories.append(
            {
                "filename": filepath.stem,
                "entry_count": _count_entries(filepath),
                "last_updated": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d"
                ),
                "size_bytes": stat.st_size,
                "first_line": _first_content_line(filepath),
            }
        )
    return memories


@mcp.tool()
def read_memory(filename: str) -> str:
    """Read the full contents of a memory file. Call this after list_memories() to read files relevant to the current conversation. Always read before responding so your answers reflect what you know about the user. You can read multiple files in sequence.

    Args:
        filename: the filename to read, without .md extension, e.g. "favorite-papers"
    """
    safe_name = _sanitize_filename(filename)
    filepath = _memory_path(safe_name)

    if not filepath.exists():
        logger.warning("tool=read_memory file=%s error='not found'", safe_name)
        return f"Error: Memory file '{safe_name}.md' not found."

    logger.info("tool=read_memory file=%s", safe_name)
    return filepath.read_text()


@mcp.tool()
def read_all_memories() -> str:
    """Dump the full contents of every memory file. WARNING: This outputs a large amount of text into the context window. Only call this when the user explicitly asks to see all their memories (e.g. "show me everything you remember", "dump all memories"). For normal use, prefer list_memories() + read_memory() to read only relevant files."""
    logger.info("tool=read_all_memories")
    files = sorted(MEMORY_DIR.glob("*.md"))
    if not files:
        return "No memories stored yet."

    parts = []
    for filepath in files:
        parts.append(f"=== {filepath.stem} ===\n{filepath.read_text()}")

    logger.info("tool=read_all_memories files=%d", len(files))
    return "\n\n".join(parts)


@mcp.tool()
def update_memory(filename: str, content: str) -> dict:
    """Replace the entire contents of a memory file. Use this when information is outdated ("I moved to Berlin", "I quit that job") or when a file needs rewriting for clarity. Always call read_memory() first so you know what you're replacing. If you want to add a new entry while keeping existing ones, use remember() instead.

    Args:
        filename: the filename to overwrite, without .md extension
        content: the complete new file content
    """
    safe_name = _sanitize_filename(filename)
    if not safe_name:
        logger.warning("tool=update_memory error='invalid filename' input=%r", filename)
        return {"error": "Invalid filename"}

    filepath = _memory_path(safe_name)

    if not filepath.exists():
        logger.warning("tool=update_memory file=%s error='not found'", safe_name)
        return {
            "error": f"Memory file '{safe_name}.md' not found. Use remember() to create new files."
        }

    filepath.write_text(content)

    logger.info("tool=update_memory file=%s size=%d", safe_name, filepath.stat().st_size)
    return {
        "status": "updated",
        "filename": safe_name,
        "size_bytes": filepath.stat().st_size,
    }


@mcp.tool()
def reorganize(operations: list[dict]) -> dict:
    """Restructure memory files by merging, splitting, synthesizing, or renaming. Call this when get_status() shows many files since last reorganize, or when files overlap. Read the files you plan to reorganize first.

    Operations: merge (combine files, deletes sources), split (break file into parts, deletes source), synthesize (create insight from multiple files, keeps sources), rename (change filename, keeps content).

    Args:
        operations: list of operation dicts. Each must have "type" plus:
            - merge: source_files (list), target_filename (str), content (str)
            - split: source_file (str), new_files (dict of filename → content)
            - synthesize: source_files (list), target_filename (str), content (str)
            - rename: old_filename (str), new_filename (str)
    """
    logger.info("tool=reorganize operations_count=%d", len(operations))
    results = {
        "operations_completed": 0,
        "files_created": [],
        "files_deleted": [],
        "files_renamed": [],
        "errors": [],
    }

    for op in operations:
        op_type = op.get("type", "").lower()

        try:
            if op_type == "merge":
                source_files = op.get("source_files", [])
                target = _sanitize_filename(op.get("target_filename", ""))
                content = op.get("content", "")

                if not target or not content or len(source_files) < 2:
                    results["errors"].append(
                        "Merge: need target_filename, content, and at least 2 source_files"
                    )
                    continue

                missing = [
                    f
                    for f in source_files
                    if not _memory_path(_sanitize_filename(f)).exists()
                ]
                if missing:
                    results["errors"].append(
                        f"Merge: source files not found: {missing}"
                    )
                    continue

                target_path = _memory_path(target)
                target_path.write_text(content)
                results["files_created"].append(target)

                for src in source_files:
                    src_safe = _sanitize_filename(src)
                    src_path = _memory_path(src_safe)
                    if src_path != target_path:
                        src_path.unlink()
                        results["files_deleted"].append(src_safe)

                results["operations_completed"] += 1

            elif op_type == "split":
                source = _sanitize_filename(op.get("source_file", ""))
                new_files = op.get("new_files", {})

                if not source or not new_files:
                    results["errors"].append(
                        "Split: need source_file and new_files"
                    )
                    continue

                source_path = _memory_path(source)
                if not source_path.exists():
                    results["errors"].append(
                        f"Split: source file '{source}.md' not found"
                    )
                    continue

                for fname, fcontent in new_files.items():
                    safe = _sanitize_filename(fname)
                    fpath = _memory_path(safe)
                    fpath.write_text(fcontent)
                    results["files_created"].append(safe)

                source_path.unlink()
                results["files_deleted"].append(source)
                results["operations_completed"] += 1

            elif op_type == "synthesize":
                source_files = op.get("source_files", [])
                target = _sanitize_filename(op.get("target_filename", ""))
                content = op.get("content", "")

                if not target or not content or not source_files:
                    results["errors"].append(
                        "Synthesize: need source_files, target_filename, and content"
                    )
                    continue

                missing = [
                    f
                    for f in source_files
                    if not _memory_path(_sanitize_filename(f)).exists()
                ]
                if missing:
                    results["errors"].append(
                        f"Synthesize: source files not found: {missing}"
                    )
                    continue

                target_path = _memory_path(target)
                target_path.write_text(content)
                results["files_created"].append(target)
                results["operations_completed"] += 1

            elif op_type == "rename":
                old = _sanitize_filename(op.get("old_filename", ""))
                new = _sanitize_filename(op.get("new_filename", ""))

                if not old or not new:
                    results["errors"].append(
                        "Rename: need old_filename and new_filename"
                    )
                    continue

                old_path = _memory_path(old)
                if not old_path.exists():
                    results["errors"].append(f"Rename: '{old}.md' not found")
                    continue

                new_path = _memory_path(new)
                old_path.rename(new_path)
                results["files_renamed"].append({"from": old, "to": new})
                results["operations_completed"] += 1

            else:
                results["errors"].append(f"Unknown operation type: '{op_type}'")

        except (ValueError, KeyError, TypeError, OSError) as e:
            logger.error("tool=reorganize op=%s error=%s", op_type, e)
            results["errors"].append(f"{op_type}: {e}")

    # Reset reorganize counter
    status = _read_status()
    status["files_since_last_reorganize"] = 0
    status["last_reorganize_date"] = date.today().isoformat()
    _write_status(status)

    logger.info(
        "tool=reorganize completed=%d created=%s deleted=%s renamed=%s errors=%d",
        results["operations_completed"],
        results["files_created"],
        results["files_deleted"],
        results["files_renamed"],
        len(results["errors"]),
    )
    return results


@mcp.tool()
def edit_rules(content: str) -> dict:
    """Update memory behavior rules. Call get_rules() first, modify, then write back. Use when the user wants to change what gets stored, naming conventions, language, or any standing instructions (e.g. "stop storing health info", "write entries in Spanish").

    Args:
        content: the complete new rules.md content
    """
    RULES_FILE.write_text(content)
    logger.info("tool=edit_rules size=%d", RULES_FILE.stat().st_size)
    return {"status": "rules_updated", "size_bytes": RULES_FILE.stat().st_size}


@mcp.tool()
def get_rules() -> str:
    """Read the memory rules and onboarding status. Call this at the start of every conversation. If is_onboarded is false, call start() to begin onboarding. Rules define what to store, naming conventions, language, and user-specific instructions."""
    logger.info("tool=get_rules")
    if not RULES_FILE.exists():
        _ensure_dirs()
    return RULES_FILE.read_text()


@mcp.tool()
def get_status() -> dict:
    """Check memory system health and whether reorganization is needed. Returns total files, files since last reorganize, largest files, and oldest untouched files. Call this after storing memories; if files_since_last_reorganize exceeds the threshold, consider calling reorganize()."""
    logger.info("tool=get_status")
    status = _read_status()

    memory_files = list(MEMORY_DIR.glob("*.md"))
    total_size = sum(f.stat().st_size for f in memory_files)

    file_stats = []
    for f in memory_files:
        stat = f.stat()
        file_stats.append(
            {
                "name": f.stem,
                "entries": _count_entries(f),
                "bytes": stat.st_size,
                "last_updated": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d"
                ),
            }
        )

    largest = sorted(file_stats, key=lambda x: x["bytes"], reverse=True)[:5]
    oldest = sorted(file_stats, key=lambda x: x["last_updated"])[:5]

    return {
        "total_files": len(memory_files),
        "files_since_last_reorganize": status.get("files_since_last_reorganize", 0),
        "last_reorganize_date": status.get("last_reorganize_date"),
        "largest_files": [
            {"name": f["name"], "entries": f["entries"], "bytes": f["bytes"]}
            for f in largest
        ],
        "oldest_untouched_files": [
            {"name": f["name"], "last_updated": f["last_updated"]} for f in oldest
        ],
        "total_memory_size_bytes": total_size,
        "reorganize_threshold": status.get("reorganize_threshold", 10),
    }


# --- Login Page ---

LOGIN_PAGE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MemFabric — Authorize</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0a0a0a; color: #e0e0e0; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 12px;
          padding: 2rem; max-width: 400px; width: 90%; }
  h1 { font-size: 1.3rem; margin-bottom: 0.5rem; }
  p { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
  input[type=password] { width: 100%; padding: 0.75rem; border: 1px solid #333;
         border-radius: 8px; background: #111; color: #e0e0e0; font-size: 1rem;
         margin-bottom: 1rem; }
  input[type=password]:focus { outline: none; border-color: #666; }
  button { width: 100%; padding: 0.75rem; border: none; border-radius: 8px;
           background: #fff; color: #000; font-size: 1rem; font-weight: 600;
           cursor: pointer; }
  button:hover { background: #ddd; }
  .error { color: #ff6b6b; font-size: 0.85rem; margin-bottom: 1rem; }
</style>
</head>
<body>
<div class="card">
  <h1>MemFabric</h1>
  <p>Enter your access token to authorize this connection.</p>
  {{error}}
  <form method="POST" action="/login">
    <input type="hidden" name="pending" value="{{pending}}">
    <input type="password" name="token" placeholder="Access token" autofocus required>
    <button type="submit">Authorize</button>
  </form>
</div>
</body>
</html>
"""

# --- Middleware ---


class MemFabricMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return Response("OK", status_code=200)

        if request.url.path == "/download":
            # Require token auth
            if AUTH_TOKEN:
                auth_header = request.headers.get("authorization", "")
                if auth_header != f"Bearer {AUTH_TOKEN}":
                    return Response("Unauthorized", status_code=401)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for filepath in sorted(MEMORY_DIR.glob("*.md")):
                    zf.write(filepath, f"memory/{filepath.name}")
                if RULES_FILE.exists():
                    zf.write(RULES_FILE, "system/rules.md")
                if STATUS_FILE.exists():
                    zf.write(STATUS_FILE, "system/status.json")
            buf.seek(0)
            logger.info("tool=download size=%d", buf.getbuffer().nbytes)
            return Response(
                buf.getvalue(),
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=memfabric-export.zip"},
            )

        if request.url.path == "/login":
            if request.method == "GET":
                pending = request.query_params.get("pending", "")
                html = LOGIN_PAGE.replace("{{pending}}", pending).replace("{{error}}", "")
                return Response(html, media_type="text/html")

            elif request.method == "POST":
                form = await request.form()
                token = form.get("token", "")
                pending_id = form.get("pending", "")

                pending = _oauth_provider._pending_auths.pop(pending_id, None)

                if not pending:
                    html = LOGIN_PAGE.replace("{{pending}}", "").replace(
                        "{{error}}", '<p class="error">Session expired. Please try connecting again.</p>'
                    )
                    return Response(html, media_type="text/html", status_code=400)

                # Expire after 10 minutes
                if time.time() - pending["created_at"] > 600:
                    html = LOGIN_PAGE.replace("{{pending}}", "").replace(
                        "{{error}}", '<p class="error">Session expired. Please try connecting again.</p>'
                    )
                    return Response(html, media_type="text/html", status_code=400)

                if token != AUTH_TOKEN:
                    # Put it back so user can retry
                    _oauth_provider._pending_auths[pending_id] = pending
                    html = LOGIN_PAGE.replace("{{pending}}", pending_id).replace(
                        "{{error}}", '<p class="error">Invalid token. Please try again.</p>'
                    )
                    return Response(html, media_type="text/html", status_code=401)

                # Token correct — complete the OAuth flow
                params = pending["params"]
                code = _oauth_provider._create_auth_code(pending["client_id"], params)
                redirect_url = construct_redirect_uri(
                    str(params.redirect_uri), code=code, state=params.state
                )
                logger.info("oauth=login_approved client_id=%s", pending["client_id"])
                from starlette.responses import RedirectResponse
                return RedirectResponse(url=redirect_url, status_code=302)

        return await call_next(request)


# --- Main ---

if __name__ == "__main__":
    logger.info(
        "starting MemFabric on port=%d data_dir=%s server_url=%s",
        PORT, DATA_DIR, SERVER_URL,
    )
    app = mcp.streamable_http_app()
    app.add_middleware(MemFabricMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
