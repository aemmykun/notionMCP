-- sql.dialect=PostgreSQL
-- =============================================================================
-- Domain Backbone Migration
--
-- Purpose:
--   Introduce the first domain-aligned tables from the original architecture
--   without breaking the current governance-first RAG implementation.
--
-- Prerequisites:
--   1. Apply schema.sql first (creates mcp_app, rag_sources, and base RLS model)
--   2. PostgreSQL 14+ with pgcrypto available
--
-- Compatibility strategy:
--   - Preserve current workspace_id isolation by mapping one family to one
--     workspace boundary via families.workspace_id.
--   - Keep rag_sources as the current content-governance source of truth.
--   - Allow future resources to link back to rag_sources via resources.source_id.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- Shared trigger helpers
-- =============================================================================

CREATE OR REPLACE FUNCTION domain_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_audit_immutable_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_immutable is append-only; % operations are not allowed', TG_OP;
END;
$$;

-- =============================================================================
-- families
-- =============================================================================

CREATE TABLE IF NOT EXISTS families (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id    UUID NOT NULL UNIQUE,
  family_key      TEXT UNIQUE,
  name            TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'inactive', 'archived')),
  billing_state   TEXT NOT NULL DEFAULT 'current'
                  CHECK (billing_state IN ('current', 'past_due', 'suspended', 'closed')),
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_families_updated_at ON families;
CREATE TRIGGER trg_families_updated_at
  BEFORE UPDATE ON families
  FOR EACH ROW EXECUTE FUNCTION domain_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_families_workspace_id
  ON families (workspace_id);

CREATE INDEX IF NOT EXISTS idx_families_status
  ON families (status);

-- =============================================================================
-- members
-- =============================================================================

CREATE TABLE IF NOT EXISTS members (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families (id) ON DELETE CASCADE,
  external_key    TEXT,
  display_name    TEXT NOT NULL,
  member_type     TEXT NOT NULL DEFAULT 'child'
                  CHECK (member_type IN ('child', 'guardian', 'staff', 'system')),
  relationship    TEXT,
  department      TEXT,
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'inactive', 'archived')),
  date_of_birth   DATE,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (family_id, external_key)
);

DROP TRIGGER IF EXISTS trg_members_updated_at ON members;
CREATE TRIGGER trg_members_updated_at
  BEFORE UPDATE ON members
  FOR EACH ROW EXECUTE FUNCTION domain_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_members_family_id
  ON members (family_id);

CREATE INDEX IF NOT EXISTS idx_members_type_status
  ON members (family_id, member_type, status);

-- =============================================================================
-- resources
-- =============================================================================

CREATE TABLE IF NOT EXISTS resources (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id          UUID NOT NULL REFERENCES families (id) ON DELETE CASCADE,
  member_id          UUID REFERENCES members (id) ON DELETE SET NULL,
  source_id          UUID REFERENCES rag_sources (id) ON DELETE SET NULL,
  resource_type      TEXT NOT NULL,
  name               TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('draft', 'active', 'archived', 'deleted')),
  visibility         TEXT NOT NULL DEFAULT 'family'
                     CHECK (visibility IN ('family', 'assignment', 'internal')),
  classification     TEXT,
  legal_hold         BOOLEAN NOT NULL DEFAULT FALSE,
  effective_from     TIMESTAMPTZ,
  effective_to       TIMESTAMPTZ,
  retention_class    TEXT,
  encryption_key_ref TEXT,
  metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT resources_effective_window_order
    CHECK (effective_from IS NULL OR effective_to IS NULL OR effective_from < effective_to)
);

DROP TRIGGER IF EXISTS trg_resources_updated_at ON resources;
CREATE TRIGGER trg_resources_updated_at
  BEFORE UPDATE ON resources
  FOR EACH ROW EXECUTE FUNCTION domain_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_resources_family_status
  ON resources (family_id, status)
  WHERE legal_hold = FALSE;

CREATE INDEX IF NOT EXISTS idx_resources_member_id
  ON resources (member_id);

CREATE INDEX IF NOT EXISTS idx_resources_source_id
  ON resources (source_id)
  WHERE source_id IS NOT NULL;

-- =============================================================================
-- domain_events
-- =============================================================================

CREATE TABLE IF NOT EXISTS domain_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families (id) ON DELETE CASCADE,
  member_id       UUID REFERENCES members (id) ON DELETE SET NULL,
  resource_id     UUID REFERENCES resources (id) ON DELETE SET NULL,
  request_id      UUID,
  actor_id        TEXT NOT NULL,
  event_type      TEXT NOT NULL,
  outcome         TEXT NOT NULL DEFAULT 'info'
                  CHECK (outcome IN ('info', 'success', 'deny', 'error')),
  payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_domain_events_family_created_at
  ON domain_events (family_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_domain_events_request_id
  ON domain_events (request_id)
  WHERE request_id IS NOT NULL;

-- =============================================================================
-- audit_immutable
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_immutable (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id           UUID NOT NULL REFERENCES families (id) ON DELETE CASCADE,
  event_id            UUID REFERENCES domain_events (id) ON DELETE SET NULL,
  request_id          UUID,
  actor_id            TEXT NOT NULL,
  action              TEXT NOT NULL,
  outcome             TEXT NOT NULL
                      CHECK (outcome IN ('success', 'deny', 'error')),
  target_type         TEXT,
  target_id           TEXT,
  reason_codes        JSONB NOT NULL DEFAULT '[]'::jsonb,
  payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
  proof_hash          TEXT NOT NULL,
  previous_proof_hash TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_immutable_family_created_at
  ON audit_immutable (family_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_immutable_request_id
  ON audit_immutable (request_id)
  WHERE request_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_immutable_proof_hash
  ON audit_immutable (proof_hash);

DROP TRIGGER IF EXISTS trg_audit_immutable_no_update ON audit_immutable;
CREATE TRIGGER trg_audit_immutable_no_update
  BEFORE UPDATE OR DELETE ON audit_immutable
  FOR EACH ROW EXECUTE FUNCTION prevent_audit_immutable_mutation();

-- =============================================================================
-- Grants
-- =============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON families TO mcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON members TO mcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON resources TO mcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON domain_events TO mcp_app;
GRANT SELECT, INSERT ON audit_immutable TO mcp_app;

-- =============================================================================
-- RLS
-- =============================================================================

ALTER TABLE families ENABLE ROW LEVEL SECURITY;
ALTER TABLE families FORCE ROW LEVEL SECURITY;

ALTER TABLE members ENABLE ROW LEVEL SECURITY;
ALTER TABLE members FORCE ROW LEVEL SECURITY;

ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE resources FORCE ROW LEVEL SECURITY;

ALTER TABLE domain_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE domain_events FORCE ROW LEVEL SECURITY;

ALTER TABLE audit_immutable ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_immutable FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS families_workspace_isolation ON families;
CREATE POLICY families_workspace_isolation
  ON families
  FOR SELECT
  USING (
    workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
  );

DROP POLICY IF EXISTS families_workspace_write ON families;
CREATE POLICY families_workspace_write
  ON families
  FOR ALL
  WITH CHECK (
    workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
  );

DROP POLICY IF EXISTS members_workspace_isolation ON members;
CREATE POLICY members_workspace_isolation
  ON members
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = members.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS members_workspace_write ON members;
CREATE POLICY members_workspace_write
  ON members
  FOR ALL
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = members.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS resources_workspace_isolation ON resources;
CREATE POLICY resources_workspace_isolation
  ON resources
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = resources.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS resources_workspace_write ON resources;
CREATE POLICY resources_workspace_write
  ON resources
  FOR ALL
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = resources.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS domain_events_workspace_isolation ON domain_events;
CREATE POLICY domain_events_workspace_isolation
  ON domain_events
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = domain_events.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS domain_events_workspace_write ON domain_events;
CREATE POLICY domain_events_workspace_write
  ON domain_events
  FOR ALL
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = domain_events.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS audit_immutable_workspace_isolation ON audit_immutable;
CREATE POLICY audit_immutable_workspace_isolation
  ON audit_immutable
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = audit_immutable.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS audit_immutable_workspace_insert ON audit_immutable;
CREATE POLICY audit_immutable_workspace_insert
  ON audit_immutable
  FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = audit_immutable.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );