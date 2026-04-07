"""
Workspace resolver — derives workspace_id from a verified caller identity.

Callers never supply workspace_id directly; it is always resolved here from
a credential the server can verify (API key or JWT).

Supported mechanisms (configure via env vars):
  API key  — set RAG_API_KEYS as a comma-separated list of
             "hmac_sha256_hex:workspace_uuid" pairs.
             Example:
               RAG_API_KEYS=abc123hash:ws-uuid-1,def456hash:ws-uuid-2
             
             Also requires RAG_SERVER_SECRET for HMAC computation.
             Generate keys using: python generate_api_key.py "key1" "key2"

The API key sent by the caller must be in the X-API-Key header.
The server computes HMAC-SHA256(server_secret, api_key) and looks up the result.

Security: HMAC prevents offline dictionary attacks if config leaks.
          API keys MUST be high-entropy random values (32+ characters).

Add JWT support here when needed; do not change the public interface.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi import Header, HTTPException

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server secret for HMAC (loaded once at import)
# ---------------------------------------------------------------------------

def _get_server_secret() -> bytes:
    """
    Get server secret from RAG_SERVER_SECRET environment variable.
    
    CRITICAL: This secret must be:
    - Set consistently across all deployments
    - Different from API keys
    - High-entropy random value (32+ bytes recommended)
    - Kept secure (do not commit to version control)
    
    If not set, authentication will fail (intentional fail-closed behavior).
    """
    secret = os.getenv("RAG_SERVER_SECRET", "")
    if not secret:
        _log.error(
            "RAG_SERVER_SECRET not set. Authentication will fail. "
            "Set a strong server secret: export RAG_SERVER_SECRET='$(openssl rand -base64 32)'"
        )
        # Return empty bytes to allow import, but all auth attempts will fail
        return b""
    return secret.encode()

_SERVER_SECRET: bytes = _get_server_secret()

# ---------------------------------------------------------------------------
# Build lookup table at import time (cheap; env var is read once)
# ---------------------------------------------------------------------------

def _build_key_table() -> dict[str, str]:
    """
    Return {hmac_sha256_hex: workspace_id} from RAG_API_KEYS env var.
    
    SECURITY WARNING: Multiple keys mapping to the SAME workspace_id is allowed
    (for key rotation, multi-service access), but accidental collision is a
    critical risk. This function logs a warning if duplicate workspace_id values
    are detected to help catch configuration errors.
    
    SAFE PATTERN: Use deterministic UUIDv5 generation (see generate_workspace_id below)
    instead of manual UUID assignment to prevent collisions.
    
    Format: RAG_API_KEYS=hmac_hex1:workspace_uuid1,hmac_hex2:workspace_uuid2,...
    
    IMPORTANT: Keys must be generated with generate_api_key.py using the SAME
               RAG_SERVER_SECRET that is set in this deployment.
    """
    raw = os.getenv("RAG_API_KEYS", "")
    table: dict[str, str] = {}
    workspace_ids_seen: dict[str, list[str]] = {}  # workspace_id -> [key_hashes]
    
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 1)
        if len(parts) != 2:
            _log.warning("Skipping malformed RAG_API_KEYS entry (expected hash:workspace_id)")
            continue
        
        key_hash = parts[0].lower()
        workspace_id = parts[1]
        
        table[key_hash] = workspace_id
        
        # Track workspace_id usage to detect collisions
        if workspace_id not in workspace_ids_seen:
            workspace_ids_seen[workspace_id] = []
        workspace_ids_seen[workspace_id].append(key_hash)
    
    # Warn about potential tenant collisions (multiple keys → same workspace)
    for workspace_id, key_hashes in workspace_ids_seen.items():
        if len(key_hashes) > 1:
            _log.warning(
                "SECURITY: Multiple API keys map to workspace %s: %s. "
                "If this is intentional (key rotation, multi-service), ignore. "
                "If accidental, this is a TENANT COLLISION RISK.",
                workspace_id,
                ", ".join(key_hashes[:3])  # Show first 3
            )
    
    return table


_KEY_TABLE: dict[str, str] = _build_key_table()


# ---------------------------------------------------------------------------
# Safe workspace_id generation (prevents tenant collision)
# ---------------------------------------------------------------------------

def generate_workspace_id(api_key: str) -> str:
    """
    Generate a deterministic workspace_id from an API key using UUIDv5.
    
    This prevents tenant collision by making workspace_id a cryptographic
    function of the API key. Two different keys will ALWAYS produce different
    workspace UUIDs.
    
    Security: Uses HMAC-SHA256 with server secret before UUIDv5 derivation
              to prevent offline dictionary attacks if config leaks.
    
    Usage:
        export RAG_SERVER_SECRET="your-server-secret"
        api_key = "my-secret-key-for-tenant-a"
        workspace_id = generate_workspace_id(api_key)
        # Or use: python generate_api_key.py "my-secret-key-for-tenant-a"
    
    The namespace UUID is specific to this application to avoid collisions
    with other systems using UUIDv5.
    """
    import uuid
    
    # Namespace UUID for Notion MCP Governance Server
    # IMPORTANT: This is intentionally fixed across all environments.
    # Change only if you want different workspace_id derivations per environment.
    NAMESPACE = uuid.UUID("a7c3e8f2-4d9b-5a1c-8e6f-2b4d7a9c1e3f")
    
    # UUIDv5(namespace, HMAC-SHA256(server_secret, api_key))
    # HMAC prevents offline guessing if RAG_API_KEYS leaks
    key_id = hmac.new(_SERVER_SECRET, api_key.encode(), hashlib.sha256).hexdigest()
    return str(uuid.uuid5(NAMESPACE, key_id))


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def resolve_workspace_id(x_api_key: Optional[str] = Header(default=None)) -> str:
    """
    FastAPI dependency — resolves workspace_id from the X-API-Key header.

    Raises HTTP 401 when:
      - RAG_API_KEYS is not configured (auth is not set up)
      - RAG_SERVER_SECRET is not set (HMAC computation impossible)
      - Header is missing
      - Key does not match any registered workspace

    Returns the workspace_id UUID string on success.
    """
    if not _SERVER_SECRET:
        raise HTTPException(
            status_code=401,
            detail=(
                "Server authentication not configured (RAG_SERVER_SECRET missing). "
                "Contact system administrator."
            ),
        )
    
    if not _KEY_TABLE:
        raise HTTPException(
            status_code=401,
            detail=(
                "RAG_API_KEYS is not configured. "
                "Set it in .env as hmac_sha256_hex:workspace_id pairs."
            ),
        )
    
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header is required")

    # Compute HMAC-SHA256 (not plain SHA-256) for stronger security
    key_id = hmac.new(_SERVER_SECRET, x_api_key.encode(), hashlib.sha256).hexdigest()
    workspace_id = _KEY_TABLE.get(key_id)
    
    if workspace_id is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return workspace_id
