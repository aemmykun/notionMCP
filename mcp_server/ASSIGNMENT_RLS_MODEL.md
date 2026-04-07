# Assignment And RLS Model

## Purpose

This document defines the recommended assignment-driven authorization model that should sit on top of the initial domain backbone.

The goal is to move from simple workspace-level isolation plus optional `child_id` checks toward explicit, SQL-backed authorization based on family scope, subject relationships, role assignments, and effective windows.

## Current State

The current repository authorizes RAG access through:

- `workspace_id` resolved from `X-API-Key`
- RLS on `rag_sources`, `rag_chunks`, and `rag_source_access`
- Optional `child_id` joins for source-level entitlement

This is secure, but it is not yet expressive enough for the original architecture.

## Recommended Assignment Model

### Core Principles

1. Tenant scope remains fail-closed and DB-enforced.
2. Family membership and role assignment are explicit tables, not implied strings.
3. Resource access is derived from assignments and policy resolution, not duplicated on every content row.
4. Effective windows are enforced in SQL wherever possible.
5. Secure views should become the main read surface for higher-level consumers.

## Recommended Tables

### `assignments`

Represents actor-to-scope authorization.

Suggested shape:

| Column | Purpose |
| --- | --- |
| `id` | Primary key |
| `family_id` | Root tenant boundary |
| `actor_id` | Human, service, or integration identity |
| `actor_type` | `user`, `service`, `integration`, `system` |
| `member_id` | Optional subject/member scope |
| `resource_id` | Optional resource scope |
| `department` | Optional department scope |
| `role` | Authorization role |
| `scope_type` | `family`, `member`, `resource`, `department` |
| `effective_from` / `effective_to` | Temporal authorization window |
| `status` | `active`, `revoked`, `expired` |
| `granted_by` | Who granted the assignment |
| `created_at` / `updated_at` | Audit timestamps |

### Optional `assignment_policies`

Represents attached rules or capabilities for a given assignment.

Suggested use:

- Fine-grained action allow/deny
- Precedence overrides
- Reason-code generation for denies

## Recommended Role Baseline

Use a small deterministic role vocabulary first:

| Role | Intended Capability |
| --- | --- |
| `family_admin` | Full family-level access and assignment management |
| `guardian` | Family/member access with policy restrictions |
| `case_manager` | Assigned-member operational access |
| `staff` | Limited operational access by department or resource |
| `viewer` | Read-only access |
| `service_agent` | Non-human integration access |

Do not expand roles until policy resolution semantics are fixed.

## RLS Strategy

### Layer 1: Tenant Boundary

All domain tables continue to enforce tenant scope through `families.workspace_id = current_setting('app.workspace_id')::uuid`.

This remains the outer fail-closed gate.

### Layer 2: Assignment Existence

Rows become visible only when an active assignment exists for the caller identity and the requested scope.

Conceptually:

```sql
EXISTS (
  SELECT 1
  FROM assignments a
  WHERE a.family_id = resources.family_id
    AND a.actor_id = current_setting('app.actor_id', true)
    AND a.status = 'active'
    AND (a.effective_from IS NULL OR a.effective_from <= NOW())
    AND (a.effective_to IS NULL OR a.effective_to >= NOW())
)
```

### Layer 3: Scope Resolution

The assignment must match one of these scopes:

- family-wide
- member-specific
- resource-specific
- department-specific

Order of specificity should be deterministic:

1. resource
2. member
3. department
4. family

More specific grants or denies should override broader ones when policy resolution is introduced.

### Layer 4: Resource Governance

Even with a valid assignment, resource governance still applies:

- `status`
- `legal_hold`
- `effective_from` / `effective_to`
- any future policy-derived deny state

This preserves the repo's current governance-first pattern.

## Secure View Strategy

Recommended views:

| View | Purpose |
| --- | --- |
| `v_family_current` | Family rows already filtered to current tenant |
| `v_member_current` | Members visible to current actor |
| `v_resource_authorized` | Resources visible after tenant, assignment, and governance checks |
| `v_resource_secure` | Resource data with sensitive fields masked or withheld |

Use views for consumer reads. Keep base tables for controlled server-side writes and audits.

## Session Context Requirements

The current repo sets only `app.workspace_id` in PostgreSQL.

The assignment model will require additional session context, likely:

- `app.actor_id`
- `app.actor_type`
- optionally `app.request_id`

The server should continue to set these with `SET LOCAL` inside the transaction boundary.

## Recommended Evolution From Current Repo

### Current

- `rag_source_access(source_id, child_id, role)`

### Transitional

- Keep `rag_source_access` for compatibility
- Introduce `assignments` for domain resources first
- Add compatibility views or translation logic where needed

### Target

- Use `assignments` as the primary authorization model
- Treat `rag_source_access` as legacy or a specialized projection of assignment data

## Non-Goals For The First Slice

Do not do these in the same first migration:

- full policy engine implementation
- attribute-based policy language
- deny/allow precedence across every domain table
- complete secure-view rollout for all consumers

The first slice should establish the model, not finish the entire authorization stack.

## Implementation Recommendation

When coding the next step:

1. Add an `assignments` table with family/member/resource scope and effective windows.
2. Extend the server's DB session context beyond `app.workspace_id` to include actor identity.
3. Introduce one secure view for resources before attempting broad policy rollout.
4. Only then refactor `rag_source_access` or integrate it into the assignment model.
