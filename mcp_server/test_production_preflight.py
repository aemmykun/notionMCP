import production_preflight


def test_collect_preflight_findings_strict_blocks_risky_debug_and_missing_signing():
    errors, warnings = production_preflight.collect_preflight_findings(
        {
            "DEBUG": "1",
            "ALLOW_DEBUG_TRACEBACKS": "1",
            "SKIP_NOTION_API": "1",
            "RAG_DATABASE_URL": "postgresql://mcp_app:CHANGE_ME_IN_PRODUCTION@db:5432/notion_mcp",
            "RAG_API_KEYS": "abc:ws",
        },
        strict=True,
    )

    assert warnings == ["REDIS_URL is not set; this is acceptable for single-instance deployments only"]
    assert any("DEBUG is enabled" in item for item in errors)
    assert any("ALLOW_DEBUG_TRACEBACKS is enabled" in item for item in errors)
    assert any("SKIP_NOTION_API is enabled" in item for item in errors)
    assert any("default mcp_app password" in item for item in errors)
    assert any("RAG_SERVER_SECRET is missing" in item for item in errors)
    assert any("ACTOR_SIGNING_SECRET is required" in item for item in errors)


def test_collect_preflight_findings_non_strict_warns_instead_of_failing_debug():
    errors, warnings = production_preflight.collect_preflight_findings(
        {
            "DEBUG": "1",
            "ALLOW_DEBUG_TRACEBACKS": "1",
            "SKIP_NOTION_API": "1",
            "RAG_SERVER_SECRET": "short-secret",
            "ACTOR_SIGNING_SECRET": "short-actor-secret",
        },
        strict=False,
    )

    assert errors == []
    assert any("DEBUG is enabled" in item for item in warnings)
    assert any("ALLOW_DEBUG_TRACEBACKS is enabled" in item for item in warnings)
    assert any("SKIP_NOTION_API is enabled" in item for item in warnings)
    assert any("RAG_SERVER_SECRET appears short" in item for item in warnings)
    assert any("ACTOR_SIGNING_SECRET appears short" in item for item in warnings)


def test_collect_preflight_findings_passes_for_hardened_env():
    errors, warnings = production_preflight.collect_preflight_findings(
        {
            "NOTION_TOKEN": "token",
            "GOVERNANCE_DB_ID": "gov",
            "AUDIT_DB_ID": "audit",
            "WORKFLOW_DB_ID": "workflow",
            "APPROVAL_DB_ID": "approval",
            "RAG_DATABASE_URL": "postgresql://mcp_app:super-secret-password@db:5432/notion_mcp",
            "RAG_API_KEYS": "abc:ws",
            "RAG_SERVER_SECRET": "x" * 40,
            "ACTOR_SIGNING_SECRET": "y" * 40,
            "REDIS_URL": "redis://redis:6379/0",
        },
        strict=True,
    )

    assert errors == []
    assert warnings == []