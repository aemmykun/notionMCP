# Client Integration Manual

This manual explains how the MCP works in practice, what a frontend user can do with it, and what your frontend or backend-for-frontend must implement to use the full feature set safely.

## What This MCP Does

This server exposes two capability groups:

- governance tools for policy, risk, workflow, approval, and audit operations
- governed data tools for retrieval, ingestion, and authorized resource access

The main tools are:

- `policy.check`
- `risk.score`
- `audit.log`
- `workflow.dispatch`
- `approval.request`
- `rag.retrieve`
- `rag.ingest_source`
- `rag.ingest_chunks`
- `resource.list`
- `resource.get`

## The Core Rule

The frontend should not call this MCP directly from browser JavaScript in production.

Reasons:

- `X-API-Key` is required on protected endpoints
- governed read paths may require signed actor headers
- signing secrets must never be exposed to the browser
- request shaping and validation can be added more safely in a backend-for-frontend layer without changing the MCP core

The correct production shape is:

`browser -> your frontend app -> your backend/BFF -> MCP server`

This backend or BFF is a recommended production improvement around the MCP, not a separate layer already implemented inside this repository.

This repository now includes an additive example of that pattern in `frontend_bff.py`.

## How Identity Works

There are two identity layers in this MCP.

### 1. Workspace Identity

Every protected tool call requires `X-API-Key`.

The client never sends `workspace_id` directly. The server resolves it from the API key using server-side HMAC verification.

Frontend consequence:

- do not ask end users for `workspace_id`
- do not let the browser invent tenancy context
- keep the API key in your backend, not in browser code

### 2. Actor Identity

Governed read surfaces need an actor identity so authorization can be enforced in SQL.

These paths are:

- `resource.list`
- `resource.get`
- `rag.retrieve` when actor-aware governed mode is used

There are two operating modes:

- development mode: actor identity can be passed in the payload
- production governed mode: actor identity should be sent through signed headers

Signed actor headers are:

- `X-Actor-Id`
- `X-Actor-Type`
- `X-Actor-Timestamp`
- `X-Actor-Signature`

The signature is based on actor id, actor type, workspace id, and timestamp. That signing must be done by a trusted backend using `ACTOR_SIGNING_SECRET`.

## What A Frontend User Can Do

### Governance And Workflow

These tools support decision and review workflows:

- `policy.check`: ask whether a requested action matches governance rules
- `risk.score`: compute a risk score for a pending action
- `workflow.dispatch`: create an operational task in Notion
- `approval.request`: create a human approval item in Notion
- `audit.log`: explicitly record a decision or result

### Knowledge And Governed Data

These tools support governed retrieval and protected resource access:

- `rag.ingest_source`: create the governed source record
- `rag.ingest_chunks`: upload chunked content and embeddings
- `rag.retrieve`: search published, effective, non-held content
- `resource.list`: list only the resources the actor is authorized to see
- `resource.get`: fetch one resource without disclosing unauthorized existence

## What The Frontend Must Implement For Full Feature Use

To use the MCP fully, your frontend product should support the following capabilities.

### A. Session And User Identity

Your app should know:

- who the signed-in user is
- that user's internal actor id
- that user's actor type, if you distinguish user, admin, service, or system identities

Recommended UI behavior:

- require login before governed reads
- map app user identity to the actor identity sent to the MCP
- show the active actor in the UI for traceability

### B. Correlation And Traceability

The client should generate a `requestId` for a multi-step workflow and reuse it across related tool calls.

Example:

- user clicks `Submit purchase request`
- frontend creates one `requestId`
- backend uses that same `requestId` for `risk.score`, `policy.check`, `approval.request`, and `audit.log`

This allows the workflow to be traced end to end.

### C. Approval-Aware UX

Your frontend should not behave as if every action is immediate.

Recommended states:

- `allowed`
- `needs approval`
- `denied`
- `error`

Recommended screens:

- action review screen
- policy/risk result panel
- approval pending state
- audit or evidence panel for administrators

### D. Governed Retrieval UX

For `rag.retrieve`, your frontend needs to supply an embedding vector for the query.

That means your application needs an embedding service before calling this MCP. The MCP does not generate embeddings for you.

Recommended flow:

1. user types a search query
2. your backend creates the embedding using your model provider
3. your backend calls `rag.retrieve`
4. frontend renders the governed results

### E. Authorized Resource UX

For `resource.list` and `resource.get`, your frontend should assume access is actor-scoped and fail-closed.

Important behavior:

- `resource.get` returns `null` for absent or unauthorized resources
- this is intentional and prevents existence disclosure

Frontend implication:

- show `not available` or `not visible to your account`
- do not try to distinguish missing vs unauthorized in user-facing text

## Recommended Frontend Architecture

### Minimum Safe Architecture

- browser UI
- application backend or BFF
- MCP server

The backend or BFF should:

- store `X-API-Key`
- generate `requestId`
- sign actor headers when governed mode is enabled
- call MCP endpoints
- normalize MCP responses for the UI

In this repository, `frontend_bff.py` is an example implementation of that role. It adds browser-safe endpoints in front of the MCP without changing the MCP server itself.

### What Should Not Live In The Browser

- `X-API-Key`
- `ACTOR_SIGNING_SECRET`
- Cloudflare tunnel tokens
- direct tenant or workspace trust decisions

## Tool By Tool UI Guidance

### `policy.check`

Use when the user is about to do something sensitive.

Frontend fields:

- actor
- action
- context object

Good uses:

- pre-submit validation
- governance banner before execution

### `risk.score`

Use when the UI needs a severity or escalation number.

Frontend fields:

- actor
- category
- amount
- priority

Good uses:

- payment or expense flows
- priority escalation
- review thresholds

### `workflow.dispatch`

Use when an action becomes an operational task.

Frontend fields:

- actor
- type
- title
- description
- priority
- metadata

Good uses:

- create work item after policy pass
- create task after user confirmation

### `approval.request`

Use when the action needs a human checkpoint.

Frontend fields:

- actor
- subject
- reason
- riskScore
- relatedWorkflowId

Good uses:

- manager approval
- regulated content release
- high-value transaction approval

### `audit.log`

Use when your application wants explicit evidence beyond automatic logging.

Frontend fields:

- actor
- action
- input
- output
- policyApplied
- riskScore
- requestId

Good uses:

- log denials
- log operator overrides
- log external system outcomes

### `rag.ingest_source`

Use when content enters the governed knowledge base.

Frontend or admin console should collect:

- name
- status
- visibility
- effective dates
- legal hold
- retention class

### `rag.ingest_chunks`

Use after a source exists and chunk embeddings are ready.

Frontend implication:

- this usually belongs in an admin console, sync worker, or ingestion pipeline
- not in a normal end-user browsing screen

### `rag.retrieve`

Use when the user asks a knowledge question.

Frontend or backend should provide:

- `query_embedding`
- optional `top_k`
- optional `requestId`
- actor identity in governed mode

### `resource.list`

Use when the UI needs a listing page of allowed resources.

Frontend or backend should provide:

- actor identity
- optional member filter
- optional resource type filter
- optional limit
- request id for traceability

### `resource.get`

Use when the UI needs a details page for a single protected resource.

Frontend or backend should provide:

- actor identity
- resource id
- request id

## HTTP Usage Pattern

The server exposes REST-style endpoints as well as MCP transport.

Main REST groups:

- `/call_tool/{tool_name}` for governance and workflow tools
- `/rag_tool/{tool_name}` for governed retrieval and resource tools

Required header:

```http
X-API-Key: <tenant-api-key>
```

Governed production reads also require signed actor headers.

## Example Backend Calls

### Policy Check

```json
POST /call_tool/policy.check
{
  "actor": "user-123",
  "action": "invoice.approve",
  "context": {
    "amount": 12500,
    "department": "finance"
  }
}
```

### Approval Request

```json
POST /call_tool/approval.request
{
  "actor": "user-123",
  "subject": "Invoice approval required",
  "reason": "Amount exceeds auto-approval threshold",
  "riskScore": 82,
  "relatedWorkflowId": "wf-001"
}
```

### Governed Resource List

Development payload mode:

```json
POST /rag_tool/resource.list
{
  "actorId": "user-123",
  "actorType": "user",
  "resourceType": "document",
  "limit": 25,
  "requestId": "f345aa9d-bf7d-4b15-9b7a-4464db8b7e92"
}
```

Production signed-header mode:

- body can omit `actorId` if your trusted caller sets signed actor headers and the server injects the actor identity
- your backend still needs to know which user it is acting for

### Governed Resource Get

```json
POST /rag_tool/resource.get
{
  "actorId": "user-123",
  "actorType": "user",
  "resourceId": "resource-uuid",
  "requestId": "f345aa9d-bf7d-4b15-9b7a-4464db8b7e92"
}
```

### Governed Retrieval

```json
POST /rag_tool/rag.retrieve
{
  "query_embedding": [0.12, 0.43, 0.98],
  "top_k": 5,
  "requestId": "f345aa9d-bf7d-4b15-9b7a-4464db8b7e92"
}
```

## MCP Client Pattern

If your app uses MCP directly through the `/mcp` endpoint, the same rules still apply:

- the transport still needs `X-API-Key`
- governed read tools still require actor identity
- rate limiting still applies
- request correlation still matters

The MCP tool list currently includes all governance and governed-read tools, so a chat client or AI agent can call them if your transport layer injects the required headers safely.

## Frontend Features Needed For Full Usage

If you want the frontend to use the MCP completely, make sure your product includes:

- user authentication in your app
- backend-held tenant API key
- actor identity mapping from user session to MCP actor
- signed actor-header support in the backend for governed production mode
- request ID generation and reuse across a workflow
- embedding generation for search
- workflow and approval UI states
- admin or operator UI for ingestion and audit review
- graceful handling of `401`, `422`, `429`, and `null` governed-read responses

## Error Handling Rules For The Frontend

- `401`: authentication missing, invalid API key, or invalid signed actor context
- `422`: missing required field or invalid request shape
- `429`: rate limit exceeded, retry later
- `500`: dependency or server failure
- `resource: null`: treat as not visible or not available

Do not expose raw backend security detail to end users. Show a user-safe message and record the technical detail in your app logs.

## Best Practice Summary

- keep secrets in the backend
- treat browser clients as untrusted
- use one `requestId` across a workflow
- use approval flows, not only auto-execution
- use signed actor propagation for governed reads in production
- use `resource.list` and `resource.get` as the protected browsing surface
- use `rag.retrieve` only after generating embeddings outside the MCP
- keep operator infrastructure separate from product UX

## Related Files

- `openapi.yaml`
- `server.py`
- `frontend_bff.py`
- `auth.py`
- `rag.py`
- `GOVERNED_PATH_CHECKLIST.md`
- `RELEASE_NOTES.md`
