-- sql.dialect=PostgreSQL
-- =============================================================================
-- Notion MCP Governance-First Server — RAG schema
-- Requires: PostgreSQL 14+ with pgvector extension
--
-- Architecture (locked):
--   rag_sources      = single source of governance truth
--                      (workspace_id, status, visibility, effective_from/to,
--                       legal_hold, retention_class)
--   rag_chunks       = storage-oriented; inherits all governance via
--                      source_id → rag_sources.id
--                      only: id, source_id, content, embedding, position, token_count
--   rag_source_access = per-child entitlement; only consulted when filtering
--                      by a specific child/user. Never added to rag_chunks.
--
-- Retrieval invariant (never bypass):
--   1. Filter at source level first:
--        rs.workspace_id = :workspace_id
--        rs.status        = 'published'
--        rs.legal_hold    = FALSE
--        effective window (effective_from/to)
--   2. Optionally join rag_source_access when child_id is known
--   3. Rank by cosine similarity: ORDER BY rc.embedding <=> query_embedding
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;       -- for vector type and <=> operator

-- =============================================================================
-- DB Role Hardening (CRITICAL — must be enforced before RLS is useful)
-- =============================================================================

-- Create application role WITHOUT BYPASSRLS and WITHOUT table ownership.
-- This role will be used by the MCP server; it MUST NOT be a superuser or
-- member of any role with BYPASSRLS.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_app') THEN
    CREATE ROLE mcp_app LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
  END IF;
END
$$;

-- CRITICAL: Verify the role does NOT have BYPASSRLS
-- Run after creating role: SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname = 'mcp_app';
-- Expected: mcp_app | f

-- Grant minimal permissions (SELECT, INSERT, UPDATE, DELETE only)
-- DO NOT grant table ownership or BYPASSRLS
GRANT CONNECT ON DATABASE postgres TO mcp_app;  -- Adjust database name as needed

-- Note: GRANT statements on tables are below, after tables are created

-- -----------------------------------------------------------------------------
-- rag_sources — governance truth; one row per logical document / data source
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rag_sources (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID        NOT NULL,  -- Changed from TEXT to UUID for type safety
    name             TEXT        NOT NULL,
    status           TEXT        NOT NULL DEFAULT 'draft'
                                 CHECK (status IN ('draft', 'published', 'archived')),
    visibility       TEXT        NOT NULL DEFAULT 'private'
                                 CHECK (visibility IN ('private', 'workspace', 'public')),
    -- governance window: NULL means "no bound"
    effective_from   TIMESTAMPTZ,
    effective_to     TIMESTAMPTZ,
    -- legal hold: when TRUE, source is excluded from ALL retrievals
    legal_hold       BOOLEAN     NOT NULL DEFAULT FALSE,
    retention_class  TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT effective_window_order
        CHECK (effective_from IS NULL OR effective_to IS NULL OR effective_from < effective_to)
);

-- Keep updated_at current automatically
CREATE OR REPLACE FUNCTION rag_sources_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

DROP TRIGGER IF EXISTS trg_rag_sources_updated_at ON rag_sources;
CREATE TRIGGER trg_rag_sources_updated_at
    BEFORE UPDATE ON rag_sources
    FOR EACH ROW EXECUTE FUNCTION rag_sources_set_updated_at();

-- Governance-first filter index (workspace + status is the hot path)
CREATE INDEX IF NOT EXISTS idx_rag_sources_workspace_status
    ON rag_sources (workspace_id, status)
    WHERE legal_hold = FALSE;

-- Effective-window index
CREATE INDEX IF NOT EXISTS idx_rag_sources_effective_window
    ON rag_sources (effective_from, effective_to);

-- -----------------------------------------------------------------------------
-- rag_chunks — storage-oriented; governance inherited via source_id
-- Only add per-chunk columns for genuine storage reasons, NOT governance.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rag_chunks (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID    NOT NULL
                        REFERENCES rag_sources (id) ON DELETE CASCADE,
    content     TEXT    NOT NULL,
    -- Embedding dimension: 1536 for text-embedding-3-small / ada-002,
    --                       3072 for text-embedding-3-large.
    -- Adjust BEFORE inserting the first row; changing it later requires rebuild.
    embedding   VECTOR(1536),
    position    INTEGER,       -- chunk order within the source document
    token_count INTEGER,       -- token length of `content`
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Foreign-key navigation
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_id
    ON rag_chunks (source_id);

-- ANN index for cosine similarity (tune lists= to ~sqrt(row count) at build time)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_cosine
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- -----------------------------------------------------------------------------
-- rag_source_access — per-child entitlement (optional; only add when needed)
-- Do NOT contaminate rag_chunks with access columns.
-- Query pattern:
--   JOIN rag_source_access rsa ON rsa.source_id = rs.id
--   AND rsa.child_id = :child_id
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rag_source_access (
    source_id  UUID NOT NULL REFERENCES rag_sources (id) ON DELETE CASCADE,
    child_id   TEXT NOT NULL,   -- user-id, team-id, service-account, etc.
    role       TEXT,            -- optional: 'reader' | 'editor' | NULL
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, child_id)
);

CREATE INDEX IF NOT EXISTS idx_rag_source_access_child
    ON rag_source_access (child_id);

-- =============================================================================
-- Grant permissions to application role (after tables created)
-- =============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON rag_sources TO mcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON rag_chunks TO mcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON rag_source_access TO mcp_app;

-- Verify role hardening:
-- SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'mcp_app';
-- Expected: mcp_app | f | f
--
-- Verify table ownership (should NOT be mcp_app):
-- SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public'
--   AND tablename IN ('rag_sources', 'rag_chunks', 'rag_source_access');
-- Expected: tableowner should be postgres or your admin role, NOT mcp_app

-- =============================================================================
-- Row-Level Security (RLS) — deny-by-default workspace isolation
--
-- The application DB role must NOT be table owner and must NOT have BYPASSRLS.
-- Create it with:
--   CREATE ROLE mcp_app LOGIN PASSWORD '...';
--   GRANT SELECT, INSERT, UPDATE, DELETE
--       ON rag_sources, rag_chunks, rag_source_access TO mcp_app;
--
-- The server sets workspace context per-transaction with:
--   SET LOCAL app.workspace_id = '<uuid>';
--
-- RLS policies read current_setting('app.workspace_id', true).
-- If the gateway forgets SET LOCAL, current_setting returns NULL and the
-- comparison fails → zero rows returned (deny-by-default, no error).
-- =============================================================================

-- Enable RLS on all tables with FORCE (prevents table owner bypass)
ALTER TABLE rag_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_sources FORCE ROW LEVEL SECURITY;

ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_chunks FORCE ROW LEVEL SECURITY;

ALTER TABLE rag_source_access ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_source_access FORCE ROW LEVEL SECURITY;

-- rag_sources: enforce workspace + all governance rules (defense in depth)
-- Even if someone bypasses Python filters, DB will deny non-compliant rows

-- READ policy: Only see published, non-quarantined, time-valid sources in your workspace
CREATE POLICY rag_sources_workspace_isolation
    ON rag_sources
    FOR SELECT
    USING (
        workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
        AND status = 'published'
        AND legal_hold = FALSE
        AND (effective_from IS NULL OR effective_from <= NOW())
        AND (effective_to IS NULL OR effective_to >= NOW())
    );

-- WRITE policy (CRITICAL): Prevent cross-tenant contamination on INSERT/UPDATE
-- Without this, users could insert rows into other workspaces
CREATE POLICY rag_sources_workspace_write
    ON rag_sources
    FOR ALL
    WITH CHECK (
        workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    );

-- rag_chunks: allow only chunks whose source passes ALL governance checks
-- RLS becomes the single source of truth — no bypass possible

-- READ policy: Only see chunks from compliant sources
CREATE POLICY rag_chunks_workspace_isolation
    ON rag_chunks
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM rag_sources rs
            WHERE rs.id = source_id
              AND rs.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
              AND rs.status = 'published'
              AND rs.legal_hold = FALSE
              AND (rs.effective_from IS NULL OR rs.effective_from <= NOW())
              AND (rs.effective_to IS NULL OR rs.effective_to >= NOW())
        )
    );

-- WRITE policy (CRITICAL): Prevent cross-tenant contamination on INSERT/UPDATE
-- Without this, users could insert chunks into sources from other workspaces
CREATE POLICY rag_chunks_workspace_write
    ON rag_chunks
    FOR ALL
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM rag_sources rs
            WHERE rs.id = source_id
              AND rs.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
        )
    );

-- rag_source_access: enforce workspace isolation for access control table
-- Even though this is typically accessed via joins, RLS prevents direct query leakage

-- READ policy: Only see access grants for sources in your workspace
CREATE POLICY rag_source_access_workspace_isolation
    ON rag_source_access
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM rag_sources rs
            WHERE rs.id = source_id
              AND rs.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
        )
    );

-- WRITE policy: Prevent granting access to sources in other workspaces
CREATE POLICY rag_source_access_workspace_write
    ON rag_source_access
    FOR ALL
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM rag_sources rs
            WHERE rs.id = source_id
              AND rs.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
        )
    );
