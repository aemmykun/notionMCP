"""Example backend-for-frontend layer for browser-safe MCP usage.

This module is intentionally additive. It does not change the MCP core server.
It shows how a trusted app server can:

- hold the MCP API key
- map app user identity to MCP actor identity
- sign governed-read headers when configured
- shape browser-friendly requests into MCP tool payloads
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


def _mcp_base_url() -> str:
    return os.getenv("MCP_BASE_URL", "http://localhost:8080").rstrip("/")


def _mcp_api_key() -> str:
    api_key = os.getenv("MCP_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="MCP_API_KEY is not configured")
    return api_key


def _actor_signing_secret() -> str:
    return os.getenv("ACTOR_SIGNING_SECRET", "")


def _mcp_workspace_id() -> str:
    return os.getenv("MCP_WORKSPACE_ID", "")


def _build_actor_headers(
    actor_id: str,
    actor_type: str,
    workspace_id: str,
    secret: str,
    *,
    timestamp: str | None = None,
) -> dict[str, str]:
    if not timestamp:
        timestamp = str(int(time.time()))
    message = f"{actor_id}:{actor_type}:{workspace_id}:{timestamp}".encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "X-Actor-Id": actor_id,
        "X-Actor-Type": actor_type,
        "X-Actor-Timestamp": timestamp,
        "X-Actor-Signature": signature,
    }


def _trusted_actor(
    x_user_id: str | None,
    x_user_type: str | None,
) -> tuple[str, str]:
    if not x_user_id:
        raise HTTPException(
            status_code=401,
            detail=(
                "Missing trusted user identity. Replace X-User-Id/X-User-Type with "
                "your app session middleware in production."
            ),
        )
    return x_user_id, x_user_type or "user"


def _prepare_governed_request(
    payload: dict[str, Any],
    *,
    actor_id: str,
    actor_type: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    headers = {"X-API-Key": _mcp_api_key()}
    prepared_payload = dict(payload)

    actor_secret = _actor_signing_secret()
    workspace_id = _mcp_workspace_id()
    if actor_secret or workspace_id:
        if not actor_secret or not workspace_id:
            raise HTTPException(
                status_code=500,
                detail="ACTOR_SIGNING_SECRET and MCP_WORKSPACE_ID must both be configured",
            )
        headers.update(_build_actor_headers(actor_id, actor_type, workspace_id, actor_secret))
        return headers, prepared_payload

    prepared_payload["actorId"] = actor_id
    prepared_payload["actorType"] = actor_type
    return headers, prepared_payload


async def _forward_json(
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    url = f"{_mcp_base_url()}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=data)

    return data


class ResourceListInput(BaseModel):
    resourceType: str | None = None
    memberId: str | None = None
    limit: int = Field(default=25, ge=1, le=100)
    requestId: str | None = None


class ResourceGetInput(BaseModel):
    requestId: str | None = None


class KnowledgeSearchInput(BaseModel):
    queryEmbedding: list[float]
    topK: int = Field(default=5, ge=1, le=50)
    requestId: str | None = None


class PolicyCheckInput(BaseModel):
    action: str
    context: dict[str, Any] = Field(default_factory=dict)
    requestId: str | None = None


app = FastAPI(title="Notion MCP Frontend BFF Example", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "frontend-bff-example"}


@app.post("/frontend/resources/list")
async def frontend_resource_list(
    body: ResourceListInput,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_type: str | None = Header(default=None, alias="X-User-Type"),
) -> dict[str, Any]:
    actor_id, actor_type = _trusted_actor(x_user_id, x_user_type)
    request_id = body.requestId or str(uuid.uuid4())
    headers, payload = _prepare_governed_request(
        {
            "resourceType": body.resourceType,
            "memberId": body.memberId,
            "limit": body.limit,
            "requestId": request_id,
        },
        actor_id=actor_id,
        actor_type=actor_type,
    )
    result = await _forward_json("/rag_tool/resource.list", payload, headers)
    return {"requestId": request_id, **result}


@app.get("/frontend/resources/{resource_id}")
async def frontend_resource_get(
    resource_id: str,
    request_id: str | None = None,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_type: str | None = Header(default=None, alias="X-User-Type"),
) -> dict[str, Any]:
    actor_id, actor_type = _trusted_actor(x_user_id, x_user_type)
    final_request_id = request_id or str(uuid.uuid4())
    headers, payload = _prepare_governed_request(
        {
            "resourceId": resource_id,
            "requestId": final_request_id,
        },
        actor_id=actor_id,
        actor_type=actor_type,
    )
    result = await _forward_json("/rag_tool/resource.get", payload, headers)
    return {"requestId": final_request_id, **result}


@app.post("/frontend/knowledge/search")
async def frontend_knowledge_search(
    body: KnowledgeSearchInput,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_type: str | None = Header(default=None, alias="X-User-Type"),
) -> dict[str, Any]:
    actor_id, actor_type = _trusted_actor(x_user_id, x_user_type)
    request_id = body.requestId or str(uuid.uuid4())
    headers, payload = _prepare_governed_request(
        {
            "query_embedding": body.queryEmbedding,
            "top_k": body.topK,
            "requestId": request_id,
        },
        actor_id=actor_id,
        actor_type=actor_type,
    )
    result = await _forward_json("/rag_tool/rag.retrieve", payload, headers)
    return {"requestId": request_id, **result}


@app.post("/frontend/governance/check")
async def frontend_policy_check(
    body: PolicyCheckInput,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> dict[str, Any]:
    actor_id, _actor_type = _trusted_actor(x_user_id, None)
    request_id = body.requestId or str(uuid.uuid4())
    headers = {"X-API-Key": _mcp_api_key()}
    payload = {
        "actor": actor_id,
        "action": body.action,
        "context": body.context,
        "requestId": request_id,
    }
    result = await _forward_json("/call_tool/policy.check", payload, headers)
    return {"requestId": request_id, **result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090)