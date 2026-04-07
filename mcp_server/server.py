import os
import logging
import contextvars
import time
import asyncio
import importlib
import hmac
import hashlib
from pathlib import Path
from collections import defaultdict
from threading import Lock
from typing import Any, Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import notion_client
from notion_client.errors import APIResponseError
from mcp.server import Server
from mcp.types import Tool, CallToolResult, TextContent
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from auth import resolve_workspace_id

load_dotenv(dotenv_path=Path(__file__).with_name('.env'), encoding='utf-8-sig')

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
_log = logging.getLogger(__name__)

# ============================================================================
# Request Context (for structured logging with request_id)
# ============================================================================
_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)
_request_start_time_var: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar("request_start_time", default=None)
_mcp_actor_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_actor_id", default=None)
_mcp_actor_type: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_actor_type", default=None)
_mcp_actor_signature: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_actor_signature", default=None)
_mcp_actor_timestamp: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_actor_timestamp", default=None)

def _log_with_context(level, msg, *args, **kwargs):
    """Log message with request_id if available."""
    request_id = _request_id_var.get()
    if request_id:
        msg = f"[{request_id}] {msg}"
    getattr(_log, level)(msg, *args, **kwargs)

def _get_remaining_time() -> Optional[float]:
    """Get remaining time in seconds for current request, or None if no deadline set."""
    start_time = _request_start_time_var.get()
    if start_time is None:
        return None
    elapsed = time.time() - start_time
    remaining = _REQUEST_TIMEOUT_SECONDS - elapsed
    return max(0.0, remaining)

# ============================================================================
# Performance Timing (built-in observability without OpenTelemetry)
# ============================================================================
from contextlib import contextmanager

@contextmanager
def _timed_operation(operation_name: str, log_threshold_ms: float = 100.0):
    """
    Context manager for timing operations and logging slow operations.
    
    Usage:
        with _timed_operation("notion.pages.create"):
            result = notion.pages.create(...)
    
    Logs operations exceeding log_threshold_ms automatically.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms >= log_threshold_ms:
            _log_with_context(
                "info",
                "Operation %s took %.1fms",
                operation_name,
                elapsed_ms
            )

# ============================================================================
# Timeout Configuration (3-layer defense)
# ============================================================================
_REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
_EMBED_TIMEOUT_SECONDS = float(os.getenv("EMBED_TIMEOUT_SECONDS", "8"))
_DB_SEARCH_TIMEOUT_MS = int(os.getenv("DB_SEARCH_TIMEOUT_MS", "3000"))
_DB_INGEST_TIMEOUT_MS = int(os.getenv("DB_INGEST_TIMEOUT_MS", "10000"))
_NOTION_HTTP_TIMEOUT = 5.0

# ============================================================================
# Request & Concurrency Limits
# ============================================================================
_MAX_REQUEST_BODY_SIZE = int(os.getenv("MAX_REQUEST_BODY_SIZE", "1000000"))  # 1MB default
_MAX_CHUNKS_PER_REQUEST = int(os.getenv("MAX_CHUNKS_PER_REQUEST", "200"))
_MAX_CONCURRENT_INGESTS = int(os.getenv("MAX_CONCURRENT_INGESTS", "4"))

# Ingestion concurrency semaphore (prevents DB contention)
_ingest_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_INGESTS)

# ============================================================================
# Error Code Normalization
# ============================================================================
class ErrorCode:
    """Stable error codes for client consumption."""
    INVALID_ARGUMENT = "invalid_argument"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    DEPENDENCY_FAILURE = "dependency_failure"
    INTERNAL_ERROR = "internal_error"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"

def error_response(code: str, message: str, retryable: bool = False) -> dict:
    """Return normalized error envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable
        }
    }


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _debug_enabled() -> bool:
    return _env_enabled("DEBUG")


def _strict_production_mode() -> bool:
    return _env_enabled("STRICT_PRODUCTION_MODE")


def _client_internal_error(operation_name: str) -> str:
    return f"{operation_name} failed"


def _rag_unavailable_message(reason: str) -> str:
    if _strict_production_mode():
        return "RAG unavailable"
    return f"RAG unavailable: {reason}"


def _get_actor_signing_secret() -> str:
    """Return actor-signing secret for stateless trusted actor propagation."""
    return os.getenv("ACTOR_SIGNING_SECRET", "")


def _get_actor_signature_max_age_seconds() -> int:
    return int(os.getenv("ACTOR_SIGNATURE_MAX_AGE_SECONDS", "300"))


def _sign_actor_identity(actor_id: str, actor_type: str, workspace_id: str, timestamp: str) -> str:
    secret = _get_actor_signing_secret()
    if not secret:
        raise RuntimeError("ACTOR_SIGNING_SECRET is not configured")
    message = f"{actor_id}:{actor_type}:{workspace_id}:{timestamp}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _resolve_actor_identity(
    payload: dict[str, Any],
    workspace_id: str,
    *,
    actor_id_header: str | None = None,
    actor_type_header: str | None = None,
    actor_signature_header: str | None = None,
    actor_timestamp_header: str | None = None,
) -> tuple[str, str]:
    """
    Resolve actor identity for stateless resource authorization.

    Modes:
    - Trusted signed-header mode when ACTOR_SIGNING_SECRET is configured
    - Payload fallback mode for local/dev environments when it is not configured
    """
    actor_secret = _get_actor_signing_secret()
    if actor_secret:
        if not actor_id_header:
            raise HTTPException(
                status_code=401,
                detail=error_response(
                    ErrorCode.UNAUTHORIZED,
                    "Signed actor identity required: X-Actor-Id header missing",
                    retryable=False,
                ),
            )
        actor_type = actor_type_header or "user"
        if not actor_signature_header:
            raise HTTPException(
                status_code=401,
                detail=error_response(
                    ErrorCode.UNAUTHORIZED,
                    "Signed actor identity required: X-Actor-Signature header missing",
                    retryable=False,
                ),
            )
        if not actor_timestamp_header:
            raise HTTPException(
                status_code=401,
                detail=error_response(
                    ErrorCode.UNAUTHORIZED,
                    "Signed actor identity required: X-Actor-Timestamp header missing",
                    retryable=False,
                ),
            )
        try:
            actor_timestamp = int(actor_timestamp_header)
        except ValueError as exc:
            raise HTTPException(
                status_code=401,
                detail=error_response(
                    ErrorCode.UNAUTHORIZED,
                    "Invalid actor timestamp",
                    retryable=False,
                ),
            ) from exc
        now = int(time.time())
        max_age = _get_actor_signature_max_age_seconds()
        if abs(now - actor_timestamp) > max_age:
            raise HTTPException(
                status_code=401,
                detail=error_response(
                    ErrorCode.UNAUTHORIZED,
                    "Actor signature timestamp expired",
                    retryable=False,
                ),
            )
        expected_signature = _sign_actor_identity(actor_id_header, actor_type, workspace_id, actor_timestamp_header)
        if not hmac.compare_digest(expected_signature, actor_signature_header):
            raise HTTPException(
                status_code=401,
                detail=error_response(
                    ErrorCode.UNAUTHORIZED,
                    "Invalid actor signature",
                    retryable=False,
                ),
            )
        return actor_id_header, actor_type

    actor_id = payload.get("actorId")
    actor_type = payload.get("actorType", "user")
    if not actor_id:
        raise HTTPException(
            status_code=422,
            detail=error_response(
                ErrorCode.INVALID_ARGUMENT,
                "Missing required field: actorId",
                retryable=False,
            ),
        )
    return actor_id, actor_type

class RateLimiter:
    """Rate limiter with Redis backend support and in-memory fallback."""

    def __init__(self, requests_per_minute: int = 60, per_tool_limits: dict[str, int] | None = None):
        self.requests_per_minute = requests_per_minute
        self.per_tool_limits = per_tool_limits or {}
        self.window_seconds = 60
        
        # Try to connect to Redis for multi-instance support
        self._redis: Optional[Any] = None
        self._use_redis = False
        redis_url = os.getenv("REDIS_URL")
        
        if redis_url:
            try:
                redis_module = importlib.import_module("redis")
                self._redis = redis_module.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_timeout=1.0,
                )
                self._redis.ping()  # Test connection
                self._use_redis = True
                _log.info("Rate limiter using Redis backend: %s", redis_url.split("@")[-1])
            except ImportError:
                _log.warning("REDIS_URL set but redis package not installed (pip install redis)")
            except Exception as exc:
                _log.warning("Redis connection failed, falling back to in-memory: %s", exc)
        
        # In-memory fallback (single-instance only)
        if not self._use_redis:
            _log.info("Rate limiter using in-memory backend (single-instance only)")
        
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._tool_requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key_hash: str, tool_name: str | None = None) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, remaining)."""
        if self._use_redis:
            return self._is_allowed_redis(key_hash, tool_name)
        else:
            return self._is_allowed_memory(key_hash, tool_name)
    
    def _is_allowed_redis(self, key_hash: str, tool_name: str | None) -> tuple[bool, int]:
        """Redis-backed rate limiting with atomic operations."""
        now = time.time()
        window_start = now - self.window_seconds
        
        # Global key limit
        global_key = f"rl:global:{key_hash}"
        try:
            # Use sorted set with scores as timestamps
            pipe = self._redis.pipeline()
            # Remove old entries
            pipe.zremrangebyscore(global_key, 0, window_start)
            # Count current requests
            pipe.zcard(global_key)
            # Add current request timestamp
            pipe.zadd(global_key, {str(now): now})
            # Set expiration
            pipe.expire(global_key, self.window_seconds + 10)
            
            _, current_count, _, _ = pipe.execute()
            
            if current_count >= self.requests_per_minute:
                return False, 0
            
            # Tool-specific limit
            if tool_name:
                tool_limit = self.per_tool_limits.get(tool_name, self.requests_per_minute)
                tool_key = f"rl:tool:{key_hash}:{tool_name}"
                
                pipe = self._redis.pipeline()
                pipe.zremrangebyscore(tool_key, 0, window_start)
                pipe.zcard(tool_key)
                pipe.zadd(tool_key, {str(now): now})
                pipe.expire(tool_key, self.window_seconds + 10)
                
                _, tool_count, _, _ = pipe.execute()
                
                if tool_count >= tool_limit:
                    return False, 0
            
            remaining = self.requests_per_minute - current_count - 1
            return True, remaining
            
        except Exception as exc:
            _log.error("Redis rate limit check failed, allowing request: %s", exc)
            # Fail open on Redis errors
            return True, self.requests_per_minute
    
    def _is_allowed_memory(self, key_hash: str, tool_name: str | None) -> tuple[bool, int]:
        """In-memory rate limiting (single-instance only)."""
        now = time.time()
        with self._lock:
            # Clean old timestamps outside window
            self._requests[key_hash] = [
                ts for ts in self._requests[key_hash]
                if now - ts < self.window_seconds
            ]

            current_count = len(self._requests[key_hash])

            if current_count >= self.requests_per_minute:
                return False, 0

            if tool_name:
                tool_limit = self.per_tool_limits.get(tool_name, self.requests_per_minute)
                tool_key = f"{key_hash}:{tool_name}"
                self._tool_requests[tool_key] = [
                    ts for ts in self._tool_requests[tool_key]
                    if now - ts < self.window_seconds
                ]
                tool_count = len(self._tool_requests[tool_key])
                if tool_count >= tool_limit:
                    return False, 0
                self._tool_requests[tool_key].append(now)

            self._requests[key_hash].append(now)
            remaining = self.requests_per_minute - current_count - 1
            return True, remaining


_per_tool_limits = {
    "policy.check": 30,
    "risk.score": 60,
    "audit.log": 120,
    "workflow.dispatch": 30,
    "approval.request": 30,
    "resource.list": 120,
    "resource.get": 120,
    "rag.retrieve": 120,
    "rag.ingest_source": 20,
    "rag.ingest_chunks": 20,
}

_rate_limiter = RateLimiter(requests_per_minute=60, per_tool_limits=_per_tool_limits)

_required_vars = ["NOTION_TOKEN", "GOVERNANCE_DB_ID", "AUDIT_DB_ID", "WORKFLOW_DB_ID", "APPROVAL_DB_ID"]
_missing_vars = [v for v in _required_vars if not os.getenv(v)]
if _missing_vars:
    _log_with_context("warning", "Missing required env vars: %s — Notion API calls will fail", ", ".join(_missing_vars))

notion = notion_client.Client(auth=os.getenv("NOTION_TOKEN"))

def _clean_db_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("?")[0]

GOVERNANCE_DB_ID = _clean_db_id(os.getenv("GOVERNANCE_DB_ID"))
AUDIT_DB_ID = _clean_db_id(os.getenv("AUDIT_DB_ID"))
WORKFLOW_DB_ID = _clean_db_id(os.getenv("WORKFLOW_DB_ID"))
APPROVAL_DB_ID = _clean_db_id(os.getenv("APPROVAL_DB_ID"))

# -----------------------------
# Helper functions
# -----------------------------

def _notion_retry_sleep(attempt: int) -> None:
    """Sleep with exponential backoff, but respect request time budget."""
    delay = min(2.0, 0.5 * (2 ** attempt))
    
    # Check if we have enough time remaining to retry
    remaining = _get_remaining_time()
    if remaining is not None: # Within request context, check budget
        # Reserve at least 2s for the actual retry attempt
        min_remaining = 2.0
        if remaining < min_remaining:
            raise TimeoutError(f"Insufficient time to retry (only {remaining:.1f}s remaining)")
        # Also cap the sleep to not exceed remaining budget
        delay = min(delay, remaining - min_remaining)
    
    time.sleep(delay)

def _should_skip_notion_api() -> bool:
    """Return True when live Notion writes should be suppressed for tests."""
    return os.getenv("SKIP_NOTION_API") == "1"


def _collect_startup_safety_issues() -> list[str]:
    issues: list[str] = []
    missing_required = [v for v in _required_vars if not os.getenv(v)]
    if _strict_production_mode() and missing_required:
        issues.append(f"Missing required env vars: {', '.join(missing_required)}")
    if _strict_production_mode() and _debug_enabled():
        issues.append("DEBUG must be disabled when STRICT_PRODUCTION_MODE=1")
    if _strict_production_mode() and _env_enabled("ALLOW_DEBUG_TRACEBACKS"):
        issues.append("ALLOW_DEBUG_TRACEBACKS must be disabled when STRICT_PRODUCTION_MODE=1")
    if _strict_production_mode() and _should_skip_notion_api():
        issues.append("SKIP_NOTION_API must be disabled when STRICT_PRODUCTION_MODE=1")

    rag_db_url = os.getenv("RAG_DATABASE_URL", "")
    if rag_db_url and "CHANGE_ME_IN_PRODUCTION" in rag_db_url:
        issues.append("RAG_DATABASE_URL still contains the default mcp_app password")
    if os.getenv("RAG_API_KEYS") and not os.getenv("RAG_SERVER_SECRET"):
        issues.append("RAG_SERVER_SECRET is required when RAG_API_KEYS is configured")
    if _strict_production_mode() and rag_db_url and not _get_actor_signing_secret():
        issues.append("ACTOR_SIGNING_SECRET is required for stateless resource authorization in strict production mode")
    return issues


def _enforce_startup_safety() -> None:
    issues = _collect_startup_safety_issues()
    if not issues:
        return
    for issue in issues:
        _log.error("Startup safety check failed: %s", issue)
    if _strict_production_mode():
        raise RuntimeError("Strict production startup checks failed")
    _log.warning("Continuing startup outside strict production mode despite safety issues")


_enforce_startup_safety()

def _mock_notion_page(parent: dict, properties: dict) -> dict:
    """Return a synthetic Notion-like page payload for dry-run test flows."""
    import uuid

    return {
        "id": str(uuid.uuid4()),
        "object": "page",
        "parent": parent,
        "properties": properties,
        "mock": True,
    }

def _notion_pages_create(parent: dict, properties: dict, retries: int = 3):
    """Create Notion page with retry logic that respects time budget."""
    if not parent.get("database_id"):
        raise RuntimeError("Missing Notion database_id for pages.create")
    if _should_skip_notion_api():
        return _mock_notion_page(parent, properties)
    last_exc = None
    for attempt in range(retries):
        try:
            return notion.pages.create(parent=parent, properties=properties)
        except TimeoutError:
            # Re-raise timeout errors immediately (don't retry if we're out of time)
            raise
        except APIResponseError as exc:
            last_exc = exc
            status = getattr(exc, "status", None)
            if status in {429, 500, 502, 503, 504} and attempt < retries - 1:
                _notion_retry_sleep(attempt)
                continue
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                _notion_retry_sleep(attempt)
                continue
            raise
    if last_exc:
        raise last_exc

def _validate_notion_database(db_id: str, name: str) -> str | None:
    import httpx

    token = os.getenv("NOTION_TOKEN")
    if not token:
        return "NOTION_TOKEN missing"
    if not db_id:
        return f"{name} is missing"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.get(
            f"https://api.notion.com/v1/databases/{db_id}",
            headers=headers,
            timeout=_NOTION_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            return f"{name} invalid or not a database (HTTP {resp.status_code})"
    except Exception as exc:
        return f"{name} validation failed: {exc}"
    return None

def validate_notion_db_ids() -> None:
    if _should_skip_notion_api():
        return
    strict = os.getenv("NOTION_VALIDATE_DB_IDS_STRICT") == "1"
    errors = []
    for name, db_id in (
        ("GOVERNANCE_DB_ID", GOVERNANCE_DB_ID),
        ("AUDIT_DB_ID", AUDIT_DB_ID),
        ("WORKFLOW_DB_ID", WORKFLOW_DB_ID),
        ("APPROVAL_DB_ID", APPROVAL_DB_ID),
    ):
        error = _validate_notion_database(db_id, name)
        if error:
            errors.append(error)
    if errors:
        for error in errors:
            _log_with_context("error", "Notion DB validation: %s", error)
        if strict:
            raise RuntimeError("Notion DB validation failed; set correct DB IDs")

validate_notion_db_ids()

def create_audit_entry(
    actor,
    action,
    input_data,
    output=None,
    policy=None,
    risk=None,
    outcome="success",
    reason_codes=None,
    proof_hash=None,
    request_id=None,
    policy_version=None,
    target=None,
    error_class=None
):
    """
    Create audit-grade entry in Audit DB.
    
    REQUIRED fields (always set):
    - Event (title): human-readable summary
    - Timestamp (date): explicit UTC event time
    - Request ID (text): correlation key across workflow/approval/audit
    - Actor (text): who performed the action
    - Action (text): what operation was performed
    - Outcome (select): success | deny | error
    - Proof hash (text): evidence chain hash
    - Reason codes (text): REQUIRED for deny/error, optional for success
    
    RECOMMENDED fields:
    - Policy version (text): set when policy decision involved
    - Target (text): what was being acted on
    
    Outcome rules:
    - success: reason_codes optional, policy_version recommended if policy evaluated
    - deny: reason_codes REQUIRED, policy_version REQUIRED
    - error: reason_codes REQUIRED, policy_version optional
    """
    import hashlib
    import json
    import uuid
    from datetime import datetime, timezone
    
    # Current UTC timestamp (explicit, not relying on Notion auto-creation)
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Generate Request ID if not provided (per-request correlation)
    if request_id is None:
        request_id = str(uuid.uuid4())
    
    # Generate proof hash if not provided
    if proof_hash is None:
        hash_input = f"{request_id}:{actor}:{action}:{timestamp}"
        proof_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    # Validate outcome-specific requirements
    if outcome == "deny":
        if not reason_codes:
            reason_codes = "DENY_REASON_MISSING"  # Fail-safe
        if not policy_version:
            policy_version = "unknown"  # Fail-safe, but should be provided
    elif outcome == "error":
        if not reason_codes:
            reason_codes = "ERROR_REASON_MISSING"  # Fail-safe
        # Add error class if provided
        if error_class:
            reason_codes = f"{reason_codes} | error_class:{error_class}"
    
    # Build audit entry properties
    # Event title: "{action} — {outcome} — {target}" (more readable)
    event_parts = [action, outcome]
    if target:
        event_parts.append(target)
    event_title = " — ".join(event_parts)
    
    properties = {
        "Event": {"title": [{"text": {"content": event_title}}]},
        "Timestamp": {"date": {"start": timestamp}},
        "Request ID": {"rich_text": [{"text": {"content": request_id}}]},
        "Actor": {"rich_text": [{"text": {"content": actor}}]},
        "Action": {"rich_text": [{"text": {"content": action}}]},
        "Outcome": {"select": {"name": outcome}},
        "Proof hash": {"rich_text": [{"text": {"content": proof_hash}}]},
    }
    
    # Add reason codes (required for deny/error)
    if reason_codes:
        properties["Reason codes"] = {"rich_text": [{"text": {"content": reason_codes}}]}
    
    # Add policy version when policy decision involved
    if policy_version:
        properties["Policy version"] = {"rich_text": [{"text": {"content": policy_version}}]}
    elif policy:  # Legacy: derive from policy name if version not provided
        properties["Policy version"] = {"rich_text": [{"text": {"content": f"policy:{policy}"}}]}
    
    # Add target if specified
    if target:
        properties["Target"] = {"rich_text": [{"text": {"content": target}}]}

    if _should_skip_notion_api():
        return

    if not AUDIT_DB_ID:
        _log_with_context("error", "AUDIT_DB_ID missing; audit entry not written")
        return

    _notion_pages_create(
        parent={"database_id": AUDIT_DB_ID},
        properties=properties,
    )

def fetch_policies():
    """Fetch policies from Governance DB using direct HTTP API (notion-client lacks .query method)."""
    import httpx

    if not GOVERNANCE_DB_ID:
        raise RuntimeError("GOVERNANCE_DB_ID missing")
    if not os.getenv("NOTION_TOKEN"):
        raise RuntimeError("NOTION_TOKEN missing")

    headers = {
        "Authorization": f"Bearer {os.getenv('NOTION_TOKEN')}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    last_exc = None
    for attempt in range(3):
        try:
            response = httpx.post(
                f"https://api.notion.com/v1/databases/{GOVERNANCE_DB_ID}/query",
                headers=headers,
                json={},
                timeout=_NOTION_HTTP_TIMEOUT,
            )
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                _notion_retry_sleep(attempt)
                continue
            raise RuntimeError(f"Governance DB query failed: {exc}")
    if last_exc:
        raise last_exc

def compute_risk_score(category=None, amount=None, priority=None):
    score = 0
    if category == "finance":
        score += 40
    if category == "maintenance":
        score += 20
    if priority == "high":
        score += 30
    if amount and amount > 1000:
        score += 30
    return min(score, 100)

# -----------------------------
# MCP Tools
# -----------------------------

policy_check = Tool(
    name="policy.check",
    description="Check governance policies for an action.",
    inputSchema={
        "type": "object",
        "properties": {
            "actor": {"type": "string"},
            "action": {"type": "string"},
            "context": {"type": "object"}
        },
        "required": ["actor", "action"]
    }
)

def handle_policy_check(payload):
    actor = payload["actor"]
    action = payload["action"]
    context = payload.get("context", {})
    request_id = payload.get("_request_id")  # Injected by entrypoint

    try:
        policies = fetch_policies()
    except Exception as exc:
        _log_with_context("error", "Policy fetch failed: %s", exc)
        create_audit_entry(
            actor=actor,
            action="policy.check",
            input_data={"action": action, "context": context},
            outcome="error",
            reason_codes="NOTION_QUERY_FAILED",
            request_id=request_id,
            target=action,
            error_class=type(exc).__name__,
        )
        return {"error": "Policy query failed", "requestId": request_id}

    create_audit_entry(
        actor=actor,
        action="policy.check",
        input_data={"action": action, "context": context},
        policy=f"{len(policies)} policies matched",
        request_id=request_id,
        target=action,  # The action being checked is the target
    )

    return {"matchedPolicies": len(policies), "requestId": request_id}

risk_score = Tool(
    name="risk.score",
    description="Compute a risk score (0–100).",
    inputSchema={
        "type": "object",
        "properties": {
            "actor": {"type": "string"},
            "category": {"type": "string"},
            "amount": {"type": "number"},
            "priority": {"type": "string"}
        },
        "required": ["actor"]
    }
)

def handle_risk_score(payload):
    actor = payload["actor"]
    category = payload.get("category")
    amount = payload.get("amount")
    priority = payload.get("priority")
    request_id = payload.get("_request_id")  # Injected by entrypoint

    score = compute_risk_score(category, amount, priority)

    create_audit_entry(
        actor=actor,
        action="risk.score",
        input_data=payload,
        risk=score,
        request_id=request_id,
        target=f"{category}:{amount}" if category and amount else category or "score",
    )

    return {"riskScore": score, "requestId": request_id}

audit_log = Tool(
    name="audit.log",
    description="Write an audit log entry.",
    inputSchema={
        "type": "object",
        "properties": {
            "actor": {"type": "string"},
            "action": {"type": "string"},
            "input": {"type": "object"},
            "output": {"type": "object"},
            "policyApplied": {"type": "string"},
            "riskScore": {"type": "number"}
        },
        "required": ["actor", "action", "input"]
    }
)

def handle_audit_log(payload):
    """
    Handle explicit audit log entries with DENY/ERROR detection.
    Sets outcome based on:
    - output.denied=true OR policyApplied → deny
    - output.error=true OR exception → error
    - otherwise → success
    """
    output = payload.get("output", {})
    policy = payload.get("policyApplied")
    
    # Detect outcome
    is_error = output.get("error", False)
    is_denied = output.get("denied", False) or policy is not None
    
    if is_error:
        outcome = "error"
        reason_codes = output.get("reason", "ERROR_UNSPECIFIED")
        error_class = output.get("errorClass")
    elif is_denied:
        outcome = "deny"
        reason_codes = output.get("reason") or f"POLICY_VIOLATION: {policy}" if policy else "DENY_UNSPECIFIED"
    else:
        outcome = "success"
        reason_codes = None
    
    create_audit_entry(
        actor=payload["actor"],
        action=payload["action"],
        input_data=payload["input"],
        output=output,
        policy=policy,
        risk=payload.get("riskScore"),
        outcome=outcome,
        reason_codes=reason_codes,
        request_id=payload.get("requestId"),
        policy_version=payload.get("policyVersion"),
        target=payload.get("target"),
        error_class=error_class if is_error else None,
    )

    return {"status": "logged", "outcome": outcome, "requestId": payload.get("requestId")}

workflow_dispatch = Tool(
    name="workflow.dispatch",
    description="Create a workflow task in Notion.",
    inputSchema={
        "type": "object",
        "properties": {
            "actor": {"type": "string"},
            "type": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "priority": {"type": "string"},
            "metadata": {"type": "object"}
        },
        "required": ["actor", "type", "title"]
    }
)

def handle_workflow_dispatch(payload):
    request_id = payload.get("_request_id")  # Injected by entrypoint
    
    # Create workflow DB entry with Request ID (root record for the run)
    properties = {
        "Name": {"title": [{"text": {"content": payload["title"]}}]},
        "Type": {"rich_text": [{"text": {"content": payload["type"]}}]},
        "Priority": {"rich_text": [{"text": {"content": payload.get("priority", "")}}]},
    }
    
    # Add Request ID to workflow DB (correlation key)
    if request_id:
        properties["Request ID"] = {"rich_text": [{"text": {"content": request_id}}]}
    
    try:
        page = _notion_pages_create(
            parent={"database_id": WORKFLOW_DB_ID},
            properties=properties,
        )
    except Exception as exc:
        _log_with_context("error", "Workflow dispatch failed: %s", exc)
        return {"error": "Workflow dispatch failed", "requestId": request_id}

    create_audit_entry(
        actor=payload["actor"],
        action="workflow.dispatch",
        input_data=payload,
        request_id=request_id,
        target=f"workflow:{payload['title']}",
    )

    return {"status": "created", "pageId": page["id"], "requestId": request_id}

approval_request = Tool(
    name="approval.request",
    description="Create a human approval request.",
    inputSchema={
        "type": "object",
        "properties": {
            "actor": {"type": "string"},
            "subject": {"type": "string"},
            "reason": {"type": "string"},
            "riskScore": {"type": "number"},
            "relatedWorkflowId": {"type": "string"}
        },
        "required": ["actor", "subject", "reason"]
    }
)

def handle_approval_request(payload):
    request_id = payload.get("_request_id")  # Injected by entrypoint
    
    properties = {
        "Name": {"title": [{"text": {"content": payload["subject"]}}]},
        "Reason": {"rich_text": [{"text": {"content": payload["reason"]}}]},
        "RelatedWorkflow": {"rich_text": [{"text": {"content": payload.get("relatedWorkflowId", "")}}]},
        "Status": {"rich_text": [{"text": {"content": "Pending"}}]},
    }
    if payload.get("riskScore") is not None:
        properties["Risk"] = {"number": payload["riskScore"]}
    
    # Add Request ID to approval DB (correlation key)
    if request_id:
        properties["Request ID"] = {"rich_text": [{"text": {"content": request_id}}]}
    
    try:
        page = _notion_pages_create(
            parent={"database_id": APPROVAL_DB_ID},
            properties=properties,
        )
    except Exception as exc:
        _log_with_context("error", "Approval request failed: %s", exc)
        return {"error": "Approval request failed", "requestId": request_id}

    create_audit_entry(
        actor=payload["actor"],
        action="approval.request",
        input_data=payload,
        risk=payload.get("riskScore"),
        request_id=request_id,
        target=f"approval:{payload['subject']}",
    )

    return {"status": "requested", "approvalId": page["id"], "requestId": request_id}


# -----------------------------
# RAG Tools (governance-first retrieval)
# Architecture locked: rag_sources = governance truth, rag_chunks = storage only.
# Per-child access via rag_source_access — never add governance columns to chunks.
# -----------------------------

rag_retrieve = Tool(
    name="rag.retrieve",
    description=(
        "Governance-first vector retrieval. "
        "Filters at source level (workspace_id, status, effective window, legal hold) "
        "before ranking chunks by cosine similarity. "
        "Optionally scope to a specific child via child_id (uses rag_source_access). "
        "workspace_id is resolved from your API key — do not pass it in the request body."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query_embedding": {"type": "array", "items": {"type": "number"}},
            "top_k":           {"type": "integer", "default": 10},
            "child_id":        {"type": "string"},
            "actorId":         {"type": "string"},
            "actorType":       {"type": "string", "default": "user"},
            "requestId":       {"type": "string"}
        },
        "required": ["query_embedding"]
    },
)

rag_ingest_source = Tool(
    name="rag.ingest_source",
    description=(
        "Create a RAG governance source record. "
        "All governance metadata (status, visibility, effective_from/to, "
        "legal_hold, retention_class) lives here — not in chunks. "
        "workspace_id is resolved from your API key — do not pass it in the request body."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "name":           {"type": "string"},
            "status":         {"type": "string", "enum": ["draft", "published", "archived"], "default": "draft"},
            "visibility":     {"type": "string", "enum": ["private", "workspace", "public"], "default": "private"},
            "effective_from": {"type": "string", "format": "date-time"},
            "effective_to":   {"type": "string", "format": "date-time"},
            "legal_hold":     {"type": "boolean", "default": False},
            "retention_class":{"type": "string"}
        },
        "required": ["name"]
    },
)

rag_ingest_chunks = Tool(
    name="rag.ingest_chunks",
    description=(
        "Insert content chunks (with embeddings) for an existing governance source. "
        "Chunks are storage-only: content, embedding, position, token_count. "
        "Do not add governance fields here — they belong in rag_sources."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "chunks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content":     {"type": "string"},
                        "embedding":   {"type": "array", "items": {"type": "number"}},
                        "position":    {"type": "integer"},
                        "token_count": {"type": "integer"}
                    },
                    "required": ["content", "embedding"]
                }
            }
        },
        "required": ["source_id", "chunks"]
    },
)

resource_list = Tool(
    name="resource.list",
    description=(
        "List resources the caller is authorized to access via the secure SQL view. "
        "This is a standalone, stateless read surface: actor identity is supplied per request, "
        "authorization is enforced in SQL, and only curated resource fields are returned."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "actorId": {"type": "string"},
            "actorType": {"type": "string", "default": "user"},
            "memberId": {"type": "string"},
            "resourceType": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
            "requestId": {"type": "string"}
        },
    },
)

resource_get = Tool(
    name="resource.get",
    description=(
        "Get one resource the caller is authorized to access via the secure SQL view. "
        "This is a standalone, stateless read surface: actor identity is supplied per request, "
        "authorization is enforced in SQL, and absent or unauthorized resources return null."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "actorId": {"type": "string"},
            "actorType": {"type": "string", "default": "user"},
            "resourceId": {"type": "string"},
            "requestId": {"type": "string"}
        },
        "required": ["resourceId"],
    },
)


def _rag_unavailable(reason: str) -> dict:
    return error_response(ErrorCode.DEPENDENCY_FAILURE, _rag_unavailable_message(reason), retryable=False)


def handle_resource_list(payload, workspace_id: str):
    try:
        import rag
    except ImportError as exc:
        return _rag_unavailable(str(exc))

    try:
        results = rag.list_authorized_resources(
            workspace_id=workspace_id,
            actor_id=payload["actorId"],
            actor_type=payload.get("actorType", "user"),
            member_id=payload.get("memberId"),
            resource_type=payload.get("resourceType"),
            limit=payload.get("limit", 50),
            request_id=payload.get("requestId") or payload.get("_request_id"),
        )
        return {"resources": results}
    except (RuntimeError, ValueError) as exc:
        return _rag_unavailable(str(exc))
    except TimeoutError:
        return error_response(ErrorCode.TIMEOUT, "resource.list timed out", retryable=True)
    except Exception:
        _log_with_context("exception", "resource.list failed")
        return error_response(ErrorCode.INTERNAL_ERROR, _client_internal_error("resource.list"), retryable=False)


def handle_resource_get(payload, workspace_id: str):
    try:
        import rag
    except ImportError as exc:
        return _rag_unavailable(str(exc))

    resource_id = payload.get("resourceId")
    if not resource_id:
        return error_response(ErrorCode.INVALID_ARGUMENT, "Missing required field: resourceId", retryable=False)

    try:
        result = rag.get_authorized_resource(
            workspace_id=workspace_id,
            actor_id=payload["actorId"],
            actor_type=payload.get("actorType", "user"),
            resource_id=resource_id,
            request_id=payload.get("requestId") or payload.get("_request_id"),
        )
        return {"resource": result}
    except (RuntimeError, ValueError) as exc:
        return _rag_unavailable(str(exc))
    except TimeoutError:
        return error_response(ErrorCode.TIMEOUT, "resource.get timed out", retryable=True)
    except Exception:
        _log_with_context("exception", "resource.get failed")
        return error_response(ErrorCode.INTERNAL_ERROR, _client_internal_error("resource.get"), retryable=False)


def handle_rag_retrieve(payload, workspace_id: str):
    import asyncio
    try:
        import rag
    except ImportError as exc:
        return _rag_unavailable(str(exc))
    
    # Validate required inputs
    if "query_embedding" not in payload:
        return error_response(ErrorCode.INVALID_ARGUMENT, "Missing required field: query_embedding")
    
    query_embedding = payload["query_embedding"]
    
    if not isinstance(query_embedding, list):
        return error_response(ErrorCode.INVALID_ARGUMENT, "query_embedding must be a list of numbers")
    
    if len(query_embedding) == 0:
        return error_response(ErrorCode.INVALID_ARGUMENT, "query_embedding cannot be empty")
    
    try:
        results = rag.retrieve(
            workspace_id=workspace_id,
            query_embedding=query_embedding,
            top_k=payload.get("top_k", 10),
            child_id=payload.get("child_id"),
            actor_id=payload.get("actorId"),
            actor_type=payload.get("actorType"),
            request_id=payload.get("requestId") or payload.get("_request_id"),
        )
        return {"results": results}
    except (RuntimeError, ValueError) as exc:
        return _rag_unavailable(str(exc))
    except TimeoutError:
        return error_response(ErrorCode.TIMEOUT, "RAG retrieve timed out", retryable=True)
    except Exception:
        _log_with_context("exception", "RAG retrieve failed")
        return error_response(ErrorCode.INTERNAL_ERROR, _client_internal_error("RAG retrieve"), retryable=False)


def handle_rag_ingest_source(payload, workspace_id: str):
    try:
        import rag
    except ImportError as exc:
        return _rag_unavailable(str(exc))
    try:
        source_id = rag.ingest_source(
            workspace_id=workspace_id,
            name=payload["name"],
            status=payload.get("status", "draft"),
            visibility=payload.get("visibility", "private"),
            effective_from=payload.get("effective_from"),
            effective_to=payload.get("effective_to"),
            legal_hold=payload.get("legal_hold", False),
            retention_class=payload.get("retention_class"),
        )
        return {"source_id": source_id}
    except (RuntimeError, ValueError) as exc:
        return _rag_unavailable(str(exc))
    except TimeoutError:
        return error_response(ErrorCode.TIMEOUT, "RAG ingest_source timed out", retryable=True)
    except Exception:
        _log_with_context("exception", "RAG ingest_source failed")
        return error_response(ErrorCode.INTERNAL_ERROR, _client_internal_error("RAG ingest_source"), retryable=False)


def handle_rag_ingest_chunks(payload, workspace_id: str):
    try:
        import rag
    except ImportError as exc:
        return _rag_unavailable(str(exc))
    
    # Early validation: chunk count limit
    chunks = payload.get("chunks", [])
    if len(chunks) > _MAX_CHUNKS_PER_REQUEST:
        return error_response(
            ErrorCode.INVALID_ARGUMENT,
            f"Too many chunks (max {_MAX_CHUNKS_PER_REQUEST}, got {len(chunks)})",
            retryable=False
        )
    
    try:
        count = rag.ingest_chunks(
            source_id=payload["source_id"],
            chunks=chunks,
            workspace_id=workspace_id,
        )
        return {"ingested": count}
    except (RuntimeError, ValueError) as exc:
        return _rag_unavailable(str(exc))
    except TimeoutError:
        return error_response(ErrorCode.TIMEOUT, "RAG ingest_chunks timed out", retryable=True)
    except Exception:
        _log_with_context("exception", "RAG ingest_chunks failed")
        return error_response(ErrorCode.INTERNAL_ERROR, _client_internal_error("RAG ingest_chunks"), retryable=False)



# ============================================================================
# MCP Server Setup
# ============================================================================

server = Server("notion-governance-mcp", "0.1.0")

# Contextvar to propagate MCP API key from ASGI handler to tool handlers
_mcp_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_api_key", default=None)

# ============================================================================
# MCP Server Handlers (low-level API for StreamableHTTPSessionManager)
# ============================================================================

@server.list_tools()
async def list_tools_handler() -> list[Tool]:
    """Return all tools for MCP protocol."""
    return [
        policy_check,
        risk_score,
        audit_log,
        workflow_dispatch,
        approval_request,
        resource_list,
        resource_get,
        rag_retrieve,
        rag_ingest_source,
        rag_ingest_chunks,
    ]

@server.call_tool(validate_input=True)
async def call_tool_handler(name: str, arguments: dict) -> list[TextContent]:
    """Route tool calls to appropriate handlers with workspace_id from contextvar."""
    import uuid
    
    _RAG_TOOLS = {"resource.list", "resource.get", "rag.retrieve", "rag.ingest_source", "rag.ingest_chunks"}
    
    # Enforce rate limiting for MCP calls using API key
    api_key = _mcp_api_key.get()
    if not api_key:
        return [TextContent(type="text", text='{"error": "Authentication required: X-API-Key header missing"}')]
    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    allowed, _remaining = _rate_limiter.is_allowed(key_hash, name)
    if not allowed:
        return [TextContent(type="text", text='{"error": "Rate limit exceeded"}')]

    # Generate request_id once per user request (Option B: per workflow)
    # Accept requestId from client if provided (for cross-call correlation)
    request_id = arguments.get("requestId") or arguments.get("_request_id") or str(uuid.uuid4())
    arguments["_request_id"] = request_id  # Inject into payload
    
    # Governance tools (no workspace_id needed in handler signature)
    governance_handlers = {
        "policy.check":      handle_policy_check,
        "risk.score":        handle_risk_score,
        "audit.log":         handle_audit_log,
        "workflow.dispatch": handle_workflow_dispatch,
        "approval.request":  handle_approval_request,
    }
    
    # RAG tools (require workspace_id)
    rag_handlers = {
        "resource.list":      handle_resource_list,
        "resource.get":       handle_resource_get,
        "rag.retrieve":      handle_rag_retrieve,
        "rag.ingest_source": handle_rag_ingest_source,
        "rag.ingest_chunks": handle_rag_ingest_chunks,
    }
    
    try:
        if name in governance_handlers:
            result = governance_handlers[name](arguments)
            return [TextContent(type="text", text=str(result))]
        
        elif name in rag_handlers:
            # Extract workspace_id from contextvar (set by ASGI handler)
            workspace_id = resolve_workspace_id(api_key)
            if name in {"resource.list", "resource.get", "rag.retrieve"} and (
                name in {"resource.list", "resource.get"}
                or _get_actor_signing_secret()
                or arguments.get("actorId") is not None
            ):
                actor_id, actor_type = _resolve_actor_identity(
                    arguments,
                    workspace_id,
                    actor_id_header=_mcp_actor_id.get(),
                    actor_type_header=_mcp_actor_type.get(),
                    actor_signature_header=_mcp_actor_signature.get(),
                    actor_timestamp_header=_mcp_actor_timestamp.get(),
                )
                arguments["actorId"] = actor_id
                arguments["actorType"] = actor_type
            result = rag_handlers[name](arguments, workspace_id)
            return [TextContent(type="text", text=str(result))]
        
        else:
            return [TextContent(type="text", text=f'{{"error": "Tool not found: {name}"}}')]
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            return [TextContent(type="text", text=str(detail))]
        return [TextContent(type="text", text=f'{{"error": "{detail}"}}')]
    
    except KeyError as exc:
        return [TextContent(type="text", text=f'{{"error": "Missing required field: {exc}"}}')]
    except Exception:
        _log_with_context("exception", "Tool %s failed", name)
        return [TextContent(type="text", text='{"error": "Internal server error"}')]


# ============================================================================
# MCP Streamable HTTP Transport
# ============================================================================

mcp_session_manager = StreamableHTTPSessionManager(server)

# ============================================================================
# FastAPI App (exposed at module level for uvicorn)
# ============================================================================

from fastapi import FastAPI, HTTPException, Header, Depends
import uvicorn

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Start MCP session manager on app startup."""
    async with mcp_session_manager.run():
        _log.info("MCP session manager started")
        yield
    _log.info("MCP session manager stopped")

app = FastAPI(lifespan=_lifespan)

# ============================================================================
# Timeout Middleware (Application-level 15s request timeout)
# ============================================================================

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse
import asyncio

class TimeoutMiddleware(BaseHTTPMiddleware):
    """Enforce REQUEST_TIMEOUT_SECONDS on all async endpoints."""
    
    async def dispatch(self, request: Request, call_next):
        try:
            return await asyncio.wait_for(
                call_next(request),
                timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            _log_with_context("warning", "Request timeout: %s %s", request.method, request.url.path)
            return StarletteJSONResponse(
                status_code=504,
                content=error_response(
                    ErrorCode.TIMEOUT,
                    f"Request exceeded {_REQUEST_TIMEOUT_SECONDS}s timeout",
                    retryable=True
                )
            )

app.add_middleware(TimeoutMiddleware)

# ============================================================================
# Request Body Size Middleware (prevent memory spikes from large payloads)
# ============================================================================

from fastapi import Request
from starlette.requests import ClientDisconnect

@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    """Reject requests with bodies larger than MAX_REQUEST_BODY_SIZE.
    
    Uses body caching pattern to avoid consuming the stream before size check.
    """
    if request.method in {"POST", "PUT", "PATCH"}:
        # Read and cache body for size validation
        body = await request.body()
        
        if len(body) > _MAX_REQUEST_BODY_SIZE:
            _log_with_context(
                "warning",
                "Request body too large: %s bytes (max %s)",
                len(body),
                _MAX_REQUEST_BODY_SIZE
            )
            return StarletteJSONResponse(
                status_code=413,
                content=error_response(
                    ErrorCode.INVALID_ARGUMENT,
                    f"Request body too large (max {_MAX_REQUEST_BODY_SIZE} bytes)",
                    retryable=False
                )
            )
        
        # Body is already cached by Starlette after first read
        # Downstream handlers can call request.body() and get the cached value
    
    return await call_next(request)

# ============================================================================
# Endpoints
# ============================================================================

if True:  # Indentation wrapper for minimal diff
    
    # ========================================================================
    # Root & Health & OAuth Endpoints
    # ========================================================================
    
    @app.get("/")
    def root():
        return {
            "service": "Notion MCP Governance Server",
            "version": "1.4",
            "status": "running",
            "endpoints": {
                "health": "/health",
                "mcp": "/mcp",
                "oauth": {
                    "start": "/oauth/start",
                    "callback": "/oauth/callback"
                },
                "tools": {
                    "governance": "/call_tool/{tool_name}",
                    "rag": "/rag_tool/{tool_name}"
                }
            },
            "docs": "See README.md for API documentation"
        }
    
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/oauth/start")
    def oauth_start():
        """Return a Notion OAuth authorization URL for the user to visit."""
        client_id = os.getenv("NOTION_OAUTH_CLIENT_ID")
        redirect_uri = os.getenv("NOTION_OAUTH_REDIRECT_URI")
        if not client_id or not redirect_uri:
            return {"error": "NOTION_OAUTH_CLIENT_ID and NOTION_OAUTH_REDIRECT_URI must be set in .env to start OAuth."}
        auth_url = (
            f"https://api.notion.com/v1/oauth/authorize?owner=user&client_id={client_id}"
            f"&redirect_uri={redirect_uri}&response_type=code"
        )
        return {"auth_url": auth_url}

    @app.get("/oauth/callback")
    async def oauth_callback(code: str | None = None, state: str | None = None):
        """Handle Notion OAuth callback. If client credentials present, exchange the code for a token."""
        if not code:
            return {"error": "missing code"}
        client_id = os.getenv("NOTION_OAUTH_CLIENT_ID")
        client_secret = os.getenv("NOTION_OAUTH_CLIENT_SECRET")
        redirect_uri = os.getenv("NOTION_OAUTH_REDIRECT_URI")
        if not (client_id and client_secret and redirect_uri):
            return {"code": code, "note": "client credentials not configured; return code to caller for manual exchange."}
        import httpx
        token_url = "https://api.notion.com/v1/oauth/token"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        try:
            async with httpx.AsyncClient(timeout=_NOTION_HTTP_TIMEOUT) as client:
                resp = await client.post(token_url, data=data)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502, detail=f"Notion token exchange failed: {exc.response.status_code}")
        except Exception:
            raise HTTPException(status_code=500, detail="Token exchange request failed")

    # ========================================================================
    # Rate Limiting
    # ========================================================================
    
    _RAG_TOOLS = {"resource.list", "resource.get", "rag.retrieve", "rag.ingest_source", "rag.ingest_chunks"}

    def check_rate_limit(tool_name: str, x_api_key: Optional[str] = Header(default=None)) -> str:
        """FastAPI dependency: rate limit + resolve workspace_id."""
        # First resolve workspace (validates key)
        workspace_id = resolve_workspace_id(x_api_key)
        
        # Then check rate limit
        import hashlib
        key_hash = hashlib.sha256((x_api_key or "").encode()).hexdigest()
        allowed, remaining = _rate_limiter.is_allowed(key_hash, tool_name)
        
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=error_response(
                    ErrorCode.RATE_LIMITED,
                    "Rate limit exceeded. Maximum 60 requests per minute per API key.",
                    retryable=True
                ),
                headers={"Retry-After": "60"},
            )
        
        return workspace_id

    # ========================================================================
    # Legacy HTTP Endpoints (for direct API access)
    # ========================================================================

    @app.post("/call_tool/{tool_name}")
    async def call_tool(
        tool_name: str,
        payload: dict,
        workspace_id: str = Depends(check_rate_limit),  # Rate limit + auth
    ):
        """Notion governance tools — workspace_id resolved from X-API-Key (not used, but authenticates caller)."""
        import uuid
        
        # Generate request_id once per user request (Option B: per workflow)
        # Accept requestId from client if provided (for cross-call correlation)
        request_id = payload.get("requestId") or payload.get("_request_id") or str(uuid.uuid4())
        payload["_request_id"] = request_id  # Inject into payload
        _request_id_var.set(request_id)  # Set in async context for structured logging
        _request_start_time_var.set(time.time())  # Track when request started for time budget
        
        handlers = {
            "policy.check":      handle_policy_check,
            "risk.score":        handle_risk_score,
            "audit.log":         handle_audit_log,
            "workflow.dispatch": handle_workflow_dispatch,
            "approval.request":  handle_approval_request,
        }
        if tool_name in _RAG_TOOLS:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Tool '{tool_name}' requires authentication. "
                    "Use POST /rag_tool/{tool_name} with X-API-Key header."
                ),
            )
        handler = handlers.get(tool_name)
        if handler is None:
            raise HTTPException(status_code=404, detail="tool not found")
        try:
            # Run sync handler in thread pool to avoid blocking event loop
            return await asyncio.to_thread(handler, payload)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"Missing required field: {exc}")
        except Exception:
            _log_with_context("exception", "Tool %s failed", tool_name)
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post("/rag_tool/{tool_name}")
    async def call_rag_tool(
        tool_name: str,
        payload: dict,
        request: Request,
        workspace_id: str = Depends(check_rate_limit),  # Rate limit + auth
    ):
        """RAG tools — workspace_id is resolved from X-API-Key, never from payload."""
        import uuid
        
        # Generate request_id for correlation
        request_id = payload.get("requestId") or payload.get("_request_id") or str(uuid.uuid4())
        _request_id_var.set(request_id)  # Set in async context for structured logging
        _request_start_time_var.set(time.time())  # Track when request started for time budget
        
        rag_handlers = {
            "resource.list":      handle_resource_list,
            "resource.get":       handle_resource_get,
            "rag.retrieve":      handle_rag_retrieve,
            "rag.ingest_source": handle_rag_ingest_source,
            "rag.ingest_chunks": handle_rag_ingest_chunks,
        }
        handler = rag_handlers.get(tool_name)
        if handler is None:
            raise HTTPException(status_code=404, detail="RAG tool not found")
        try:
            if tool_name in {"resource.list", "resource.get", "rag.retrieve"} and (
                tool_name in {"resource.list", "resource.get"}
                or _get_actor_signing_secret()
                or payload.get("actorId") is not None
            ):
                actor_id, actor_type = _resolve_actor_identity(
                    payload,
                    workspace_id,
                    actor_id_header=request.headers.get("X-Actor-Id"),
                    actor_type_header=request.headers.get("X-Actor-Type"),
                    actor_signature_header=request.headers.get("X-Actor-Signature"),
                    actor_timestamp_header=request.headers.get("X-Actor-Timestamp"),
                )
                payload["actorId"] = actor_id
                payload["actorType"] = actor_type
            # Apply concurrency limit for ingest operations
            if tool_name == "rag.ingest_chunks":
                async with _ingest_semaphore:
                    return await asyncio.to_thread(handler, payload, workspace_id)
            else:
                return await asyncio.to_thread(handler, payload, workspace_id)
        except HTTPException:
            raise
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"Missing required field: {exc}")
        except Exception:
            _log_with_context("exception", "RAG tool %s failed", tool_name)
            raise HTTPException(status_code=500, detail="Internal server error")

    # ========================================================================
    # MCP Streamable HTTP ASGI Handler (extracts X-API-Key and delegates)
    # ========================================================================
    
    async def _mcp_asgi_app(scope, receive, send):
        """ASGI handler for /mcp endpoint: extract X-API-Key and delegate to session manager."""
        if scope["type"] != "http":
            return await mcp_session_manager.handle_request(scope, receive, send)
        
        # Extract X-API-Key from headers
        api_key = None
        actor_id = None
        actor_type = None
        actor_signature = None
        actor_timestamp = None
        for header_name, header_value in scope.get("headers", []):
            lower_name = header_name.lower()
            decoded_value = header_value.decode("utf-8")
            if lower_name == b"x-api-key":
                api_key = decoded_value
            elif lower_name == b"x-actor-id":
                actor_id = decoded_value
            elif lower_name == b"x-actor-type":
                actor_type = decoded_value
            elif lower_name == b"x-actor-signature":
                actor_signature = decoded_value
            elif lower_name == b"x-actor-timestamp":
                actor_timestamp = decoded_value
        
        # Set contextvar for tool handlers to consume
        token = _mcp_api_key.set(api_key)
        actor_id_token = _mcp_actor_id.set(actor_id)
        actor_type_token = _mcp_actor_type.set(actor_type)
        actor_signature_token = _mcp_actor_signature.set(actor_signature)
        actor_timestamp_token = _mcp_actor_timestamp.set(actor_timestamp)
        try:
            return await mcp_session_manager.handle_request(scope, receive, send)
        finally:
            _mcp_api_key.reset(token)
            _mcp_actor_id.reset(actor_id_token)
            _mcp_actor_type.reset(actor_type_token)
            _mcp_actor_signature.reset(actor_signature_token)
            _mcp_actor_timestamp.reset(actor_timestamp_token)
    
    # Mount MCP endpoint (with and without trailing slash)
    app.mount("/mcp", _mcp_asgi_app)
    app.mount("/mcp/", _mcp_asgi_app)

# Close indentation wrapper
if True:
    pass

if __name__ == "__main__":
    _log.info("Starting MCP HTTP server on port 8080 with /mcp endpoint")
    uvicorn.run(app, host="0.0.0.0", port=8080)
