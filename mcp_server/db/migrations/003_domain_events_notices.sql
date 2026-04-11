-- =============================================================================
-- 003_domain_events_notices.sql
-- Add notice fields to domain_events + audit_immutable
-- =============================================================================

-- domain_events notices (your primary event log)
ALTER TABLE domain_events 
  ADD COLUMN IF NOT EXISTS notice_type       TEXT,
  ADD COLUMN IF NOT EXISTS notice_title      TEXT,
  ADD COLUMN IF NOT EXISTS notice_description TEXT;

-- audit_immutable notices (your proof chain)  
ALTER TABLE audit_immutable 
  ADD COLUMN IF NOT EXISTS notice_type       TEXT,
  ADD COLUMN IF NOT EXISTS notice_title      TEXT,
  ADD COLUMN IF NOT EXISTS notice_description TEXT;

-- Indexes for workspace + notice filtering (Notion dashboard ready)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_domain_events_family_notice 
  ON domain_events (family_id, notice_type, created_at DESC)
  WHERE notice_type IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_immutable_family_notice 
  ON audit_immutable (family_id, notice_type, created_at DESC) 
  WHERE notice_type IS NOT NULL;

-- Permissions (mcp_app already has INSERT from migration 001)
GRANT SELECT, INSERT, UPDATE ON domain_events TO mcp_app;
GRANT SELECT, INSERT ON audit_immutable TO mcp_app;

-- RLS unchanged — notices inherit your existing family/workspace isolation
COMMENT ON COLUMN domain_events.notice_type IS 'Governance/policy notice type (PII_detected, approval_required)';
COMMENT ON COLUMN domain_events.notice_title IS 'Human-readable notice title';
COMMENT ON COLUMN domain_events.notice_description IS 'Detailed notice explanation for audit/Notion';
