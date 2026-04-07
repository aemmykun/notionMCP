import hashlib
import hmac
import os
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from server import (
    _collect_startup_safety_issues,
    _resolve_actor_identity,
    _sign_actor_identity,
    compute_risk_score,
    handle_approval_request,
    handle_resource_get,
    handle_resource_list,
    handle_rag_ingest_chunks,
    handle_rag_ingest_source,
    handle_rag_retrieve,
    handle_workflow_dispatch,
)

# Test server secret (used across all auth tests)
TEST_SERVER_SECRET = b"test-server-secret-for-unit-tests"


# ---------------------------------------------------------------------------
# Risk score tests
# ---------------------------------------------------------------------------

def test_compute_risk_score_finance_high():
    assert compute_risk_score(category="finance", amount=2000, priority="high") == 100

def test_compute_risk_score_maintenance_low():
    assert compute_risk_score(category="maintenance", amount=500, priority="low") == 20

def test_compute_risk_score_none():
    assert compute_risk_score() == 0


# ---------------------------------------------------------------------------
# Auth — workspace resolver tests (no network required)
# ---------------------------------------------------------------------------

class TestResolveWorkspaceId:
    def _make_env(self, key: str, workspace_id: str, server_secret: bytes = TEST_SERVER_SECRET) -> str:
        """Return a RAG_API_KEYS value for the given plaintext key using HMAC-SHA256."""
        key_id = hmac.new(server_secret, key.encode(), hashlib.sha256).hexdigest()
        return f"{key_id}:{workspace_id}"

    def test_valid_key_returns_workspace_id(self):
        """Test full resolver path (env → HMAC → lookup → return), not just internal state."""
        key = "secret-key-1"
        ws = "ws-uuid-aaa"
        raw = self._make_env(key, ws)
        with patch.dict(os.environ, {"RAG_API_KEYS": raw, "RAG_SERVER_SECRET": TEST_SERVER_SECRET.decode()}):
            from importlib import reload
            import auth
            reload(auth)
            # Test the FULL resolver path (not just _KEY_TABLE)
            resolved = auth.resolve_workspace_id(x_api_key=key)
            assert resolved == ws

    def test_invalid_key_rejected(self):
        import auth
        with patch.dict(os.environ, {"RAG_API_KEYS": self._make_env("good-key", "ws-1"), "RAG_SERVER_SECRET": TEST_SERVER_SECRET.decode()}):
            from importlib import reload
            reload(auth)
            with pytest.raises(HTTPException) as exc_info:
                auth.resolve_workspace_id(x_api_key="wrong-key")
            assert exc_info.value.status_code == 401

    def test_missing_key_header_rejected(self):
        import auth
        with patch.dict(os.environ, {"RAG_API_KEYS": self._make_env("some-key", "ws-1"), "RAG_SERVER_SECRET": TEST_SERVER_SECRET.decode()}):
            from importlib import reload
            reload(auth)
            with pytest.raises(HTTPException) as exc_info:
                auth.resolve_workspace_id(x_api_key=None)
            assert exc_info.value.status_code == 401

    def test_no_keys_configured_rejected(self):
        import auth
        with patch.dict(os.environ, {"RAG_API_KEYS": "", "RAG_SERVER_SECRET": TEST_SERVER_SECRET.decode()}):
            from importlib import reload
            reload(auth)
            with pytest.raises(HTTPException) as exc_info:
                auth.resolve_workspace_id(x_api_key="any-key")
            assert exc_info.value.status_code == 401
    
    def test_malformed_api_keys_format_skipped(self):
        """Test that invalid RAG_API_KEYS format is skipped (logged but doesn't crash)."""
        import auth
        # Invalid formats: missing colon, extra colons, etc.
        with patch.dict(os.environ, {
            "RAG_API_KEYS": "invalid-format-no-colon,too:many:colons:here",
            "RAG_SERVER_SECRET": TEST_SERVER_SECRET.decode()
        }):
            from importlib import reload
            reload(auth)
            # Should skip malformed entries and result in empty table
            with pytest.raises(HTTPException) as exc_info:
                auth.resolve_workspace_id(x_api_key="any-key")
            assert exc_info.value.status_code == 401
    
    def test_duplicate_key_ids_last_wins(self):
        """Test that duplicate key_ids (config error) uses last value (deterministic behavior)."""
        import auth
        key_id = "abc123" * 10  # 60 chars (valid hex length)
        # Same key_id mapped to two different workspaces (config error)
        with patch.dict(os.environ, {
            "RAG_API_KEYS": f"{key_id}:ws-uuid-1,{key_id}:ws-uuid-2",
            "RAG_SERVER_SECRET": TEST_SERVER_SECRET.decode()
        }):
            from importlib import reload
            reload(auth)
            # Last value should win (dict update behavior)
            assert auth._KEY_TABLE.get(key_id) == "ws-uuid-2"
    
    def test_missing_server_secret_fails_auth(self):
        """Test that missing RAG_SERVER_SECRET causes authentication failure."""
        import auth
        key = "test-key"
        ws = "ws-uuid-test"
        raw = self._make_env(key, ws)
        with patch.dict(os.environ, {"RAG_API_KEYS": raw, "RAG_SERVER_SECRET": ""}, clear=True):
            from importlib import reload
            reload(auth)
            with pytest.raises(HTTPException) as exc_info:
                auth.resolve_workspace_id(x_api_key=key)
            assert exc_info.value.status_code == 401
            assert "not configured" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# RAG handler tests (no DB required — rag module is mocked)
# workspace_id is now resolved server-side and passed as second argument.
# ---------------------------------------------------------------------------

_WS = "ws-resolved-from-api-key"


def _error_message(result):
    error = result["error"]
    if isinstance(error, dict):
        return error.get("message", "")
    return str(error)


class TestHandleRagRetrieve:
    def test_returns_results_from_rag_module(self):
        fake_results = [{"id": "abc", "content": "hello", "similarity": 0.92}]
        mock_rag = MagicMock()
        mock_rag.retrieve.return_value = fake_results

        with patch.dict("sys.modules", {"rag": mock_rag}):
            result = handle_rag_retrieve(
                {"query_embedding": [0.1, 0.2, 0.3]},
                workspace_id=_WS,
            )

        assert result == {"results": fake_results}
        mock_rag.retrieve.assert_called_once_with(
            workspace_id=_WS,
            query_embedding=[0.1, 0.2, 0.3],
            top_k=10,
            child_id=None,
            actor_id=None,
            actor_type=None,
            request_id=None,
        )

    def test_passes_child_id_when_provided(self):
        mock_rag = MagicMock()
        mock_rag.retrieve.return_value = []

        with patch.dict("sys.modules", {"rag": mock_rag}):
            handle_rag_retrieve(
                {"query_embedding": [0.1], "child_id": "user-42", "top_k": 5},
                workspace_id=_WS,
            )

        mock_rag.retrieve.assert_called_once_with(
            workspace_id=_WS,
            query_embedding=[0.1],
            top_k=5,
            child_id="user-42",
            actor_id=None,
            actor_type=None,
            request_id=None,
        )

    def test_passes_actor_context_when_provided(self):
        mock_rag = MagicMock()
        mock_rag.retrieve.return_value = []

        with patch.dict("sys.modules", {"rag": mock_rag}):
            handle_rag_retrieve(
                {
                    "query_embedding": [0.1],
                    "actorId": "actor-42",
                    "actorType": "service",
                    "requestId": "req-42",
                },
                workspace_id=_WS,
            )

        mock_rag.retrieve.assert_called_once_with(
            workspace_id=_WS,
            query_embedding=[0.1],
            top_k=10,
            child_id=None,
            actor_id="actor-42",
            actor_type="service",
            request_id="req-42",
        )

    def test_returns_error_when_rag_database_url_missing(self):
        mock_rag = MagicMock()
        mock_rag.retrieve.side_effect = RuntimeError("RAG_DATABASE_URL is not set.")

        with patch.dict("sys.modules", {"rag": mock_rag}), patch.dict(os.environ, {"STRICT_PRODUCTION_MODE": "0"}, clear=False):
            result = handle_rag_retrieve(
                {"query_embedding": [0.1]},
                workspace_id=_WS,
            )

        assert "error" in result
        assert "RAG_DATABASE_URL" in _error_message(result)
    
    def test_missing_embedding_returns_error(self):
        """Test that missing query_embedding returns error instead of crashing."""
        result = handle_rag_retrieve({}, workspace_id=_WS)
        assert "error" in result
        # Should mention the missing field
        error_msg = _error_message(result).lower()
        assert "query_embedding" in error_msg or "embedding" in error_msg or "required" in error_msg
    
    def test_invalid_embedding_type_returns_error(self):
        """Test that non-list embedding returns error."""
        result = handle_rag_retrieve(
            {"query_embedding": "not-a-list"},
            workspace_id=_WS
        )
        assert "error" in result
    
    def test_empty_embedding_returns_error(self):
        """Test that empty embedding list returns error."""
        result = handle_rag_retrieve(
            {"query_embedding": []},
            workspace_id=_WS
        )
        assert "error" in result


class TestHandleResourceList:
    def test_returns_authorized_resources_from_rag_module(self):
        fake_results = [{"id": "res-1", "name": "Care Plan", "resource_type": "document"}]
        mock_rag = MagicMock()
        mock_rag.list_authorized_resources.return_value = fake_results

        with patch.dict("sys.modules", {"rag": mock_rag}):
            result = handle_resource_list(
                {"actorId": "actor-1", "actorType": "service", "limit": 10},
                workspace_id=_WS,
            )

        assert result == {"resources": fake_results}
        mock_rag.list_authorized_resources.assert_called_once_with(
            workspace_id=_WS,
            actor_id="actor-1",
            actor_type="service",
            member_id=None,
            resource_type=None,
            limit=10,
            request_id=None,
        )

    def test_missing_actor_id_returns_error(self):
        result = handle_resource_list({}, workspace_id=_WS)
        assert "error" in result

    def test_passes_optional_filters(self):
        mock_rag = MagicMock()
        mock_rag.list_authorized_resources.return_value = []

        with patch.dict("sys.modules", {"rag": mock_rag}):
            handle_resource_list(
                {
                    "actorId": "actor-2",
                    "memberId": "member-1",
                    "resourceType": "plan",
                    "requestId": "req-1",
                },
                workspace_id=_WS,
            )

        mock_rag.list_authorized_resources.assert_called_once_with(
            workspace_id=_WS,
            actor_id="actor-2",
            actor_type="user",
            member_id="member-1",
            resource_type="plan",
            limit=50,
            request_id="req-1",
        )


class TestHandleResourceGet:
    def test_returns_authorized_resource_from_rag_module(self):
        fake_result = {"id": "res-1", "name": "Care Plan", "resource_type": "document"}
        mock_rag = MagicMock()
        mock_rag.get_authorized_resource.return_value = fake_result

        with patch.dict("sys.modules", {"rag": mock_rag}):
            result = handle_resource_get(
                {"actorId": "actor-1", "actorType": "service", "resourceId": "res-1", "requestId": "req-2"},
                workspace_id=_WS,
            )

        assert result == {"resource": fake_result}
        mock_rag.get_authorized_resource.assert_called_once_with(
            workspace_id=_WS,
            actor_id="actor-1",
            actor_type="service",
            resource_id="res-1",
            request_id="req-2",
        )

    def test_returns_null_when_resource_not_visible(self):
        mock_rag = MagicMock()
        mock_rag.get_authorized_resource.return_value = None

        with patch.dict("sys.modules", {"rag": mock_rag}):
            result = handle_resource_get(
                {"actorId": "actor-1", "resourceId": "res-missing"},
                workspace_id=_WS,
            )

        assert result == {"resource": None}

    def test_missing_resource_id_returns_error(self):
        result = handle_resource_get({"actorId": "actor-1"}, workspace_id=_WS)
        assert result["error"]["code"] == "invalid_argument"


class TestResolveActorIdentity:
    def test_payload_fallback_without_signing_secret(self):
        with patch.dict(os.environ, {"ACTOR_SIGNING_SECRET": ""}, clear=False):
            actor_id, actor_type = _resolve_actor_identity(
                {"actorId": "actor-payload", "actorType": "service"},
                _WS,
            )
        assert actor_id == "actor-payload"
        assert actor_type == "service"

    def test_signed_headers_required_when_secret_configured(self):
        with patch.dict(os.environ, {"ACTOR_SIGNING_SECRET": "actor-secret"}, clear=False):
            with pytest.raises(HTTPException) as exc_info:
                _resolve_actor_identity({}, _WS)
        assert exc_info.value.status_code == 401

    def test_signed_headers_require_timestamp_when_secret_configured(self):
        with patch.dict(os.environ, {"ACTOR_SIGNING_SECRET": "actor-secret"}, clear=False):
            with pytest.raises(HTTPException) as exc_info:
                _resolve_actor_identity(
                    {},
                    _WS,
                    actor_id_header="actor-header",
                    actor_type_header="service",
                    actor_signature_header="sig",
                )
        assert exc_info.value.status_code == 401


class TestStartupSafetyChecks:
    def test_strict_mode_blocks_debug_skip_and_missing_actor_secret(self):
        with patch.dict(
            os.environ,
            {
                "STRICT_PRODUCTION_MODE": "1",
                "DEBUG": "1",
                "SKIP_NOTION_API": "1",
                "RAG_DATABASE_URL": "postgresql://mcp_app:CHANGE_ME_IN_PRODUCTION@db:5432/notion_mcp",
                "RAG_API_KEYS": "abc:ws",
                "RAG_SERVER_SECRET": "server-secret",
                "ACTOR_SIGNING_SECRET": "",
            },
            clear=False,
        ):
            issues = _collect_startup_safety_issues()

        assert any("DEBUG must be disabled" in issue for issue in issues)
        assert any("SKIP_NOTION_API must be disabled" in issue for issue in issues)
        assert any("default mcp_app password" in issue for issue in issues)
        assert any("ACTOR_SIGNING_SECRET is required" in issue for issue in issues)

    def test_non_strict_mode_does_not_fail_on_missing_actor_secret(self):
        with patch.dict(
            os.environ,
            {
                "STRICT_PRODUCTION_MODE": "0",
                "RAG_DATABASE_URL": "postgresql://mcp_app:secure-password@db:5432/notion_mcp",
                "RAG_API_KEYS": "abc:ws",
                "RAG_SERVER_SECRET": "server-secret",
                "ACTOR_SIGNING_SECRET": "",
            },
            clear=False,
        ):
            issues = _collect_startup_safety_issues()

        assert issues == []

    def test_valid_signed_headers_win_when_secret_configured(self):
        with patch.dict(os.environ, {"ACTOR_SIGNING_SECRET": "actor-secret", "ACTOR_SIGNATURE_MAX_AGE_SECONDS": "300"}, clear=False):
            timestamp = str(int(time.time()))
            signature = _sign_actor_identity("actor-header", "service", _WS, timestamp)
            actor_id, actor_type = _resolve_actor_identity(
                {"actorId": "actor-payload", "actorType": "user"},
                _WS,
                actor_id_header="actor-header",
                actor_type_header="service",
                actor_signature_header=signature,
                actor_timestamp_header=timestamp,
            )
        assert actor_id == "actor-header"
        assert actor_type == "service"

    def test_expired_signed_headers_rejected(self):
        with patch.dict(os.environ, {"ACTOR_SIGNING_SECRET": "actor-secret", "ACTOR_SIGNATURE_MAX_AGE_SECONDS": "60"}, clear=False):
            timestamp = str(int(time.time()) - 120)
            signature = _sign_actor_identity("actor-header", "service", _WS, timestamp)
            with pytest.raises(HTTPException) as exc_info:
                _resolve_actor_identity(
                    {},
                    _WS,
                    actor_id_header="actor-header",
                    actor_type_header="service",
                    actor_signature_header=signature,
                    actor_timestamp_header=timestamp,
                )
        assert exc_info.value.status_code == 401

    def test_invalid_timestamp_rejected(self):
        with patch.dict(os.environ, {"ACTOR_SIGNING_SECRET": "actor-secret"}, clear=False):
            with pytest.raises(HTTPException) as exc_info:
                _resolve_actor_identity(
                    {},
                    _WS,
                    actor_id_header="actor-header",
                    actor_type_header="service",
                    actor_signature_header="sig",
                    actor_timestamp_header="not-a-timestamp",
                )
        assert exc_info.value.status_code == 401

    def test_invalid_signed_headers_rejected(self):
        with patch.dict(os.environ, {"ACTOR_SIGNING_SECRET": "actor-secret", "ACTOR_SIGNATURE_MAX_AGE_SECONDS": "300"}, clear=False):
            timestamp = str(int(time.time()))
            with pytest.raises(HTTPException) as exc_info:
                _resolve_actor_identity(
                    {},
                    _WS,
                    actor_id_header="actor-header",
                    actor_type_header="service",
                    actor_signature_header="bad-signature",
                    actor_timestamp_header=timestamp,
                )
        assert exc_info.value.status_code == 401


class TestHandleRagIngestSource:
    def test_returns_source_id(self):
        mock_rag = MagicMock()
        mock_rag.ingest_source.return_value = "source-uuid-123"

        with patch.dict("sys.modules", {"rag": mock_rag}):
            result = handle_rag_ingest_source(
                {"name": "Q1 Policies"},
                workspace_id=_WS,
            )

        assert result == {"source_id": "source-uuid-123"}
        mock_rag.ingest_source.assert_called_once_with(
            workspace_id=_WS,
            name="Q1 Policies",
            status="draft",
            visibility="private",
            effective_from=None,
            effective_to=None,
            legal_hold=False,
            retention_class=None,
        )

    def test_passes_all_governance_fields(self):
        mock_rag = MagicMock()
        mock_rag.ingest_source.return_value = "src-456"

        with patch.dict("sys.modules", {"rag": mock_rag}):
            handle_rag_ingest_source(
                {
                    "name": "Legal Hold Doc",
                    "status": "published",
                    "visibility": "workspace",
                    "effective_from": "2026-01-01T00:00:00Z",
                    "effective_to": "2026-12-31T23:59:59Z",
                    "legal_hold": True,
                    "retention_class": "7yr",
                },
                workspace_id=_WS,
            )

        _, kwargs = mock_rag.ingest_source.call_args
        assert kwargs["workspace_id"] == _WS
        assert kwargs["legal_hold"] is True
        assert kwargs["retention_class"] == "7yr"
        assert kwargs["status"] == "published"


class TestGovernanceHandlersInTestMode:
    def test_workflow_dispatch_skips_live_notion_write(self):
        import server

        with (
            patch.dict(os.environ, {"SKIP_NOTION_API": "1"}, clear=False),
            patch("server.WORKFLOW_DB_ID", "workflow-db"),
            patch("server.AUDIT_DB_ID", "audit-db"),
            patch.object(server.notion.pages, "create") as create_page,
        ):
            result = handle_workflow_dispatch(
                {
                    "actor": "tester",
                    "type": "review",
                    "title": "Workflow in test mode",
                    "_request_id": "req-1",
                }
            )

        assert result["status"] == "created"
        assert result["requestId"] == "req-1"
        assert "pageId" in result
        create_page.assert_not_called()

    def test_approval_request_skips_live_notion_write(self):
        import server

        with (
            patch.dict(os.environ, {"SKIP_NOTION_API": "1"}, clear=False),
            patch("server.APPROVAL_DB_ID", "approval-db"),
            patch("server.AUDIT_DB_ID", "audit-db"),
            patch.object(server.notion.pages, "create") as create_page,
        ):
            result = handle_approval_request(
                {
                    "actor": "tester",
                    "subject": "Approval in test mode",
                    "reason": "Validate dry-run path",
                    "_request_id": "req-2",
                }
            )

        assert result["status"] == "requested"
        assert result["requestId"] == "req-2"
        assert "approvalId" in result
        create_page.assert_not_called()


class TestHandleRagIngestChunks:
    def test_returns_ingested_count(self):
        mock_rag = MagicMock()
        mock_rag.ingest_chunks.return_value = 3
        chunks = [
            {"content": "a", "embedding": [0.1, 0.2]},
            {"content": "b", "embedding": [0.3, 0.4]},
            {"content": "c", "embedding": [0.5, 0.6]},
        ]

        with patch.dict("sys.modules", {"rag": mock_rag}):
            result = handle_rag_ingest_chunks(
                {"source_id": "src-001", "chunks": chunks},
                workspace_id=_WS,
            )

        assert result == {"ingested": 3}
        mock_rag.ingest_chunks.assert_called_once_with(
            source_id="src-001",
            chunks=chunks,
            workspace_id=_WS,
        )

    def test_returns_error_when_rag_unavailable(self):
        mock_rag = MagicMock()
        mock_rag.ingest_chunks.side_effect = RuntimeError("RAG_DATABASE_URL is not set.")

        with patch.dict("sys.modules", {"rag": mock_rag}):
            result = handle_rag_ingest_chunks(
                {"source_id": "src-001", "chunks": [{"content": "x", "embedding": [0.1]}]},
                workspace_id=_WS,
            )

        assert "error" in result


# ---------------------------------------------------------------------------
# Lint check: Ensure no direct _get_conn() usage outside rag.py
# ---------------------------------------------------------------------------

class TestSecurityBoundaries:
    def test_no_direct_db_access_in_server(self):
        """Verify server.py does not import or call _get_conn directly."""
        import server
        # Check server module doesn't have _get_conn
        assert not hasattr(server, "_get_conn"), (
            "server.py must NOT import _get_conn. "
            "All DB access must go through rag.run_scoped_query() to ensure RLS."
        )
    
    def test_run_scoped_query_is_only_db_access(self):
        """Verify _get_conn is only called from safe wrapper functions (refactor-safe test)."""
        import rag
        import ast
        import inspect
        
        # Get source code and parse AST
        source = inspect.getsource(rag)
        tree = ast.parse(source)
        
        # Find all function definitions
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        
        # Track which functions call _get_conn
        functions_calling_get_conn = []
        
        for func_name, func_node in functions.items():
            for node in ast.walk(func_node):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == '_get_conn':
                        functions_calling_get_conn.append(func_name)
                        break
        
        # Allowed functions that can call _get_conn (supports refactoring)
        # If you split run_scoped_query into helpers, add them here
        allowed_callers = {"run_scoped_query"}
        
        actual_callers = set(functions_calling_get_conn)
        assert actual_callers <= allowed_callers, (
            f"_get_conn() can only be called from {allowed_callers}. "
            f"Found in: {actual_callers - allowed_callers}"
        )

class TestRunScopedQueryValidation:
    def test_rejects_invalid_workspace_id(self):
        """Verify run_scoped_query fails fast on non-UUID workspace_id."""
        import rag
        
        with pytest.raises(ValueError, match="workspace_id must be a valid UUID"):
            rag.run_scoped_query(
                workspace_id="not-a-uuid",
                sql="SELECT 1",
                params={},
                returning=False,
            )
    
    def test_rejects_empty_workspace_id(self):
        """Verify run_scoped_query fails fast on empty workspace_id."""
        import rag
        
        with pytest.raises(ValueError, match="workspace_id must be a valid UUID"):
            rag.run_scoped_query(
                workspace_id="",
                sql="SELECT 1",
                params={},
                returning=False,
            )
