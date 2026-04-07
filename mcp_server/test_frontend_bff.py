from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import frontend_bff


def test_prepare_governed_request_dev_mode_injects_actor_into_payload():
    with patch.dict(
        "os.environ",
        {"MCP_API_KEY": "tenant-key", "ACTOR_SIGNING_SECRET": "", "MCP_WORKSPACE_ID": ""},
        clear=False,
    ):
        headers, payload = frontend_bff._prepare_governed_request(
            {"resourceId": "resource-1"},
            actor_id="user-123",
            actor_type="user",
        )

    assert headers == {"X-API-Key": "tenant-key"}
    assert payload["actorId"] == "user-123"
    assert payload["actorType"] == "user"


def test_prepare_governed_request_signed_mode_uses_headers_not_payload():
    with patch.dict(
        "os.environ",
        {
            "MCP_API_KEY": "tenant-key",
            "ACTOR_SIGNING_SECRET": "signing-secret",
            "MCP_WORKSPACE_ID": "workspace-123",
        },
        clear=False,
    ):
        headers, payload = frontend_bff._prepare_governed_request(
            {"resourceId": "resource-1"},
            actor_id="user-123",
            actor_type="user",
        )

    assert headers["X-API-Key"] == "tenant-key"
    assert headers["X-Actor-Id"] == "user-123"
    assert headers["X-Actor-Type"] == "user"
    assert "X-Actor-Signature" in headers
    assert payload == {"resourceId": "resource-1"}


def test_frontend_resource_list_shapes_browser_request():
    mock_forward = AsyncMock(return_value={"resources": []})
    with patch.object(frontend_bff, "_forward_json", mock_forward):
        with patch.dict(
            "os.environ",
            {"MCP_API_KEY": "tenant-key", "ACTOR_SIGNING_SECRET": "", "MCP_WORKSPACE_ID": ""},
            clear=False,
        ):
            client = TestClient(frontend_bff.app)
            response = client.post(
                "/frontend/resources/list",
                headers={"X-User-Id": "user-123", "X-User-Type": "user"},
                json={"resourceType": "document", "limit": 10},
            )

    assert response.status_code == 200
    forward_path, forward_payload, forward_headers = mock_forward.await_args.args
    assert forward_path == "/rag_tool/resource.list"
    assert forward_payload["resourceType"] == "document"
    assert forward_payload["limit"] == 10
    assert forward_payload["actorId"] == "user-123"
    assert forward_headers == {"X-API-Key": "tenant-key"}
    assert "requestId" in response.json()


def test_frontend_resource_get_uses_trusted_actor_header():
    mock_forward = AsyncMock(return_value={"resource": None})
    with patch.object(frontend_bff, "_forward_json", mock_forward):
        with patch.dict(
            "os.environ",
            {"MCP_API_KEY": "tenant-key", "ACTOR_SIGNING_SECRET": "", "MCP_WORKSPACE_ID": ""},
            clear=False,
        ):
            client = TestClient(frontend_bff.app)
            response = client.get(
                "/frontend/resources/resource-1",
                headers={"X-User-Id": "user-123"},
            )

    assert response.status_code == 200
    forward_path, forward_payload, _forward_headers = mock_forward.await_args.args
    assert forward_path == "/rag_tool/resource.get"
    assert forward_payload["resourceId"] == "resource-1"
    assert forward_payload["actorId"] == "user-123"


def test_frontend_requires_trusted_user_identity():
    client = TestClient(frontend_bff.app)
    response = client.post("/frontend/governance/check", json={"action": "invoice.approve"})

    assert response.status_code == 401
    assert "Missing trusted user identity" in response.json()["detail"]