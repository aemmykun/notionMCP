from unittest.mock import patch

import rag


def test_list_authorized_resources_records_curated_event_and_audit_metadata():
    calls = []

    def fake_run_scoped_query(workspace_id, sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        if "FROM v_resource_authorized" in sql:
            return [{"id": "res-1", "name": "Care Plan"}]
        if "SELECT id FROM families" in sql:
            return [{"id": "family-1"}]
        if "INSERT INTO domain_events" in sql:
            return [{"id": "event-1"}]
        if "SELECT proof_hash" in sql:
            return [{"proof_hash": "prev-proof"}]
        if "INSERT INTO audit_immutable" in sql:
            return 1
        raise AssertionError(f"Unexpected SQL: {sql}")

    with patch.object(rag, "run_scoped_query", side_effect=fake_run_scoped_query):
        results = rag.list_authorized_resources(
            workspace_id="123e4567-e89b-12d3-a456-426614174000",
            actor_id="actor-1",
            actor_type="service",
            member_id="member-1",
            resource_type="plan",
            limit=10,
            request_id="123e4567-e89b-12d3-a456-426614174999",
        )

    assert results == [{"id": "res-1", "name": "Care Plan"}]

    audit_insert = next(params for sql, params, _ in calls if "INSERT INTO audit_immutable" in sql)
    assert audit_insert["action"] == "resource.list"
    assert audit_insert["actor_id"] == "actor-1"
    assert audit_insert["target_type"] == "resource"
    assert audit_insert["target_id"] == "member-1"
    assert '"result_count": 1' in audit_insert["payload"]
    assert '"mode": "stateless-secure-view"' in audit_insert["payload"]
    assert 'Care Plan' not in audit_insert["payload"]


def test_list_authorized_resources_does_not_fail_if_event_audit_write_errors():
    def fake_run_scoped_query(workspace_id, sql, params, **kwargs):
        if "FROM v_resource_authorized" in sql:
            return [{"id": "res-1", "name": "Care Plan"}]
        raise RuntimeError("event store unavailable")

    with patch.object(rag, "run_scoped_query", side_effect=fake_run_scoped_query):
        results = rag.list_authorized_resources(
            workspace_id="123e4567-e89b-12d3-a456-426614174000",
            actor_id="actor-1",
        )

    assert results == [{"id": "res-1", "name": "Care Plan"}]


def test_get_authorized_resource_records_curated_event_and_audit_metadata():
    calls = []

    def fake_run_scoped_query(workspace_id, sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        if "FROM v_resource_authorized" in sql:
            return [{"id": "res-1", "name": "Care Plan"}]
        if "SELECT id FROM families" in sql:
            return [{"id": "family-1"}]
        if "INSERT INTO domain_events" in sql:
            return [{"id": "event-3"}]
        if "SELECT proof_hash" in sql:
            return [{"proof_hash": "prev-proof"}]
        if "INSERT INTO audit_immutable" in sql:
            return 1
        raise AssertionError(f"Unexpected SQL: {sql}")

    with patch.object(rag, "run_scoped_query", side_effect=fake_run_scoped_query):
        result = rag.get_authorized_resource(
            workspace_id="123e4567-e89b-12d3-a456-426614174000",
            actor_id="actor-1",
            actor_type="service",
            resource_id="res-1",
            request_id="123e4567-e89b-12d3-a456-426614174999",
        )

    assert result == {"id": "res-1", "name": "Care Plan"}

    audit_insert = next(params for sql, params, _ in calls if "INSERT INTO audit_immutable" in sql)
    assert audit_insert["action"] == "resource.get"
    assert audit_insert["actor_id"] == "actor-1"
    assert audit_insert["target_type"] == "resource"
    assert audit_insert["target_id"] == "res-1"
    assert '"resource_id": "res-1"' in audit_insert["payload"]
    assert '"result_count": 1' in audit_insert["payload"]
    assert 'Care Plan' not in audit_insert["payload"]


def test_get_authorized_resource_records_zero_result_without_disclosing_existence():
    calls = []

    def fake_run_scoped_query(workspace_id, sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        if "FROM v_resource_authorized" in sql:
            return []
        if "SELECT id FROM families" in sql:
            return [{"id": "family-1"}]
        if "INSERT INTO domain_events" in sql:
            return [{"id": "event-4"}]
        if "SELECT proof_hash" in sql:
            return [{"proof_hash": "prev-proof"}]
        if "INSERT INTO audit_immutable" in sql:
            return 1
        raise AssertionError(f"Unexpected SQL: {sql}")

    with patch.object(rag, "run_scoped_query", side_effect=fake_run_scoped_query):
        result = rag.get_authorized_resource(
            workspace_id="123e4567-e89b-12d3-a456-426614174000",
            actor_id="actor-1",
            actor_type="service",
            resource_id="res-missing",
            request_id="123e4567-e89b-12d3-a456-426614174999",
        )

    assert result is None

    audit_insert = next(params for sql, params, _ in calls if "INSERT INTO audit_immutable" in sql)
    assert audit_insert["action"] == "resource.get"
    assert audit_insert["target_id"] == "res-missing"
    assert '"result_count": 0' in audit_insert["payload"]


def test_retrieve_records_curated_event_and_audit_metadata_when_actor_present():
    calls = []

    def fake_run_scoped_query(workspace_id, sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        if "FROM  rag_chunks" in sql:
            return [{"id": "chunk-1", "content": "governed text"}]
        if "SELECT id FROM families" in sql:
            return [{"id": "family-1"}]
        if "INSERT INTO domain_events" in sql:
            return [{"id": "event-2"}]
        if "SELECT proof_hash" in sql:
            return [{"proof_hash": "prev-proof"}]
        if "INSERT INTO audit_immutable" in sql:
            return 1
        raise AssertionError(f"Unexpected SQL: {sql}")

    with patch.object(rag, "run_scoped_query", side_effect=fake_run_scoped_query):
        results = rag.retrieve(
            workspace_id="123e4567-e89b-12d3-a456-426614174000",
            query_embedding=[0.1] * rag.EMBEDDING_DIM,
            top_k=5,
            child_id="child-1",
            actor_id="actor-1",
            actor_type="service",
            request_id="123e4567-e89b-12d3-a456-426614174999",
        )

    assert results == [{"id": "chunk-1", "content": "governed text"}]
    audit_insert = next(params for sql, params, _ in calls if "INSERT INTO audit_immutable" in sql)
    assert audit_insert["action"] == "rag.retrieve"
    assert audit_insert["target_type"] == "rag_chunk"
    assert audit_insert["target_id"] == "child-1"
    assert '"mode": "governance-first-rag"' in audit_insert["payload"]
    assert '"result_count": 1' in audit_insert["payload"]
    assert 'governed text' not in audit_insert["payload"]