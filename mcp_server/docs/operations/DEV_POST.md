# Dev Post Draft — Notion MCP Governance Server

## Summary

Python MCP server that uses Notion as the data back end for governance workflows, with a governance-first RAG retrieval layer backed by PostgreSQL + pgvector.

## What it implements

### Governance tools (Notion back end)

- `policy.check` — query governance policy definitions
- `risk.score` — compute a risk score (0–100) based on category, amount, priority
- `audit.log` — write audit-grade entry with 8 required fields (Event, Timestamp, Request ID, Actor, Action, Outcome, Proof hash, Reason codes) + optional Policy version and Target
- `workflow.dispatch` — create a workflow task page in Notion with Request ID correlation
- `approval.request` — create a human approval request page in Notion with Request ID correlation

**Audit-Grade Features (v1.1):**

- **Request ID Threading**: Client passes `requestId` for workflow correlation, or server auto-generates
- **Event Format**: `"{action} — {outcome} — {target}"` (e.g., `payment.execute — deny — invoice:INV-001`)
- **3 Outcomes**: `success | deny | error` with deterministic validation rules
- **Fail-Safe**: REQUIRED reason codes on deny/error, auto-generated proof hashes

**Runtime hardening since v1.2/v1.3:**

- **Request guardrails**: 1 MB request body limit, 200-chunk ingest cap, 4 concurrent ingests by default
- **Multi-instance support**: Optional Redis-backed rate limiting with in-memory fallback when `REDIS_URL` is unset
- **Built-in observability**: Slow operations logged with request ID correlation using stdlib timing
- **Container hardening**: Localhost bind by default in Compose, read-only root FS, dropped caps, health checks, restart policy

### RAG tools (PostgreSQL + pgvector back end)

- `resource.list` — stateless authorized resource listing via `v_resource_authorized`
- `rag.retrieve` — governance-first vector retrieval: filters at source level before ranking chunks by cosine similarity
- `rag.ingest_source` — create a governance source record (`rag_sources`)
- `rag.ingest_chunks` — insert content chunks with embeddings (`rag_chunks`)

**Domain backbone since v1.4:**

- **Domain tables**: `families`, `members`, `resources`, `domain_events`, `audit_immutable`
- **Assignment model**: `assignments` table added as the authorization backbone
- **Secure views**: `v_family_current`, `v_member_current`, `v_resource_authorized`
- **Stateless resource access**: `resource.list` returns curated resource metadata only
- **Trusted stateless mode**: Optional `ACTOR_SIGNING_SECRET` enables signed actor header validation
- **Live SQL audit/event writes**: successful `resource.list` calls now append curated metadata to `domain_events` and `audit_immutable`
- **Signer helper**: `generate_actor_signature.py` emits signed `X-Actor-*` headers for trusted callers

**Authentication**: X-API-Key header (required for ALL tools). Server resolves `workspace_id` from API key using HMAC-SHA256—**never** from request body.

**Security Architecture**:

- HMAC-SHA256 authentication with server secret (prevents offline dictionary attacks)
- UUIDv5 workspace_id derivation (prevents tenant collision)
- `SET LOCAL app.workspace_id` in every transaction before SQL
- Row-Level Security (RLS) with deny-by-default policies
- WITH CHECK policies prevent cross-tenant write contamination
- FORCE ROW LEVEL SECURITY prevents table owner bypass
- Rate limiting: 60 requests/minute per API key
- Docker network isolation (Postgres not published to host)
- DB role `mcp_app` has NO `BYPASSRLS` and is NOT table owner
- ALL endpoints require authentication (no open surface)

### HTTP server (FastAPI, port 8080)

- `GET /health`
- `POST /call_tool/{tool_name}` — unified tool dispatch
- `GET /oauth/start` — generate Notion OAuth auth URL
- `GET /oauth/callback` — exchange code for tokens

## RAG architecture (locked)

```text
rag_sources        Single source of governance truth
                   Owns: workspace_id, status, visibility,
                         effective_from/to, legal_hold, retention_class
                   Retrieval filters here FIRST.

rag_chunks         Storage-oriented only.
                   Owns: id, source_id, content, embedding, position, token_count.
                   Inherits ALL governance via source_id → rag_sources.
                   Never add governance columns here.

rag_source_access  Per-child entitlement.
                   (source_id, child_id, role?)
                   Use instead of adding child columns to rag_chunks.
```

Retrieval invariant (never bypass):

1. Workspace isolation via RLS (enforced at DB level with `SET LOCAL app.workspace_id`)
2. `rs.status = 'published'`
3. `rs.legal_hold = FALSE`
4. effective window (`effective_from/to`)
5. optionally join `rag_source_access` when `child_id` is known
6. `ORDER BY rc.embedding <=> query_embedding` (cosine similarity)

**Critical**: `workspace_id` is **server-resolved** from the caller's X-API-Key header. It is NEVER accepted from the client request.

## New files

| File | Purpose |
| --- | --- |
| `schema.sql` | PostgreSQL + pgvector schema with RLS and DB role hardening |
| `rag.py` | Governance retrieval module (`retrieve`, `ingest_source`, `ingest_chunks`, `grant_access`, `revoke_access`) |
| `auth.py` | API key → workspace_id resolver (HMAC-SHA256 derivation with UUIDv5) |
| `.env.example` | Template for all required environment variables (includes `RAG_SERVER_SECRET` and `RAG_API_KEYS`) |
| `docker-compose.yml` | Production setup with internal network isolation |
| `migrations/001_domain_backbone.sql` | Domain backbone tables + baseline RLS |
| `migrations/002_assignments_and_secure_views.sql` | Assignment model + secure views |
| `test_rls_fail_closed.py` | RLS security validation (6 tests: fail-closed reads/writes, cross-workspace isolation, WITH CHECK, DB bypass protection, master test) |
| `test_production_security_proof.py` | Production validation proofs (2 tests: cross-workspace write contamination, owner bypass is dead) |
| `PRODUCTION_VALIDATION.md` | Final security validation guide before deployment |

## How to run locally

1. Create and activate a Python 3.11+ virtualenv:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

1. Copy `.env.example` to `.env` and fill in tokens, DB IDs, `RAG_DATABASE_URL`, `RAG_SERVER_SECRET`, and `RAG_API_KEYS`:

```powershell
Copy-Item .env.example .env

# Generate server secret
openssl rand -base64 32  # Add to .env as RAG_SERVER_SECRET

# Generate API key using the provided script
$env:RAG_SERVER_SECRET = "your-server-secret"
python generate_api_key.py "$(openssl rand -base64 32)" "$(openssl rand -base64 32)"
# Output includes HMAC hash to add to RAG_API_KEYS
```

1. Install dependencies:

```powershell
pip install -r requirements.txt
pip install -r dev-requirements.txt
```

1. (RAG only) Apply the schema to your PostgreSQL database:

```powershell
psql $env:RAG_DATABASE_URL -f schema.sql
```

1. Start the server:

```powershell
# Optional: suppress live Notion writes
# $env:SKIP_NOTION_API = "1"
python server.py
```

## Run tests

```powershell
# Unit tests — no DB or Notion required (31 tests)
python -m pytest test_server.py test_rag_session_context.py -v

# RLS security validation suite — requires RAG_DATABASE_URL (6 tests)
# Tests fail-closed reads, fail-closed writes, cross-workspace isolation,
# WITH CHECK enforcement, and direct DB access protection
python -m pytest test_rls_fail_closed.py -v

# Production validation proofs — requires RAG_DATABASE_URL (2 tests)
# Test #1: Cross-workspace write contamination blocked
# Test #2: Owner bypass is dead (FORCE RLS) — also needs RAG_DATABASE_OWNER_URL
# See PRODUCTION_VALIDATION.md for detailed guide
python -m pytest test_production_security_proof.py -v

# Audit acceptance test — validates Request ID threading and required audit fields
python test_request_id_threading.py

# Integration tests — server must be running on :8080
$env:RUN_INTEGRATION = "1"
$env:SKIP_NOTION_API = "1"   # omit to allow live Notion writes
python -m pytest integration_tests -q
```

Current verified surface:

- 37 focused unit tests passed (`test_server.py`, `test_rag_session_context.py`, `test_rag_resource_audit.py`)
- 4 integration tests passed (`integration_tests/test_integration.py`)
- Repository test inventory remains 46 automated tests total (37 focused/unit + 6 RLS + 2 production validation + 1 acceptance)

## Docker

```powershell
# Single container
docker build -t notion-mcp-server .
docker run --env-file .env -p 8080:8080 notion-mcp-server

# Docker Compose (recommended for production: includes Postgres + network isolation)
cd ..
docker compose up --build
```

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `NOTION_TOKEN` | Yes | Notion integration token |
| `GOVERNANCE_DB_ID` | Yes | Notion DB for policy definitions |
| `AUDIT_DB_ID` | Yes | Notion DB for audit events |
| `WORKFLOW_DB_ID` | Yes | Notion DB for workflow tasks |
| `APPROVAL_DB_ID` | Yes | Notion DB for approval requests |
| `RAG_DATABASE_URL` | For RAG tools | PostgreSQL + pgvector connection string |
| `RAG_SERVER_SECRET` | For RAG tools | Server secret for HMAC-SHA256 key derivation (generate with `openssl rand -base64 32`) |
| `RAG_API_KEYS` | For RAG tools | Comma-separated `hmac_sha256_hex:workspace_uuid` pairs (use `generate_api_key.py`) |
| `NOTION_OAUTH_CLIENT_ID` | OAuth only | Notion OAuth client ID |
| `NOTION_OAUTH_CLIENT_SECRET` | OAuth only | Notion OAuth client secret |
| `NOTION_OAUTH_REDIRECT_URI` | OAuth only | OAuth redirect URI |
| `SKIP_NOTION_API` | Dev/test | `1` = suppress live Notion writes |
| `DEBUG` | Dev | `1` = include tracebacks in 500 responses |
| `MCP_HTTP_MODE` | Dev | `1` = force HTTP server mode |
| `ACTOR_SIGNING_SECRET` | Optional security | HMAC secret for signed `X-Actor-*` headers |

## Notion setup

1. Create an integration at **Settings → Integrations** or register an OAuth app per Notion docs.
2. Share each database with the integration (open the DB → Share → invite your integration).
3. Copy the 32-character database IDs into `.env`. The server strips `?v=...` query strings automatically.

## Troubleshooting

- **`API token is invalid`** — verify `NOTION_TOKEN` in `.env`; ensure the integration has access to each database.
- **`RAG unavailable: RAG_DATABASE_URL is not set`** — add `RAG_DATABASE_URL` to `.env` and run `schema.sql`.
- **`cannot connect to the docker daemon`** — start Docker Desktop before building.
- **Integration test writes real data** — set `SKIP_NOTION_API=1` to test HTTP routing without writing to Notion.

## Security

- `.env` is in `.gitignore` — never commit tokens or secrets.
- Tool errors return HTTP 500 with a generic message. Set `DEBUG=1` locally to see tracebacks.
- For CI, use a dedicated sandbox Notion workspace and short-lived tokens stored in your CI provider's secrets manager.

## Packaging & next steps

- Add OAuth redirect host for real Notion integration.
- Publish Docker image to a container registry (tag with commit SHA).
- Add CI workflow: build image on PR, push on merge to main.
- Add RLS to `rag_sources` when server-side workspace enforcement is needed.
