import os
import pytest
import requests

API_KEY = os.getenv("INTEGRATION_TEST_API_KEY", "test-key-123")
RESOURCE_LIST_ACTOR_ID = os.getenv("RESOURCE_LIST_ACTOR_ID")
RESOURCE_LIST_ACTOR_TYPE = os.getenv("RESOURCE_LIST_ACTOR_TYPE", "service")
RESOURCE_LIST_MEMBER_ID = os.getenv("RESOURCE_LIST_MEMBER_ID")
RESOURCE_LIST_EXPECTED_NAME = os.getenv("RESOURCE_LIST_EXPECTED_NAME")
RESOURCE_LIST_EXPECTED_TYPE = os.getenv("RESOURCE_LIST_EXPECTED_TYPE", "plan")


@pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Run integration tests only when RUN_INTEGRATION=1")
def test_health():
    r = requests.get("http://127.0.0.1:8080/health", timeout=5)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Run integration tests only when RUN_INTEGRATION=1")
def test_risk_score_call():
    payload = {"actor": "integration-test", "category": "finance", "amount": 2500, "priority": "high"}
    r = requests.post(
        "http://127.0.0.1:8080/call_tool/risk.score",
        json=payload,
        headers={"X-API-Key": API_KEY},
        timeout=5,
    )
    assert r.status_code == 200
    data = r.json()
    assert "riskScore" in data
    assert isinstance(data["riskScore"], int)


@pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Run integration tests only when RUN_INTEGRATION=1")
def test_resource_list_requires_actor_id():
    r = requests.post(
        "http://127.0.0.1:8080/rag_tool/resource.list",
        json={},
        headers={"X-API-Key": API_KEY},
        timeout=5,
    )
    assert r.status_code == 200
    data = r.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_argument"


@pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Run integration tests only when RUN_INTEGRATION=1")
def test_resource_list_returns_seeded_authorized_resource():
    if not (RESOURCE_LIST_ACTOR_ID and RESOURCE_LIST_MEMBER_ID and RESOURCE_LIST_EXPECTED_NAME):
        pytest.skip("Seeded resource-list integration fixture not configured")

    payload = {
        "actorId": RESOURCE_LIST_ACTOR_ID,
        "actorType": RESOURCE_LIST_ACTOR_TYPE,
        "memberId": RESOURCE_LIST_MEMBER_ID,
        "resourceType": RESOURCE_LIST_EXPECTED_TYPE,
        "limit": 10,
    }
    r = requests.post(
        "http://127.0.0.1:8080/rag_tool/resource.list",
        json=payload,
        headers={"X-API-Key": API_KEY},
        timeout=5,
    )
    assert r.status_code == 200
    data = r.json()
    assert "resources" in data
    assert isinstance(data["resources"], list)
    assert any(resource.get("name") == RESOURCE_LIST_EXPECTED_NAME for resource in data["resources"])
