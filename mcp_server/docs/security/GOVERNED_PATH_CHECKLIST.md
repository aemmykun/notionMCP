# Governed Path Checklist

Use this checklist before declaring a request path production-governed.

## Identity

- `X-API-Key` resolves `workspace_id` server-side.
- Actor identity is never trusted from a public caller when `ACTOR_SIGNING_SECRET` is enabled.
- Signed actor headers include:
  - `X-Actor-Id`
  - `X-Actor-Type`
  - `X-Actor-Timestamp`
  - `X-Actor-Signature`
- Signature is HMAC-bound to `actor_id`, `actor_type`, `workspace_id`, and `timestamp`.
- Verification uses `hmac.compare_digest`.
- Timestamp age is enforced with `ACTOR_SIGNATURE_MAX_AGE_SECONDS`.

## Authorization

- Workspace isolation is enforced in SQL with `SET LOCAL app.workspace_id`.
- Actor context is projected into SQL when the path is governed.
- Authorization is enforced in SQL or secure views, not only in handler code.
- Missing context fails closed or is explicitly blocked in strict production mode.

## Audit

- Successful governed reads write curated metadata to `domain_events`.
- Matching append-only rows are written to `audit_immutable`.
- Audit payloads exclude raw request bodies.
- Audit payloads exclude returned record content.
- A stable `request_id` can be correlated across request, event, and audit rows.

## Runtime Safety

- `STRICT_PRODUCTION_MODE=1` is enabled for production redeploys.
- `production_preflight.py --strict` passes.
- `DEBUG`, `ALLOW_DEBUG_TRACEBACKS`, and `SKIP_NOTION_API` are disabled in production.
- Default database passwords are not present in runtime URLs.
- `ACTOR_SIGNING_SECRET` is set when governed stateless reads are exposed.

## Post-Deploy Proof

- Health endpoint returns `{"status": "ok"}`.
- One signed request succeeds on the live path.
- One matching `domain_events` row exists for that request.
- One matching `audit_immutable` row exists for that request.
- Stored payload shows curated metadata only.

## Current Governed Paths

- `resource.list`
- `rag.retrieve` when actor identity is supplied or strict signed mode is enabled
