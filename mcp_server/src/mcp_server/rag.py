"""
Governance-first RAG retrieval module.

Architecture (locked — do not add governance columns to rag_chunks):

  rag_sources       single source of governance truth.
                    Owns: workspace_id, status, visibility,
                          effective_from/to, legal_hold, retention_class.

  rag_chunks        Storage-oriented only.
                    Owns: id, source_id, content, embedding,
                          position, token_count.
                    Inherits all governance via source_id → rag_sources.id.
                    Only add per-chunk columns for genuine storage reasons.

  rag_source_access Per-child entitlement table.
                    Use instead of adding child/user columns to rag_chunks.
                    Only joined when child_id filtering is required.

Retrieval invariant (never bypass):
  1. Filter at source level:
       rs.workspace_id = :workspace_id   ← always resolved server-side from API key
       rs.status        = 'published'
       rs.legal_hold    = FALSE
       effective window (effective_from/to)
  2. Optionally join rag_source_access when child_id is known.
  3. Rank chunks by cosine similarity: ORDER BY rc.embedding <=> query_embedding.

workspace_id decision (locked):
  ALWAYS resolved from the caller's API key via auth.resolve_workspace_id().
  NEVER accepted from tool arguments directly.
  Every DB call runs inside a transaction that does SET LOCAL app.workspace_id
  before executing SQL, so RLS policies can enforce it at the DB level.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

EMBEDDING_DIM = 1536
MAX_TOP_K = 100
MAX_CHUNKS_PER_BATCH = 200

# Timeout constants (milliseconds) for Postgres statement_timeout
DB_SEARCH_TIMEOUT_MS = int(os.getenv("DB_SEARCH_TIMEOUT_MS", "3000"))
DB_INGEST_TIMEOUT_MS = int(os.getenv("DB_INGEST_TIMEOUT_MS", "10000"))


def _validate_embedding(embedding: list[float]) -> None:
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("embedding must be a non-empty list of numbers")
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"embedding must be length {EMBEDDING_DIM}")
    for value in embedding:
        if not isinstance(value, (int, float)):
            raise ValueError("embedding values must be numeric")

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_conn():
    """
    PRIVATE: Get a new PostgreSQL connection.
    
    WARNING: Do NOT call this directly from handlers, scripts, or background jobs.
    ALWAYS use run_scoped_query() instead to ensure workspace isolation.
    
    Direct usage bypasses:
    - SET LOCAL app.workspace_id (RLS will deny all access)
    - Transaction safety
    - UUID validation
    
    This function is ONLY called inside run_scoped_query().
    """
    """Return a psycopg2 connection. Raises RuntimeError if not configured."""
    url = os.getenv("RAG_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "RAG_DATABASE_URL is not set. "
            "Add it to your .env file to enable RAG functionality."
        )
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 is not installed. Run: pip install psycopg2-binary") from exc
    return psycopg2.connect(url)


def _apply_session_context(
    cur: Any,
    workspace_id: str,
    *,
    actor_id: str | None = None,
    actor_type: str | None = None,
    request_id: str | None = None,
) -> None:
    """
    Apply transaction-scoped session context for RLS, views, and audit correlation.

    Required today:
    - app.workspace_id

    Optional, forward-looking context for assignment-aware authorization:
    - app.actor_id
    - app.actor_type
    - app.request_id
    """
    cur.execute("SET LOCAL app.workspace_id = %s", (str(workspace_id),))
    if actor_id is not None:
        cur.execute("SET LOCAL app.actor_id = %s", (actor_id,))
    if actor_type is not None:
        cur.execute("SET LOCAL app.actor_type = %s", (actor_type,))
    if request_id is not None:
        cur.execute("SET LOCAL app.request_id = %s", (request_id,))


# ---------------------------------------------------------------------------
# Scoped query wrapper — single entrypoint for all RAG DB calls
# ---------------------------------------------------------------------------

def run_scoped_query(
    workspace_id: str,
    sql: str,
    params: dict[str, Any],
    *,
    many: bool = False,
    returning: bool = True,
    timeout_ms: int | None = None,
    actor_id: str | None = None,
    actor_type: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]] | int:
    """
    Execute sql inside a transaction with SET LOCAL app.workspace_id.

    All rag.* tools MUST go through this function. Never call _get_conn()
    directly from tool handlers.

    Parameters
    ----------
    workspace_id : Server-resolved workspace UUID — never caller-supplied.
    sql          : The query to run (SELECT / INSERT / UPDATE / DELETE).
    params       : Named parameters for the query.
    many         : If True, use executemany(sql, params as list).
    returning    : If True, fetchall() and return rows as list[dict].
                   If False, return rowcount as int.
    timeout_ms   : Optional Postgres statement_timeout in milliseconds.
                   Recommended: 3000ms for search, 10000ms for ingest.
    actor_id     : Optional actor identity to project into SQL session context.
    actor_type   : Optional actor type for future assignment-aware authorization.
    request_id   : Optional request correlation ID for SQL-side event/audit logic.

    The SET LOCAL only affects the current transaction; it is safe on pooled
    connections because it cannot leak to the next user of the connection.
    """
    import uuid
    from psycopg2.extras import RealDictCursor

    # Guard: workspace_id must be a valid UUID (fail fast)
    try:
        uuid.UUID(workspace_id)
    except (ValueError, AttributeError) as e:
        raise ValueError(f"workspace_id must be a valid UUID, got: {workspace_id!r}") from e

    conn = _get_conn()
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Explicit BEGIN — makes transaction boundary clear
            cur.execute("BEGIN")
            # Enforce session context at DB level. SET LOCAL is transaction-scoped
            # and cannot leak across pooled connections.
            _apply_session_context(
                cur,
                workspace_id,
                actor_id=actor_id,
                actor_type=actor_type,
                request_id=request_id,
            )
            # Set statement timeout if specified (3-layer timeout defense)
            if timeout_ms is not None:
                cur.execute(f"SET LOCAL statement_timeout = '{timeout_ms}ms'")
            if many:
                cur.executemany(sql, params)  # type: ignore[arg-type]
            else:
                cur.execute(sql, params)
            
            # Safe fetch: only fetchall if the query returned rows
            if returning and cur.description is not None:
                rows = [dict(row) for row in cur.fetchall()]
            else:
                rows = None
            rowcount = cur.rowcount
        conn.commit()
        return rows if returning else rowcount  # type: ignore[return-value]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Retrieval — governance filter first, similarity rank second
# ---------------------------------------------------------------------------

_RETRIEVE_SQL = """
    SELECT
        rc.id,
        rc.source_id,
        rc.content,
        rc.position,
        rc.token_count,
        rs.name            AS source_name,
        rs.visibility,
        rs.retention_class,
        1 - (rc.embedding <=> %(embedding)s::vector) AS similarity
    FROM  rag_chunks  rc
    JOIN  rag_sources rs ON rs.id = rc.source_id
    {access_join}
    WHERE rs.status        = 'published'
      AND rs.legal_hold    = FALSE
      AND (rs.effective_from IS NULL OR rs.effective_from <= NOW())
      AND (rs.effective_to   IS NULL OR rs.effective_to   >= NOW())
      {access_filter}
    ORDER BY rc.embedding <=> %(embedding)s::vector
    LIMIT %(top_k)s
"""


def retrieve(
    workspace_id: str,
    query_embedding: list[float],
    top_k: int = 10,
    child_id: str | None = None,
    *,
    actor_id: str | None = None,
    actor_type: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Governance-first vector retrieval.

    Parameters
    ----------
    workspace_id    : Required. Resolved server-side from API key — never from args.
    query_embedding : Embedding vector of the search query.
    top_k           : Maximum chunks to return (default 10).
    child_id        : Optional. When provided, a JOIN on rag_source_access is
                      added to enforce per-child entitlements.
                      Do NOT add child columns to rag_chunks — use this instead.
    """
    _validate_embedding(query_embedding)
    top_k = max(1, min(int(top_k), MAX_TOP_K))

    access_join: str = ""
    access_filter: str = ""
    params: dict[str, Any] = {
        "embedding": query_embedding,
        "top_k": top_k,
    }

    if child_id is not None:
        access_join = "JOIN rag_source_access rsa ON rsa.source_id = rs.id"
        access_filter = "AND rsa.child_id = %(child_id)s"
        params["child_id"] = child_id

    sql = _RETRIEVE_SQL.format(access_join=access_join, access_filter=access_filter)
    results = run_scoped_query(
        workspace_id,
        sql,
        params,
        returning=True,
        timeout_ms=DB_SEARCH_TIMEOUT_MS,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )  # type: ignore[assignment]
    if actor_id is not None:
        try:
            _record_governed_read_event(
                workspace_id,
                actor_id=actor_id,
                actor_type=actor_type or "user",
                action="rag.retrieve",
                target_type="rag_chunk",
                target_id=child_id,
                payload={
                    "top_k": top_k,
                    "mode": "governance-first-rag",
                    "child_scope": child_id is not None,
                },
                result_count=len(results),
                request_id=request_id,
            )
        except Exception:
            _log.exception("Failed to persist rag.retrieve domain event/audit record")
    return results  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Ingest — source first, then chunks
# ---------------------------------------------------------------------------

def ingest_source(
    workspace_id: str,
    name: str,
    status: str = "draft",
    visibility: str = "private",
    effective_from: str | None = None,
    effective_to: str | None = None,
    legal_hold: bool = False,
    retention_class: str | None = None,
) -> str:
    """
    Create a governance source record.

    Returns the new source_id (UUID string).
    Sources are created in 'draft' status by default; set status='published'
    to make them visible in retrieval.
    """
    sql = """
        INSERT INTO rag_sources
            (workspace_id, name, status, visibility,
             effective_from, effective_to, legal_hold, retention_class)
        VALUES
            (%(workspace_id)s, %(name)s, %(status)s, %(visibility)s,
             %(effective_from)s, %(effective_to)s, %(legal_hold)s, %(retention_class)s)
        RETURNING id
    """
    rows = run_scoped_query(
        workspace_id,
        sql,
        {
            "workspace_id": workspace_id,
            "name": name,
            "status": status,
            "visibility": visibility,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "legal_hold": legal_hold,
            "retention_class": retention_class,
        },
        returning=True,
        timeout_ms=DB_INGEST_TIMEOUT_MS,
    )
    return str(rows[0]["id"])  # type: ignore[index]


def ingest_chunks(source_id: str, chunks: list[dict[str, Any]], workspace_id: str) -> int:
    """
    Insert content chunks (with embeddings) for an existing governance source.

    workspace_id is required so SET LOCAL is always applied, even for chunk-only writes.

    Each chunk dict must contain:
      content   (str)          — the text content
      embedding (list[float])  — the embedding vector

    Optional chunk fields (storage metadata only, never governance):
      position    (int) — chunk order in the source document
      token_count (int) — token length of content

    Returns the number of rows inserted.
    """
    if not chunks:
        return 0
    if len(chunks) > MAX_CHUNKS_PER_BATCH:
        raise ValueError(f"chunks exceeds max batch size of {MAX_CHUNKS_PER_BATCH}")

    sql = """
        INSERT INTO rag_chunks (source_id, content, embedding, position, token_count)
        VALUES (%(source_id)s, %(content)s, %(embedding)s::vector,
                %(position)s, %(token_count)s)
    """
    rows = []
    for c in chunks:
        embedding = c["embedding"]
        _validate_embedding(embedding)
        rows.append(
            {
                "source_id": source_id,
                "content": c["content"],
                "embedding": embedding,
                "position": c.get("position"),
                "token_count": c.get("token_count"),
            }
        )
    run_scoped_query(workspace_id, sql, rows, many=True, returning=False, timeout_ms=DB_INGEST_TIMEOUT_MS)  # type: ignore[arg-type]
    return len(rows)


# ---------------------------------------------------------------------------
# Source access management
# ---------------------------------------------------------------------------

def grant_access(source_id: str, child_id: str, workspace_id: str, role: str | None = None) -> None:
    """Grant a child (user/team/service) access to a source. Idempotent."""
    sql = """
        INSERT INTO rag_source_access (source_id, child_id, role)
        VALUES (%(source_id)s, %(child_id)s, %(role)s)
        ON CONFLICT (source_id, child_id) DO UPDATE SET role = EXCLUDED.role
    """
    run_scoped_query(
        workspace_id,
        sql,
        {"source_id": source_id, "child_id": child_id, "role": role},
        returning=False,
    )


def revoke_access(source_id: str, child_id: str, workspace_id: str) -> None:
    """Revoke a child's access to a source."""
    sql = "DELETE FROM rag_source_access WHERE source_id = %(source_id)s AND child_id = %(child_id)s"
    run_scoped_query(
        workspace_id,
        sql,
        {"source_id": source_id, "child_id": child_id},
        returning=False,
    )


def _resolve_family_id(
    workspace_id: str,
    *,
    actor_id: str | None = None,
    actor_type: str | None = None,
    request_id: str | None = None,
) -> str | None:
    rows = run_scoped_query(
        workspace_id,
        "SELECT id FROM families WHERE workspace_id = %(workspace_id)s LIMIT 1",
        {"workspace_id": workspace_id},
        returning=True,
        timeout_ms=DB_SEARCH_TIMEOUT_MS,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )
    if not rows:
        return None
    return str(rows[0]["id"])


def _record_governed_read_event(
    workspace_id: str,
    *,
    actor_id: str,
    actor_type: str,
    action: str,
    target_type: str,
    target_id: str | None,
    payload: dict[str, Any],
    result_count: int,
    request_id: str | None,
) -> None:
    """
    Persist curated, non-raw event/audit metadata for governed read operations.

    The stored payload intentionally excludes returned resource rows and raw request
    bodies. Only filter metadata and result counts are recorded.
    """
    family_id = _resolve_family_id(
        workspace_id,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )
    if family_id is None:
        _log.warning("Skipping domain event/audit write: no family for workspace %s", workspace_id)
        return

    payload_with_result = {**payload, "result_count": result_count}

    event_rows = run_scoped_query(
        workspace_id,
        """
        INSERT INTO domain_events (family_id, member_id, request_id, actor_id, event_type, outcome, payload)
        VALUES (
            %(family_id)s,
            %(member_id)s,
            %(request_id)s::uuid,
            %(actor_id)s,
            %(event_type)s,
            %(outcome)s,
            %(payload)s::jsonb
        )
        RETURNING id
        """,
        {
            "family_id": family_id,
            "member_id": target_id,
            "request_id": request_id,
            "actor_id": actor_id,
            "event_type": action,
            "outcome": "success",
            "payload": json.dumps(payload_with_result),
        },
        returning=True,
        timeout_ms=DB_INGEST_TIMEOUT_MS,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )
    event_id = str(event_rows[0]["id"])

    previous_rows = run_scoped_query(
        workspace_id,
        """
        SELECT proof_hash
        FROM audit_immutable
        WHERE family_id = %(family_id)s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"family_id": family_id},
        returning=True,
        timeout_ms=DB_SEARCH_TIMEOUT_MS,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )
    previous_proof_hash = str(previous_rows[0]["proof_hash"]) if previous_rows else None

    proof_input = ":".join(
        [
            family_id,
            request_id or "",
            actor_id,
            action,
            previous_proof_hash or "",
            str(result_count),
        ]
    )
    proof_hash = hashlib.sha256(proof_input.encode()).hexdigest()

    run_scoped_query(
        workspace_id,
        """
        INSERT INTO audit_immutable (
            family_id,
            event_id,
            request_id,
            actor_id,
            action,
            outcome,
            target_type,
            target_id,
            reason_codes,
            payload,
            proof_hash,
            previous_proof_hash
        )
        VALUES (
            %(family_id)s,
            %(event_id)s::uuid,
            %(request_id)s::uuid,
            %(actor_id)s,
            %(action)s,
            %(outcome)s,
            %(target_type)s,
            %(target_id)s,
            %(reason_codes)s::jsonb,
            %(payload)s::jsonb,
            %(proof_hash)s,
            %(previous_proof_hash)s
        )
        """,
        {
            "family_id": family_id,
            "event_id": event_id,
            "request_id": request_id,
            "actor_id": actor_id,
            "action": action,
            "outcome": "success",
            "target_type": target_type,
            "target_id": target_id,
            "reason_codes": json.dumps([]),
            "payload": json.dumps(payload_with_result),
            "proof_hash": proof_hash,
            "previous_proof_hash": previous_proof_hash,
        },
        returning=False,
        timeout_ms=DB_INGEST_TIMEOUT_MS,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )


def list_authorized_resources(
    workspace_id: str,
    actor_id: str,
    *,
    actor_type: str = "user",
    member_id: str | None = None,
    resource_type: str | None = None,
    limit: int = 50,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return authorized resources via the secure SQL view.

    This is intended to be stateless and safe-by-default:
    - actor identity is provided per request
    - authorization is enforced in SQL via session context and secure view logic
    - only the secure view columns are returned; no raw payload persistence occurs
    """
    limit = max(1, min(int(limit), 100))

    filters = []
    params: dict[str, Any] = {"limit": limit}

    if member_id is not None:
        filters.append("member_id = %(member_id)s")
        params["member_id"] = member_id

    if resource_type is not None:
        filters.append("resource_type = %(resource_type)s")
        params["resource_type"] = resource_type

    where_clause = ""
    if filters:
        where_clause = "WHERE " + " AND ".join(filters)

    sql = f"""
        SELECT
            id,
            family_id,
            member_id,
            source_id,
            resource_type,
            name,
            status,
            visibility,
            classification,
            effective_from,
            effective_to,
            retention_class,
            created_at,
            updated_at
        FROM v_resource_authorized
        {where_clause}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT %(limit)s
    """
    results = run_scoped_query(
        workspace_id,
        sql,
        params,
        returning=True,
        timeout_ms=DB_SEARCH_TIMEOUT_MS,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )  # type: ignore[assignment]
    try:
        _record_governed_read_event(
            workspace_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action="resource.list",
            target_type="resource",
            target_id=member_id,
            payload={
                "resource_type": resource_type,
                "member_id": member_id,
                "limit": limit,
                "mode": "stateless-secure-view",
            },
            result_count=len(results),
            request_id=request_id,
        )
    except Exception:
        _log.exception("Failed to persist resource.list domain event/audit record")
    return results  # type: ignore[return-value]


def get_authorized_resource(
    workspace_id: str,
    actor_id: str,
    *,
    resource_id: str,
    actor_type: str = "user",
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Return one authorized resource via the secure SQL view.

    This is fail-closed: if the resource is not visible to the supplied actor,
    the function returns None rather than disclosing whether the row exists.
    """
    sql = """
        SELECT
            id,
            family_id,
            member_id,
            source_id,
            resource_type,
            name,
            status,
            visibility,
            classification,
            effective_from,
            effective_to,
            retention_class,
            created_at,
            updated_at
        FROM v_resource_authorized
        WHERE id = %(resource_id)s
        LIMIT 1
    """
    results = run_scoped_query(
        workspace_id,
        sql,
        {"resource_id": resource_id},
        returning=True,
        timeout_ms=DB_SEARCH_TIMEOUT_MS,
        actor_id=actor_id,
        actor_type=actor_type,
        request_id=request_id,
    )  # type: ignore[assignment]
    resource = results[0] if results else None
    try:
        _record_governed_read_event(
            workspace_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action="resource.get",
            target_type="resource",
            target_id=resource_id,
            payload={
                "resource_id": resource_id,
                "mode": "stateless-secure-view",
            },
            result_count=1 if resource is not None else 0,
            request_id=request_id,
        )
    except Exception:
        _log.exception("Failed to persist resource.get domain event/audit record")
    return resource  # type: ignore[return-value]
