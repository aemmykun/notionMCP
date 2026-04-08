"""
Integration test: RLS fail-closed behavior

This test verifies that RLS actually enforces workspace isolation by
temporarily breaking the SET LOCAL mechanism and confirming retrieval
returns ZERO rows (not "all rows").

Run with: pytest test_rls_fail_closed.py -v

Prerequisites:
- RAG_DATABASE_URL must be set and point to a test database
- Database must have schema applied (schema.sql)
- Test data will be inserted and cleaned up automatically

Tests cover:
1. Fail-closed reads (no SET LOCAL → 0 rows)
2. Fail-closed writes (no SET LOCAL → INSERT blocked)
3. Cross-workspace isolation (workspace A can't see workspace B)
4. WITH CHECK policy enforcement (can't INSERT into other workspace)
5. Direct DB bypass protection (even _get_conn() respects RLS)
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest

# Skip if RAG_DATABASE_URL not set
pytestmark = pytest.mark.skipif(
    not os.getenv("RAG_DATABASE_URL"),
    reason="RAG_DATABASE_URL not set — skipping RLS integration test",
)


def _create_broken_run_scoped_query():
    """Create a patched run_scoped_query that skips SET LOCAL (simulates bypass)."""
    from mcp_server import rag
    from psycopg2.extras import RealDictCursor
    
    def broken_run_scoped_query(
        workspace_id,
        sql,
        params,
        *,
        many=False,
        returning=True,
        timeout_ms=None,
        actor_id=None,
        actor_type=None,
        request_id=None,
    ):
        """Modified version that skips SET LOCAL (simulates bypass attempt)."""
        conn = rag._get_conn()
        conn.autocommit = False
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("BEGIN")
                # CRITICAL: Skip the SET LOCAL statement here
                # cur.execute("SET LOCAL app.workspace_id = %s", (str(workspace_id),))
                if many:
                    cur.executemany(sql, params)
                else:
                    cur.execute(sql, params)

                if returning and cur.description is not None:
                    rows = [dict(row) for row in cur.fetchall()]
                else:
                    rows = None
                rowcount = cur.rowcount
            conn.commit()
            return rows if returning else rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    return broken_run_scoped_query


def test_rls_fail_closed_reads():
    """
    Test #1: RLS denies reads when SET LOCAL is skipped.
    
    Verifies that without workspace context, retrieval returns ZERO rows
    (fail-closed), not all rows (fail-open).
    """
    from mcp_server import rag

    test_workspace_id = str(uuid.uuid4())
    test_source_id = str(uuid.uuid4())
    test_embedding = [0.1] * 1536

    try:
        # Insert test data with proper workspace context
        rag.run_scoped_query(
            test_workspace_id,
            """
            INSERT INTO rag_sources (id, workspace_id, name, status, legal_hold)
            VALUES (%(id)s, %(workspace_id)s, %(name)s, 'published', FALSE)
            """,
            {
                "id": test_source_id,
                "workspace_id": test_workspace_id,
                "name": "RLS Read Test Source",
            },
            returning=False,
        )

        rag.run_scoped_query(
            test_workspace_id,
            """
            INSERT INTO rag_chunks (source_id, content, embedding)
            VALUES (%(source_id)s, %(content)s, %(embedding)s::vector)
            """,
            {
                "source_id": test_source_id,
                "content": "RLS fail-closed read test chunk",
                "embedding": test_embedding,
            },
            returning=False,
        )

        # Verify normal retrieval works (with SET LOCAL)
        results_normal = rag.retrieve(
            workspace_id=test_workspace_id,
            query_embedding=test_embedding,
            top_k=10,
        )
        assert len(results_normal) == 1, "Normal retrieval should return 1 chunk"

        # Patch to skip SET LOCAL and verify fail-closed behavior
        broken_query = _create_broken_run_scoped_query()
        with patch.object(rag, "run_scoped_query", side_effect=broken_query):
            results_broken = rag.retrieve(
                workspace_id=test_workspace_id,
                query_embedding=test_embedding,
                top_k=10,
            )

            # CRITICAL: Must return zero rows (fail-closed, not fail-open)
            assert len(results_broken) == 0, (
                f"RLS READ fail-closed test FAILED: "
                f"Without SET LOCAL, expected 0 rows but got {len(results_broken)}. "
                f"RLS is NOT enforcing properly (fail-open behavior)!"
            )

        print("✅ Test #1 PASSED: RLS denies reads without SET LOCAL (fail-closed)")

    finally:
        # Cleanup
        try:
            rag.run_scoped_query(
                test_workspace_id,
                "DELETE FROM rag_sources WHERE id = %(id)s",
                {"id": test_source_id},
                returning=False,
            )
        except Exception:
            pass


def test_rls_fail_closed_writes():
    """
    Test #2: RLS denies writes when SET LOCAL is skipped.
    
    Verifies that INSERT without workspace context fails (WITH CHECK policy).
    Uses trusted context to verify no cross-contamination occurred.
    """
    from mcp_server import rag

    test_workspace_id = str(uuid.uuid4())

    try:
        # Attempt INSERT without SET LOCAL (should fail due to WITH CHECK policy)
        broken_query = _create_broken_run_scoped_query()
        with patch.object(rag, "run_scoped_query", side_effect=broken_query):
            insert_succeeded = False
            try:
                result = rag.ingest_source(
                    workspace_id=test_workspace_id,
                    name="Bypass Attempt Source",
                    status="published",
                )
                # If we reach here, INSERT did not throw an exception
                insert_succeeded = True
            except Exception as e:
                # Expected: RLS WITH CHECK policy blocks INSERT
                print(f"✅ INSERT blocked by RLS: {type(e).__name__}")

        # CRITICAL: Verify no row was inserted using TRUSTED context
        # (not the broken context, which would hide cross-contamination)
        count_result = rag.run_scoped_query(
            test_workspace_id,
            "SELECT COUNT(*) as count FROM rag_sources WHERE name = %(name)s",
            {"name": "Bypass Attempt Source"},
            returning=True,
        )
        count = count_result[0]["count"] if count_result else 0

        if insert_succeeded:
            # INSERT succeeded without exception - check if it was actually written
            assert count == 0, (
                f"RLS WRITE fail-closed test FAILED: "
                f"INSERT without SET LOCAL succeeded AND created {count} row(s). "
                f"This indicates missing WITH CHECK policy - cross-tenant contamination possible!"
            )
            print("⚠️  INSERT succeeded without exception but RLS hid the row (acceptable)")
        else:
            # INSERT threw exception - verify no row exists
            assert count == 0, (
                f"RLS WRITE fail-closed test FAILED: "
                f"INSERT threw exception but {count} row(s) still exist. "
                f"Possible data inconsistency!"
            )

        print("✅ Test #2 PASSED: RLS denies writes without SET LOCAL (fail-closed)")

    finally:
        # Cleanup (best effort)
        try:
            rag.run_scoped_query(
                test_workspace_id,
                "DELETE FROM rag_sources WHERE name = %(name)s",
                {"name": "Bypass Attempt Source"},
                returning=False,
            )
        except Exception:
            pass


def test_rls_cross_workspace_isolation():
    """
    Test #3: Workspace A cannot access workspace B data.
    
    Verifies that even with valid SET LOCAL, cross-tenant isolation works.
    """
    from mcp_server import rag

    workspace_a = str(uuid.uuid4())
    workspace_b = str(uuid.uuid4())
    source_a_id = str(uuid.uuid4())
    test_embedding = [0.2] * 1536

    try:
        # Insert data into workspace A
        rag.run_scoped_query(
            workspace_a,
            """
            INSERT INTO rag_sources (id, workspace_id, name, status, legal_hold)
            VALUES (%(id)s, %(workspace_id)s, %(name)s, 'published', FALSE)
            """,
            {
                "id": source_a_id,
                "workspace_id": workspace_a,
                "name": "Workspace A Source",
            },
            returning=False,
        )

        rag.run_scoped_query(
            workspace_a,
            """
            INSERT INTO rag_chunks (source_id, content, embedding)
            VALUES (%(source_id)s, %(content)s, %(embedding)s::vector)
            """,
            {
                "source_id": source_a_id,
                "content": "Workspace A secret data",
                "embedding": test_embedding,
            },
            returning=False,
        )

        # Verify workspace A can see its own data
        results_a = rag.retrieve(
            workspace_id=workspace_a,
            query_embedding=test_embedding,
            top_k=10,
        )
        assert len(results_a) == 1, "Workspace A should see its own data"

        # CRITICAL: Verify workspace B CANNOT see workspace A data
        results_b = rag.retrieve(
            workspace_id=workspace_b,
            query_embedding=test_embedding,
            top_k=10,
        )
        assert len(results_b) == 0, (
            f"RLS CROSS-WORKSPACE test FAILED: "
            f"Workspace B retrieved {len(results_b)} row(s) from workspace A. "
            f"Cross-tenant isolation is broken!"
        )

        print("✅ Test #3 PASSED: Cross-workspace isolation enforced (A ≠ B)")

    finally:
        # Cleanup
        try:
            rag.run_scoped_query(
                workspace_a,
                "DELETE FROM rag_sources WHERE id = %(id)s",
                {"id": source_a_id},
                returning=False,
            )
        except Exception:
            pass


def test_rls_with_check_prevents_cross_tenant_writes():
    """
    Test #4: WITH CHECK policy prevents inserting into other workspace.
    
    Directly validates the WITH CHECK migration. Attempts to INSERT a row
    with workspace_id=A while session is set to workspace_id=B.
    """
    from mcp_server import rag

    workspace_a = str(uuid.uuid4())
    workspace_b = str(uuid.uuid4())

    try:
        # Attempt to INSERT into workspace A while session is workspace B
        # This should FAIL due to WITH CHECK policy
        insert_succeeded = False
        try:
            rag.run_scoped_query(
                workspace_b,  # Session set to workspace B
                """
                INSERT INTO rag_sources (workspace_id, name, status, legal_hold)
                VALUES (%(workspace_id)s, %(name)s, 'published', FALSE)
                """,
                {
                    "workspace_id": workspace_a,  # Trying to insert into workspace A
                    "name": "Cross-Tenant Attack Source",
                },
                returning=False,
            )
            insert_succeeded = True
        except Exception as e:
            # Expected: WITH CHECK policy rejects this
            print(f"✅ Cross-tenant INSERT blocked by WITH CHECK: {type(e).__name__}")

        # Verify no row was created in workspace A
        count_a = rag.run_scoped_query(
            workspace_a,
            "SELECT COUNT(*) as count FROM rag_sources WHERE name = %(name)s",
            {"name": "Cross-Tenant Attack Source"},
            returning=True,
        )[0]["count"]

        # Verify no row was created in workspace B either
        count_b = rag.run_scoped_query(
            workspace_b,
            "SELECT COUNT(*) as count FROM rag_sources WHERE name = %(name)s",
            {"name": "Cross-Tenant Attack Source"},
            returning=True,
        )[0]["count"]

        if insert_succeeded:
            assert count_a == 0 and count_b == 0, (
                f"RLS WITH CHECK test FAILED: "
                f"INSERT succeeded without exception. "
                f"Found {count_a} rows in workspace A, {count_b} rows in workspace B. "
                f"Missing WITH CHECK policy allows cross-tenant contamination!"
            )
        else:
            assert count_a == 0 and count_b == 0, (
                f"WITH CHECK blocked INSERT but {count_a + count_b} row(s) still exist!"
            )

        print("✅ Test #4 PASSED: WITH CHECK policy prevents cross-tenant writes")

    finally:
        # Cleanup both workspaces
        for ws in [workspace_a, workspace_b]:
            try:
                rag.run_scoped_query(
                    ws,
                    "DELETE FROM rag_sources WHERE name = %(name)s",
                    {"name": "Cross-Tenant Attack Source"},
                    returning=False,
                )
            except Exception:
                pass


def test_rls_direct_db_access_bypass_protected():
    """
    Test #5: Even direct _get_conn() usage respects RLS.
    
    Tests that bypassing the run_scoped_query wrapper still cannot
    access data without proper workspace context. Proves DB-layer security.
    """
    from mcp_server import rag

    test_workspace_id = str(uuid.uuid4())
    test_source_id = str(uuid.uuid4())
    test_embedding = [0.3] * 1536

    try:
        # Insert test data normally
        rag.run_scoped_query(
            test_workspace_id,
            """
            INSERT INTO rag_sources (id, workspace_id, name, status, legal_hold)
            VALUES (%(id)s, %(workspace_id)s, %(name)s, 'published', FALSE)
            """,
            {
                "id": test_source_id,
                "workspace_id": test_workspace_id,
                "name": "Direct DB Access Test",
            },
            returning=False,
        )

        rag.run_scoped_query(
            test_workspace_id,
            """
            INSERT INTO rag_chunks (source_id, content, embedding)
            VALUES (%(source_id)s, %(content)s, %(embedding)s::vector)
            """,
            {
                "source_id": test_source_id,
                "content": "Direct access test chunk",
                "embedding": test_embedding,
            },
            returning=False,
        )

        # Attempt direct DB access WITHOUT run_scoped_query wrapper
        conn = rag._get_conn()
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN")
                # No SET LOCAL here - direct DB access
                cur.execute(
                    "SELECT COUNT(*) FROM rag_chunks WHERE content LIKE %s",
                    ("%Direct access%",)
                )
                count = cur.fetchone()[0]
            conn.commit()

            # CRITICAL: Direct access without SET LOCAL must return 0
            assert count == 0, (
                f"RLS BYPASS test FAILED: "
                f"Direct _get_conn() access without SET LOCAL returned {count} row(s). "
                f"DB-layer RLS is not enforcing! Application wrapper bypass is possible!"
            )

            print("✅ Test #5 PASSED: Direct DB access denied without SET LOCAL")

        finally:
            conn.close()

    finally:
        # Cleanup
        try:
            rag.run_scoped_query(
                test_workspace_id,
                "DELETE FROM rag_sources WHERE id = %(id)s",
                {"id": test_source_id},
                returning=False,
            )
        except Exception:
            pass


def test_rls_fail_closed_behavior():
    """
    Master test: Run all RLS security tests in sequence.
    
    This is the main integration test that validates complete tenant isolation.
    """
    print("\n" + "=" * 70)
    print("RLS SECURITY VALIDATION - PRODUCTION-GRADE TEST SUITE")
    print("=" * 70)
    
    test_rls_fail_closed_reads()
    test_rls_fail_closed_writes()
    test_rls_cross_workspace_isolation()
    test_rls_with_check_prevents_cross_tenant_writes()
    test_rls_direct_db_access_bypass_protected()
    
    print("\n" + "=" * 70)
    print("✅ ALL RLS SECURITY TESTS PASSED")
    print("=" * 70)
    print("Tenant isolation guaranteed under:")
    print("  1. Missing workspace context (fail-closed)")
    print("  2. Write operations without context")
    print("  3. Cross-workspace access attempts")
    print("  4. Cross-workspace write attempts (WITH CHECK)")
    print("  5. Direct database access bypass attempts")
    print("=" * 70)


if __name__ == "__main__":
    # Allow running directly for manual testing
    test_rls_fail_closed_behavior()


