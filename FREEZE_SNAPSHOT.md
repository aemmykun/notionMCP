# Repository Snapshot - April 6, 2026

## Repository State

- Status: Production-ready core plus v1.4 domain backbone and stateless authorization
- Version: 1.4
- Current focus: domain-aligned secure reads, signed actor identity, and live SQL audit/event writes

## v1.4 Summary

1. Domain backbone migrations are in place.
   - `migrations/001_domain_backbone.sql` adds `families`, `members`, `resources`, `domain_events`, and append-only `audit_immutable`.
   - `migrations/002_assignments_and_secure_views.sql` adds `assignments` plus `v_family_current`, `v_member_current`, and `v_resource_authorized`.

2. Stateless resource authorization is live.
   - `resource.list` reads only from `v_resource_authorized`.
   - `workspace_id` is resolved from `X-API-Key`.
   - Actor identity can be verified with signed `X-Actor-*` headers when `ACTOR_SIGNING_SECRET` is configured.

3. Curated SQL audit/event writes are live.
   - Successful `resource.list` calls now append metadata to `domain_events`.
   - Matching append-only records are written to `audit_immutable`.
   - Stored payloads contain filters and result counts only, not raw request bodies or returned resource rows.

4. Trusted caller tooling was added.
   - `generate_actor_signature.py` generates signed `X-Actor-Id`, `X-Actor-Type`, and `X-Actor-Signature` headers.
   - `rag.retrieve` now supports the governed signed/audited path when actor identity is supplied.
   - `GOVERNED_PATH_CHECKLIST.md` defines the production-governed route criteria.
   - `minimal_load_test.py` provides a small concurrent health/governed-read test harness.

## Verification Completed Today

- Focused unit suite passed: 47 tests.
- Integration suite passed: 4 tests.
- Live HTTP verification passed against the Dockerized stack.
- Matching `domain_events` and `audit_immutable` rows were confirmed in the live `notion_mcp` database for the same `request_id`.

## Runtime Shape

### Security

- HMAC-SHA256 API key authentication
- UUIDv5 workspace derivation
- Row-Level Security with fail-closed behavior
- `FORCE ROW LEVEL SECURITY` enabled
- Optional signed actor headers for stateless trust boundaries
- Curated immutable audit trail for successful `resource.list` reads

### Operations

- Docker Compose binds MCP to `127.0.0.1:8080`
- Postgres remains internal to the Compose network
- Optional Redis-backed rate limiting for multi-instance deployments
- Request size, ingest batch, concurrency, and timeout guardrails are in place

## Key Files Carrying the Current State

- `mcp_server/server.py`
- `mcp_server/rag.py`
- `mcp_server/generate_actor_signature.py`
- `mcp_server/migrations/001_domain_backbone.sql`
- `mcp_server/migrations/002_assignments_and_secure_views.sql`
- `mcp_server/test_server.py`
- `mcp_server/test_rag_session_context.py`
- `mcp_server/test_rag_resource_audit.py`
- `mcp_server/integration_tests/test_integration.py`
- `mcp_server/README.md`
- `mcp_server/PRODUCTION_VALIDATION.md`
- `mcp_server/RELEASE_NOTES.md`
- `mcp_server/DEV_POST.md`

## Current Test Inventory

- Focused/unit: 47
- RLS validation: 6
- Production validation proofs: 2
- Audit acceptance: 1
- Integration: 4

Current verified runs in this cycle:

- 47 focused/unit tests passed
- 4 integration tests passed

## Deployment Notes

1. Apply `schema.sql` first.
2. Apply `migrations/001_domain_backbone.sql`.
3. Apply `migrations/002_assignments_and_secure_views.sql`.
4. If using trusted stateless mode, set `ACTOR_SIGNING_SECRET` and sign `X-Actor-*` headers.
5. For horizontal scaling, set `REDIS_URL` and validate shared rate limiting.

## Remaining Follow-On Work

1. Extend live `domain_events` and `audit_immutable` writes to additional request paths beyond `resource.list`.
2. Decide whether payload actor fallback should remain available outside local/dev mode.
3. Re-run the full RLS and production proof suites after the next schema-affecting change.
