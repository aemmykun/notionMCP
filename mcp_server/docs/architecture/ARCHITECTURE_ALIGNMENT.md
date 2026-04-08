# Architecture Alignment

## Purpose

This document maps the current repository implementation to the original architecture provided by the user and defines the target direction for future implementation decisions.

The original architecture is treated as the richer reference model. The current repository is treated as a constrained implementation slice focused on governance-first RAG, Notion-backed workflow, approval, and audit operations.

## Current Implemented Architecture

### Database Model

The current PostgreSQL schema is intentionally narrow and centered on RAG governance:

| Current Table | Role |
| --- | --- |
| `rag_sources` | Source-level governance truth for retrieval |
| `rag_chunks` | Storage-only vector chunks linked to `rag_sources` |
| `rag_source_access` | Optional per-child entitlement table |

### Security Model

The current repository already follows several of the same architectural instincts as the original design:

- Workspace identity is server-resolved from `X-API-Key`, never client-supplied
- PostgreSQL Row-Level Security is enabled and forced on all RAG tables
- `SET LOCAL app.workspace_id` is required for every scoped DB transaction
- Write-path isolation is enforced with `WITH CHECK` policies
- Table-owner bypass is blocked with `FORCE ROW LEVEL SECURITY`
- Audit correlation is request-scoped through `requestId`

### Application Surface

The current server exposes two main capability groups:

| Surface | Current Tools |
| --- | --- |
| Governance / workflow | `policy.check`, `risk.score`, `audit.log`, `workflow.dispatch`, `approval.request` |
| RAG | `rag.retrieve`, `rag.ingest_source`, `rag.ingest_chunks` |

### Audit Model

Audit behavior is present, but implemented through Notion audit records rather than an immutable SQL event ledger.

Current audit guarantees include:

- Request ID correlation across calls
- Explicit timestamping
- Outcome classification: `success`, `deny`, `error`
- Reason code capture for negative outcomes
- Proof hash generation

## Original Architecture Reference Model

From the provided architecture screenshot, the broader intended domain appears to include:

| Reference Area | Intended Role |
| --- | --- |
| `families` | Root tenant or household boundary |
| `members` | Child/person records within a family |
| `billing` | Financial/account state tied to family context |
| `assignments` | Role/time-scoped actor-to-subject access relationships |
| `resources` | Protected domain resources with policy and lifecycle fields |
| `events` | Domain event capture |
| `audit_immutable` | Append-only evidence-grade audit trail |
| policy tables/views | Deterministic rule resolution and conflict handling |
| secure views | Query surface constrained by authorization and crypto policy |

## Alignment Summary

### What Already Aligns

The current repository already matches the reference architecture in these important ways:

1. It prefers DB-enforced security invariants over application-only checks.
2. It treats access control as data-backed policy rather than ad hoc conditionals.
3. It uses fail-closed behavior when required context is missing.
4. It separates governance metadata from storage payloads.
5. It treats audit as a first-class operational concern.

### What Is Missing

The current repository does not yet implement the full domain model implied by the original architecture.

#### Missing Core Domain Tables

- `families`
- `members`
- `billing`
- `resources` as a domain entity distinct from RAG sources
- `events` as SQL-backed operational records
- `audit_immutable` as an append-only SQL ledger
- assignment/role tables for actor-to-subject authorization

#### Missing Authorization Semantics

- Family-scoped access boundaries beyond generic workspace isolation
- Department, member, and role-based authorization rules
- Time-bounded assignments and effective windows for personnel access
- Secure-view driven query surfaces for downstream consumers

#### Missing Policy Engine Depth

- Priority-based policy evaluation in the database layer
- Conflict resolution rules with deterministic precedence
- Central policy materialization for resource/action decisions
- Policy-to-assignment joins as a standard enforcement path

#### Missing Audit Immutability

- Append-only SQL audit ledger
- Database-level immutability controls for audit rows
- Event partitioning or retention strategy at the SQL layer
- Tamper-evident audit proof chain enforced beyond application logic

## Recommended Interpretation For This Repo

The current repository should be treated as:

- A governance-first MCP service
- A secure RAG and workflow gateway
- An implementation slice, not the full target domain model

The original architecture should be treated as:

- The domain target
- The source of truth for schema evolution decisions
- The baseline for future authorization and audit design

## Decision Rules Going Forward

When extending this repository, prefer the following:

1. Add new domain concepts as explicit tables rather than hidden JSON blobs in Notion records.
2. Put security invariants in PostgreSQL when feasible, especially tenancy, assignments, and immutable audit behavior.
3. Keep storage tables inheritance-based and avoid duplicating governance columns into lower-level content tables.
4. Treat role assignment and policy resolution as first-class schema concerns.
5. Preserve fail-closed behavior whenever authorization context is missing.
6. Prefer append-only event capture for security-relevant actions.
7. Use views or narrowly scoped query functions for consumer-safe read surfaces.

## Gap Map

| Area | Current State | Reference Direction | Priority |
| --- | --- | --- | --- |
| Tenant boundary | `workspace_id` | family/tenant domain boundary | High |
| Subject modeling | optional `child_id` string | explicit `members` table | High |
| Access control | `rag_source_access` | assignment and role tables | High |
| Resource model | `rag_sources` only | generalized `resources` + content linkage | High |
| Audit | Notion-backed audit records | immutable SQL audit ledger | High |
| Events | ad hoc workflow/audit calls | explicit domain event table | Medium |
| Billing | absent | family billing model | Medium |
| Secure views | absent | DB-backed authorized views | Medium |
| Policy resolution | basic app logic | SQL-backed precedence engine | High |

## Recommended Implementation Order

### Phase 1: Domain Backbone

- Introduce explicit root entities such as `families`, `members`, and `resources`
- Define foreign-key relationships between current RAG sources and future domain resources
- Preserve current `workspace_id` behavior as a compatibility boundary during migration

### Phase 2: Access Control Upgrade

- Replace or formalize `rag_source_access` into assignment-driven authorization
- Model actor roles, family relationships, departments, and date-bounded assignments
- Expose authorization through secure views or centrally owned SQL functions

### Phase 3: Audit and Events

- Add SQL-backed `events` and `audit_immutable` tables
- Keep Notion audit writes as an integration/output layer rather than the only audit store
- Enforce append-only behavior in the database

### Phase 4: Policy Resolution

- Move from simple app-side policy matching toward deterministic rule resolution
- Add policy precedence, scope, and conflict-resolution semantics
- Make policy evaluation reusable across workflow, approval, resources, and retrieval

## Immediate Next Build Slice

If implementation starts from this alignment, the most defensible first slice is:

1. Add explicit domain tables for `families`, `members`, and `resources`
2. Introduce assignment-based access control at the SQL layer
3. Add an immutable SQL audit/event backbone

That sequence improves architectural integrity without discarding the current secure RAG foundation.
