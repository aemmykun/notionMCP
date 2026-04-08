# OpenAPI Specification

This directory contains auto-generated API documentation.

## Files

- **openapi.json** - OpenAPI 3.0 specification for the MCP server
  - Auto-generated from FastAPI application
  - Includes all tool endpoints and schemas
  - Can be viewed with Swagger UI or Redoc

## Viewing the Documentation

### Option 1: Swagger UI (Online)

1. Go to <https://editor.swagger.io/>
2. Click "File" → "Import File"
3. Select `openapi.json`

### Option 2: Redoc (Online)

1. Go to <https://redocly.github.io/redoc/>
2. Click "Try it out" in the top right
3. Paste the contents of `openapi.json`

### Option 3: FastAPI Built-in Docs (Local)

Start the server and visit:

- Swagger UI: <http://localhost:8080/docs>
- Redoc: <http://localhost:8080/redoc>

## Regenerating the Spec

If the API changes, regenerate with:

```powershell
cd mcp_server
.\venv\Scripts\Activate.ps1
python -c "from server import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
```

Or use the script:

```bash
python -c "from server import app; import json; spec = app.openapi(); print(json.dumps(spec, indent=2))" > openapi.json
```

## API Overview

The MCP server exposes these tool categories:

### Governance Tools

- `policy.check` - Validate actions against governance rules
- `risk.score` - Compute risk scores for pending actions
- `audit.log` - Record decisions and outcomes
- `workflow.dispatch` - Create operational tasks
- `approval.request` - Route to human approval

### RAG Tools

- `rag.retrieve` - Governed retrieval with actor authorization
- `rag.ingest_source` - Create governed source records
- `rag.ingest_chunks` - Ingest vector chunks

### Resource Tools

- `resource.list` - List authorized resources for actor
- `resource.get` - Get specific authorized resource

## Authentication

All protected endpoints require:

- `X-API-Key` header (workspace authentication)

Governed read endpoints may also require signed actor headers:

- `X-Actor-Id` - Actor identity
- `X-Actor-Type` - Actor type (user, service, etc.)
- `X-Actor-Timestamp` - Unix timestamp
- `X-Actor-Signature` - HMAC signature

See `CLIENT_INTEGRATION_MANUAL.md` for integration details.

---

**Last Updated**: Auto-generated on each server change  
**Spec Version**: OpenAPI 3.0.2  
**Server Version**: See RELEASE_NOTES.md
