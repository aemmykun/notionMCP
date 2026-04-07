# Schema Migration Plan

## Purpose

This plan defines how to evolve the current repository from a secure governance-first RAG service into the broader architecture described by the original reference model.

It assumes three constraints:

1. The current RAG schema and tests must remain valid during transition.
2. `workspace_id` remains the active compatibility boundary until actor/family modeling is wired end-to-end.
3. DB-enforced security remains the default design principle.

## Current Baseline

The current production-safe baseline is:

- `rag_sources`
- `rag_chunks`
- `rag_source_access`
- Notion-backed audit/workflow/approval flows
- server-resolved `workspace_id`
- RLS with `SET LOCAL app.workspace_id`

## Migration Objectives

The target architecture adds:

- explicit family/domain entities
- explicit member records
- generalized resources
- immutable SQL-backed events and audit
- assignment-driven authorization
- secure views for higher-level consumers

## Phase Order

## Phase 1: Domain Backbone

Status: implemented as an initial migration artifact in [migrations/001_domain_backbone.sql](c:/Users/arthi/notion%20mcp/mcp_server/migrations/001_domain_backbone.sql)

Scope:

- create `families`
- create `members`
- create `resources`
- create `domain_events`
- create `audit_immutable`
- apply baseline grants and RLS compatible with the current `workspace_id` model

Why first:

- establishes explicit domain anchors
- preserves current tenant isolation model
- enables future app logic without destabilizing current RAG retrieval

## Phase 2: Assignment-Driven Authorization

Scope:

- create `assignments`
- extend DB session context to include actor identity
- add assignment-aware RLS or secure views for resources and members
- keep `rag_source_access` temporarily for compatibility

Primary design reference: [ASSIGNMENT_RLS_MODEL.md](c:/Users/arthi/notion%20mcp/mcp_server/ASSIGNMENT_RLS_MODEL.md)

Key migration rule:

- do not remove current workspace-based RLS until assignment-based authorization is fully validated

## Phase 3: Application Integration

Scope:

- map current MCP operations to family/member/resource concepts
- begin writing SQL-backed `domain_events`
- mirror or dual-write audit-relevant actions into `audit_immutable`
- keep Notion as an outward workflow/audit integration surface during transition

Why before policy refactor:

- the domain model and audit backbone must exist before deeper policy semantics can be trusted

## Phase 4: Policy Resolution Upgrade

Scope:

- formalize action/resource policy evaluation
- introduce precedence and conflict resolution semantics
- connect policies to assignments, resources, and member scopes
- generate deterministic deny reasons and versioned policy references

## Phase 5: Compatibility Cleanup

Scope:

- deprecate legacy access patterns where appropriate
- evaluate whether `rag_source_access` becomes a compatibility projection or can be retired
- make secure views the preferred consumer read path
- reduce duplicated authorization logic in Python

## Data Mapping Strategy

### Workspace To Family

Current state:

- one `workspace_id` governs all accessible RAG data

Migration mapping:

- one `families.workspace_id` row becomes the compatibility anchor for a tenant boundary

This allows existing auth and RLS behavior to continue while richer domain objects are introduced.

### RAG Sources To Resources

Current state:

- `rag_sources` acts as both a governance source and the nearest thing to a protected resource

Migration mapping:

- `resources.source_id` allows a generalized domain resource to reference an existing `rag_sources` record

This avoids forcing an unsafe one-shot replacement.

### Notion Audit To SQL Audit

Current state:

- audit evidence is written to Notion

Migration mapping:

- add SQL-backed `domain_events` and `audit_immutable`
- begin dual-write before treating SQL audit as canonical

## Operational Rules During Migration

1. Never remove current RLS protections before equivalent or stronger replacements exist.
2. Keep new tables additive before making destructive schema changes.
3. Prefer dual-write or mirrored-read transitions over big-bang cutovers.
4. Validate each phase with explicit integration tests, especially cross-tenant and cross-assignment access tests.
5. Treat append-only audit behavior as non-negotiable.

## Test Plan By Phase

### Phase 1 Tests

- family/member/resource insert and isolation tests
- audit_immutable append-only tests
- workspace-bound RLS tests on new tables

### Phase 2 Tests

- assignment effective-window tests
- actor scope tests by family/member/resource/department
- deny-by-default tests when actor context is missing

### Phase 3 Tests

- dual-write audit parity tests
- MCP request-to-domain event mapping tests
- regression coverage for current RAG endpoints

### Phase 4 Tests

- policy precedence tests
- conflict resolution tests
- reason-code determinism tests

## Recommended Immediate Next Coding Step

After the initial backbone migration, the best next code change is:

1. add the `assignments` table
2. extend the DB session context to include actor identity
3. implement one secure resource view backed by assignment-aware SQL

That is the narrowest next slice that materially advances the architecture without destabilizing the existing production-safe base.
