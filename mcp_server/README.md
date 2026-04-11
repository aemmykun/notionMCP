# Notion MCP by TenantSage Governor

> A governed MCP server for Notion operations, approval flows, audit records, and secure retrieval, exposed for any AI client that can use MCP.

## What This Repo Is

This repository is the environment-specific implementation of a TenantSage governance design.

The blueprint is the base: governed execution, approval-aware actions, auditable evidence, and secure retrieval boundaries.

This repo is the working design built for the current environment:

- Notion as the operations surface for governance, audit, workflow, and approval records
- MCP and HTTP endpoints as the tool interface
- PostgreSQL plus pgvector as the governed retrieval layer
- server-side authentication, request correlation, and policy-aware routing

In practical terms, this is not just a generic MCP server. It is a governed MCP backend that uses Notion as its operational system of record and can be called by any AI assistant, agent, or application that supports MCP.

## MCP For Any AI

The Notion part explains the backend model. The MCP part explains who can use it.

Any AI client that can call MCP tools can use this server as a governed execution and retrieval layer.

That includes:

- AI assistants that need policy-aware actions
- agent frameworks that need approval and audit steps
- custom copilots that need governed retrieval
- automation layers that need a structured MCP surface instead of direct database or Notion access

So the repo should be read like this:

- Notion provides the four operational data templates used by the server
- PostgreSQL provides the governed retrieval boundary
- MCP provides the interface any AI system can use

## How The Repo Works

The repo has two operating layers.

- Notion layer: four Notion data templates hold operational records used by the governance tools
- PostgreSQL layer: governed RAG and authorised resource access are enforced at the database boundary

The server receives a tool call, authenticates the caller, resolves workspace context, and then routes the request to the correct backend.

- Governance and policy reads go to the Governance template
- Explicit audit writes go to the Audit template
- Operational task creation goes to the Workflow template
- Human review requests go to the Approval template
- Governed retrieval and resource reads go to PostgreSQL with session-scoped context and RLS enforcement

## Four Notion Data Templates

This repo depends on four Notion database templates. They are part of how the application works in this implementation, not optional marketing examples.

1. Governance template
Maps to `GOVERNANCE_DB_ID`.
Used for policy definitions and governance decisions such as `policy.check`.

2. Audit template
Maps to `AUDIT_DB_ID`.
Used for audit-grade records so actions and outcomes can be reviewed later.

3. Workflow template
Maps to `WORKFLOW_DB_ID`.
Used for workflow dispatch and operational task tracking.

4. Approval template
Maps to `APPROVAL_DB_ID`.
Used for human approval requests when an action should not auto-execute.

## Why This Structure Exists

The goal is to make the repo easy to understand:

- Notion handles the business-facing operational records
- PostgreSQL handles governed retrieval and data-boundary enforcement
- the server sits between them as the controlled execution layer
- MCP makes that controlled execution layer usable by any AI client

That is the main design idea behind this repository.

## Problem

AI systems can draft, retrieve, decide, and act quickly, but most operating teams still need answers to basic governance questions:

- Who allowed this action?
- Why was it allowed?
- What happens when risk is high?
- Can we prove what the system did later?
- Can we expose this safely to clients or regulated operators?

Without a governance layer, the answer is usually process, trust, and manual cleanup.

## Solution Shape

This repository implements a governed execution layer for Notion-backed operations and MCP-based AI workflows.

At the system level, it provides:

- policy-gated decisions before execution
- approval routing for actions that should not auto-run
- audit and workflow records in Notion
- a controlled path for governed retrieval and authorised resource access
- an operator-managed deployment shape for production use

## Buyer Outcome

The intended outcome is not just another MCP server.

It is a way to package AI workflows so a buyer can say:

- the AI does not act outside defined policy
- risky actions can be routed to human approval
- evidence exists for what happened and why
- access to governed resources is authorised, not assumed
- production exposure can be handled through operator-managed infrastructure
- the system can be presented as governed operations, not uncontrolled automation

## Who This Fits

This proposal is aimed at:

- Notion consultants and implementation partners
- agencies delivering AI-enabled operations to clients
- founders building governed AI workflow products
- regulated or compliance-sensitive teams using Notion as an operations surface
- operators who need reviewable, approval-aware automation rather than blind execution

## Scope Of The Proposal

The repository currently represents these proposal pillars:

- governed policy evaluation
- approval-aware workflow control
- audit-grade evidence capture
- governed and authorised resource access
- production-oriented deployment boundary

This means the repo is suitable as:

- a starter kit for governed AI operations
- a sales/architecture proof point
- a delivery base for implementation work
- a bridge toward TenantSage-style advanced governed execution

## Packaging Position

The repo should be understood in two layers:

- Product layer: the MCP application and governance model
- Operator layer: production deployment, public exposure, and infrastructure operations

This distinction matters commercially.

The sellable runtime package is the governed MCP application. Infrastructure concerns such as public tunnel exposure, DNS, connector services, and operator secrets belong to the operator layer and should not be treated as part of the product artifact.

## Commercial Framing

The proposal supports multiple delivery modes:

- open technical starter kit
- consultant implementation base
- governed AI operations template
- advanced multi-tenant migration path

It can be framed as:

- a governed AI workflow starter
- an approval-and-audit layer for Notion operations
- a trust layer for client-facing automations
- a constitutional bridge toward more advanced TenantSage deployment models

## What README Covers

This README intentionally stays at proposal level.

It is for:

- value proposition
- scope
- positioning
- buyer outcome
- packaging boundary

It is not the canonical source for:

- endpoint inventory
- runtime setup
- environment variables
- deployment instructions
- tunnel operations
- release-by-release implementation detail
- testing inventory

## Canonical Technical Sources

Technical and operational details live in:

- `RELEASE_NOTES.md` for implementation changes, production state, and technical evolution
- `CLIENT_INTEGRATION_MANUAL.md` for frontend, MCP client, and full-feature usage guidance
- `OPERATIONS.md` for day-to-day operations, backup/restore, API key rotation, monitoring
- `../ops/cloudflare/REMOTE_TUNNEL_RUNBOOK.md` for operator-managed public tunnel procedures
- in-repo source and test files for implementation specifics

## Quality Assurance

QA reports and assessment documentation:

- `../QA_ENGINEERING_REPORT.md` - Comprehensive technical audit (50+ pages)
- `../EXECUTIVE_SUMMARY.md` - Leadership brief with go/no-go recommendation
- `../REPORTS_README.md` - Navigation guide for all QA documentation

## API Documentation

OpenAPI specification and integration guides:

- `openapi/openapi.json` - OpenAPI 3.1.0 specification (auto-generated from FastAPI)
- `openapi/README.md` - Instructions for viewing spec in Swagger UI, Redoc
- Interactive docs: <http://localhost:8080/docs> (when server running)
- Alternative UI: <http://localhost:8080/redoc> (when server running)

For client integration patterns, see `CLIENT_INTEGRATION_MANUAL.md`.

## TenantSage Direction

This repository also functions as a proposal bridge into a broader governed execution model.

That direction includes:

- stronger governance boundaries
- more formalized authorization surfaces
- broader auditable execution paths
- operator-grade deployment patterns
- advanced multi-tenant governance models

## Status

This repository is an active governed MCP foundation with a proposal surface for buyers and a separate technical record for operators and implementers.

For technical specifics, use `RELEASE_NOTES.md` as the primary canonical source.

## License

MIT
