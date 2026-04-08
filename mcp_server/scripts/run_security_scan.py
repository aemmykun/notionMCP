#!/usr/bin/env python3
"""
Security scanning script for MCP server.

Runs multiple security tools and generates a consolidated report.
Run before production deployments or as part of CI/CD.

Usage:
    python security_scan.py
    python security_scan.py --fail-on-high
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> tuple[int, str]:
    """Run a shell command and return exit code and output."""
    print(f"\n{'='*70}")
    print(f"Running: {description}")
    print(f"{'='*70}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        print(output)
        return result.returncode, output
    except Exception as e:
        print(f"ERROR: {e}")
        return 2, str(e)


def parse_json_safe(output: str):
    """Safely parse JSON output, return None if invalid."""
    try:
        return json.loads(output)
    except Exception:
        return None
def parse_json_safe(output: str):
    """Safely parse JSON output, return None if invalid."""
    try:
        return json.loads(output)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run security scans")
    parser.add_argument(
        "--fail-on-high",
        action="store_true",
        help="Exit with error if scanner findings are detected",
    )
    args = parser.parse_args()

    # Ensure we're in the mcp_server directory
    if not Path("requirements.txt").exists():
        print("ERROR: Must run from mcp_server directory")
        return 1

    print("Security Scanning Report")
    print("=" * 70)
    print("Timestamp: ", end="")
    subprocess.run(
        [sys.executable, "-c", "import datetime; print(datetime.datetime.now())"],
        check=False,
    )
    
    findings = False
    tool_errors = False
    
    # 1. pip-audit: Check for known vulnerabilities in dependencies
    print("\n\n" + "=" * 70)
    print("SCAN 1: Dependency Vulnerabilities (pip-audit)")
    print("=" * 70)
    
    exit_code, output = run_command(
        [sys.executable, "-m", "pip_audit", "--desc", "--format", "json"],
        "pip-audit: Dependency vulnerability scan",
    )
    
    audit_json = parse_json_safe(output)
    if exit_code == 0:
        print("✅ No known vulnerabilities (pip-audit)")
    elif exit_code == 1 and audit_json is not None:
        findings = True
        print("⚠️  Vulnerabilities found by pip-audit")
    else:
        tool_errors = True
        print("❌ pip-audit failed to run correctly")
    
    # 2. bandit: Static code security analysis
    print("\n\n" + "=" * 70)
    print("SCAN 2: Source Code Security Issues (bandit)")
    print("=" * 70)
    
    exit_code, output = run_command(
        [sys.executable, "-m", "bandit", "-r", ".", "-ll", "-f", "screen"],
        "bandit: Code security scan (medium and high severity only)",
    )
    
    if exit_code == 0:
        print("✅ No Bandit issues found")
    else:
        findings = True
        print("⚠️  Bandit reported security issues")
    
    # 3. safety: Check for known security vulnerabilities
    print("\n\n" + "=" * 70)
    print("SCAN 3: Known Security Advisories (safety)")
    print("=" * 70)
    
    exit_code, output = run_command(
        [sys.executable, "-m", "safety", "scan", "--output", "json"],
        "safety: Known vulnerability database check",
    )
    
    safety_json = parse_json_safe(output)
    if exit_code == 0:
        print("✅ No Safety advisories found")
    elif safety_json is not None:
        findings = True
        print("⚠️  Safety reported vulnerabilities/advisories")
    else:
        tool_errors = True
        print("❌ Safety failed to run correctly")
    
    # 4. Production preflight check
    print("\n\n" + "=" * 70)
    print("SCAN 4: Production Configuration Hardening")
    print("=" * 70)
    
    exit_code, output = run_command(
        [sys.executable, "production_preflight.py"],
        "Production preflight check",
    )
    
    if exit_code != 0 or "FAIL" in output:
        print("⚠️  Production config issues detected")
        # Don't fail the scan for config issues (they may be intentional in dev)
    else:
        print("✅ Production config OK")
    
    # Summary
    print("\n\n" + "=" * 70)
    print("SECURITY SCAN SUMMARY")
    print("=" * 70)
    
    if tool_errors:
        print("❌ SCAN FAILED: one or more security tools failed to execute")
        return 1
    
    if findings:
        print("⚠️  Findings detected")
        return 1 if args.fail_on_high else 0
    
    print("✅ SCAN PASSED: no critical security issues detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
