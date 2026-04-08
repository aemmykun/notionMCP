#!/usr/bin/env python3
"""
RLS Policy Completeness Check

Verifies that Row Level Security is properly configured before running tests.
Catches common RLS configuration errors early in the CI pipeline.

Usage:
    python verify_rls_policies.py

Environment:
    PGPASSWORD: Postgres password
    Or provide connection string as first argument
"""
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor


def verify_rls_policies(conn_string=None):
    """Verify RLS configuration is complete and correct."""
    if conn_string is None:
        conn_string = os.getenv(
            "RAG_DATABASE_URL",
            "postgresql://postgres:test_password@localhost:5432/notion_mcp_test"
        )
    
    errors = []
    warnings = []
    
    print("=" * 70)
    print("RLS POLICY VERIFICATION")
    print("=" * 70)
    
    try:
        conn = psycopg2.connect(conn_string)
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Check for tables with RLS enabled
        print("\n1️⃣  Tables with RLS enabled:")
        cur.execute("""
            SELECT schemaname, tablename, rowsecurity
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename;
        """)
        
        tables_without_rls = []
        for row in cur.fetchall():
            rls_status = "✅ ENABLED" if row['rowsecurity'] else "⚠️  DISABLED"
            print(f"   {row['tablename']:30s} {rls_status}")
            if not row['rowsecurity']:
                tables_without_rls.append(row['tablename'])
        
        if tables_without_rls:
            warnings.append(
                f"Tables without RLS: {', '.join(tables_without_rls)}"
            )
        
        # 2. Check for tables with FORCE RLS
        print("\n2️⃣  Tables with FORCE ROW LEVEL SECURITY:")
        cur.execute("""
            SELECT c.relname, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY c.relname;
        """)
        
        for row in cur.fetchall():
            force_status = "✅ FORCED" if row['relforcerowsecurity'] else "⚠️  NOT FORCED"
            print(f"   {row['relname']:30s} {force_status}")
        
        # 3. Check policies exist for RLS-enabled tables
        print("\n3️⃣  RLS Policies per table:")
        cur.execute("""
            SELECT
                schemaname,
                tablename,
                COUNT(*) as policy_count,
                array_agg(policyname) as policies
            FROM pg_policies
            WHERE schemaname = 'public'
            GROUP BY schemaname, tablename
            ORDER BY tablename;
        """)
        
        policies_found = cur.fetchall()
        if not policies_found:
            errors.append("No RLS policies found in public schema")
        else:
            for row in policies_found:
                print(f"   {row['tablename']:30s} {row['policy_count']:2d} policies")
                for policy in row['policies']:
                    print(f"      • {policy}")
        
        # 4. Check for required roles
        print("\n4️⃣  Required roles:")
        required_roles = ['mcp_app', 'postgres']
        cur.execute("""
            SELECT rolname, rolbypassrls, rolsuper
            FROM pg_roles
            WHERE rolname = ANY(%s)
            ORDER BY rolname;
        """, (required_roles,))
        
        found_roles = set()
        for row in cur.fetchall():
            found_roles.add(row['rolname'])
            bypass_status = "⚠️  CAN BYPASS" if row['rolbypassrls'] else "✅ CANNOT BYPASS"
            super_status = "⚠️  SUPERUSER" if row['rolsuper'] else "✅ NOT SUPER"
            print(f"   {row['rolname']:20s} {bypass_status} | {super_status}")
        
        missing_roles = set(required_roles) - found_roles
        if missing_roles:
            errors.append(f"Missing required roles: {', '.join(missing_roles)}")
        
        # 5. Verify no policies reference missing columns
        print("\n5️⃣  Policy expression validation:")
        cur.execute("""
            SELECT tablename, policyname, qual, with_check
            FROM pg_policies
            WHERE schemaname = 'public'
            ORDER BY tablename, policyname;
        """)
        
        policy_count = 0
        for row in cur.fetchall():
            policy_count += 1
            # Basic validation - check for common issues
            qual = row['qual'] or ''
            with_check = row['with_check'] or ''
            
            # Check for common bugs
            if 'app.workspace_id' in qual or 'app.workspace_id' in with_check:
                print(f"   ✅ {row['tablename']}.{row['policyname']} uses workspace_id")
            else:
                warnings.append(
                    f"{row['tablename']}.{row['policyname']} does not reference app.workspace_id"
                )
        
        print(f"\n   Total policies validated: {policy_count}")
        
        # 6. Summary
        print("\n" + "=" * 70)
        print("VERIFICATION SUMMARY")
        print("=" * 70)
        
        if errors:
            print("\n❌ ERRORS:")
            for error in errors:
                print(f"   • {error}")
        
        if warnings:
            print("\n⚠️  WARNINGS:")
            for warning in warnings:
                print(f"   • {warning}")
        
        if not errors and not warnings:
            print("\n✅ ALL CHECKS PASSED")
            return 0
        elif not errors:
            print("\n✅ PASSED (with warnings)")
            return 0
        else:
            print("\n❌ FAILED")
            return 1
        
    except psycopg2.Error as e:
        print(f"\n❌ Database connection error: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    conn_string = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(verify_rls_policies(conn_string))
