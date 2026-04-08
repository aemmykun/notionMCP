-- sql.dialect=PostgreSQL
-- =============================================================================
-- Assignments And Secure Views
--
-- Purpose:
--   Add assignment-driven authorization primitives and one secure resource view.
--
-- Prerequisites:
--   1. Apply schema.sql
--   2. Apply migrations/001_domain_backbone.sql
--
-- Session context expected:
--   - app.workspace_id (already present in current repo)
--   - app.actor_id (new, optional until app integration lands)
--   - app.actor_type (new, optional until app integration lands)
-- =============================================================================

-- =============================================================================
-- assignments
-- =============================================================================

CREATE TABLE IF NOT EXISTS assignments (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families (id) ON DELETE CASCADE,
  actor_id        TEXT NOT NULL,
  actor_type      TEXT NOT NULL DEFAULT 'user'
                  CHECK (actor_type IN ('user', 'service', 'integration', 'system')),
  member_id       UUID REFERENCES members (id) ON DELETE CASCADE,
  resource_id     UUID REFERENCES resources (id) ON DELETE CASCADE,
  department      TEXT,
  role            TEXT NOT NULL,
  scope_type      TEXT NOT NULL
                  CHECK (scope_type IN ('family', 'member', 'resource', 'department')),
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'revoked', 'expired')),
  effective_from  TIMESTAMPTZ,
  effective_to    TIMESTAMPTZ,
  granted_by      TEXT,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT assignments_effective_window_order
    CHECK (effective_from IS NULL OR effective_to IS NULL OR effective_from < effective_to),
  CONSTRAINT assignments_scope_presence
    CHECK (
      (scope_type = 'family' AND member_id IS NULL AND resource_id IS NULL AND department IS NULL)
      OR (scope_type = 'member' AND member_id IS NOT NULL AND resource_id IS NULL)
      OR (scope_type = 'resource' AND resource_id IS NOT NULL)
      OR (scope_type = 'department' AND department IS NOT NULL AND resource_id IS NULL)
    )
);

DROP TRIGGER IF EXISTS trg_assignments_updated_at ON assignments;
CREATE TRIGGER trg_assignments_updated_at
  BEFORE UPDATE ON assignments
  FOR EACH ROW EXECUTE FUNCTION domain_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_assignments_family_actor
  ON assignments (family_id, actor_id, status);

CREATE INDEX IF NOT EXISTS idx_assignments_resource_actor
  ON assignments (resource_id, actor_id)
  WHERE resource_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assignments_member_actor
  ON assignments (member_id, actor_id)
  WHERE member_id IS NOT NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON assignments TO mcp_app;

ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS assignments_workspace_isolation ON assignments;
CREATE POLICY assignments_workspace_isolation
  ON assignments
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = assignments.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

DROP POLICY IF EXISTS assignments_workspace_write ON assignments;
CREATE POLICY assignments_workspace_write
  ON assignments
  FOR ALL
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM families f
      WHERE f.id = assignments.family_id
        AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    )
  );

-- =============================================================================
-- Secure views
-- =============================================================================

CREATE OR REPLACE VIEW v_family_current
WITH (security_barrier = true) AS
SELECT
  f.id,
  f.workspace_id,
  f.family_key,
  f.name,
  f.status,
  f.billing_state,
  f.created_at,
  f.updated_at
FROM families f
WHERE f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid;

CREATE OR REPLACE VIEW v_member_current
WITH (security_barrier = true) AS
SELECT
  m.id,
  m.family_id,
  m.external_key,
  m.display_name,
  m.member_type,
  m.relationship,
  m.department,
  m.status,
  m.date_of_birth,
  m.created_at,
  m.updated_at
FROM members m
WHERE EXISTS (
  SELECT 1
  FROM assignments a
  JOIN families f ON f.id = a.family_id
  WHERE a.family_id = m.family_id
    AND a.status = 'active'
    AND a.actor_id = nullif(current_setting('app.actor_id', true), '')
    AND (a.effective_from IS NULL OR a.effective_from <= NOW())
    AND (a.effective_to IS NULL OR a.effective_to >= NOW())
    AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
    AND (
      a.scope_type = 'family'
      OR (a.scope_type = 'member' AND a.member_id = m.id)
      OR (a.scope_type = 'department' AND a.department = m.department)
    )
);

CREATE OR REPLACE VIEW v_resource_authorized
WITH (security_barrier = true) AS
SELECT
  r.id,
  r.family_id,
  r.member_id,
  r.source_id,
  r.resource_type,
  r.name,
  r.status,
  r.visibility,
  r.classification,
  r.effective_from,
  r.effective_to,
  r.retention_class,
  r.created_at,
  r.updated_at
FROM resources r
WHERE r.status IN ('draft', 'active')
  AND r.legal_hold = FALSE
  AND (r.effective_from IS NULL OR r.effective_from <= NOW())
  AND (r.effective_to IS NULL OR r.effective_to >= NOW())
  AND EXISTS (
    SELECT 1
    FROM assignments a
    JOIN families f ON f.id = a.family_id
    LEFT JOIN members m ON m.id = r.member_id
    WHERE a.family_id = r.family_id
      AND a.status = 'active'
      AND a.actor_id = nullif(current_setting('app.actor_id', true), '')
      AND (a.effective_from IS NULL OR a.effective_from <= NOW())
      AND (a.effective_to IS NULL OR a.effective_to >= NOW())
      AND f.workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
      AND (
        a.scope_type = 'family'
        OR (a.scope_type = 'resource' AND a.resource_id = r.id)
        OR (a.scope_type = 'member' AND a.member_id = r.member_id)
        OR (a.scope_type = 'department' AND m.department IS NOT NULL AND a.department = m.department)
      )
  );

GRANT SELECT ON v_family_current TO mcp_app;
GRANT SELECT ON v_member_current TO mcp_app;
GRANT SELECT ON v_resource_authorized TO mcp_app;