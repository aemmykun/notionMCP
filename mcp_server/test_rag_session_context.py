from unittest.mock import call, MagicMock

import rag


def test_apply_session_context_sets_workspace_only_by_default():
    cursor = MagicMock()

    rag._apply_session_context(cursor, "123e4567-e89b-12d3-a456-426614174000")

    cursor.execute.assert_has_calls(
        [call("SET LOCAL app.workspace_id = %s", ("123e4567-e89b-12d3-a456-426614174000",))]
    )
    assert cursor.execute.call_count == 1


def test_apply_session_context_sets_optional_actor_and_request_context():
    cursor = MagicMock()

    rag._apply_session_context(
        cursor,
        "123e4567-e89b-12d3-a456-426614174000",
        actor_id="actor-42",
        actor_type="service",
        request_id="req-abc",
    )

    cursor.execute.assert_has_calls(
        [
            call("SET LOCAL app.workspace_id = %s", ("123e4567-e89b-12d3-a456-426614174000",)),
            call("SET LOCAL app.actor_id = %s", ("actor-42",)),
            call("SET LOCAL app.actor_type = %s", ("service",)),
            call("SET LOCAL app.request_id = %s", ("req-abc",)),
        ]
    )
    assert cursor.execute.call_count == 4