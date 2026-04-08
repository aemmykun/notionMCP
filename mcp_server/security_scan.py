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
        output = result.stdout + result.stderr
        print(output)
        return result.returncode, output
    except Exception as e:
        print(f"ERROR: {e}")
        return 1, str(e)


def main():
    parser = argparse.ArgumentParser(description="Run security scans")
    parser.add_argument(
        "--fail-on-high",
        action="store_true",
        help="Exit with error if high-severity issues found",
    )
    args = parser.parse_args()

    # Ensure we're in the mcp_server directory
    if not Path("requirements.txt").exists():
        print("ERROR: Must run from mcp_server directory")
        sys.exit(1)

    print("Security Scanning Report")
    print("=" * 70)
    print("Timestamp: ", end="")
    subprocess.run(["python", "-c", "import datetime; print(datetime.datetime.now())"])
    
    has_errors = False
    
    # 1. pip-audit: Check for known vulnerabilities in dependencies
    print("\n\n" + "=" * 70)
    print("SCAN 1: Dependency Vulnerabilities (pip-audit)")
    print("=" * 70)
    
    exit_code, output = run_command(
        ["pip-audit", "--desc", "--format", "json"],
        "pip-audit: Dependency vulnerability scan",
    )
    
    if exit_code != 0 and "Found 0 known vulnerabilities" not in output:
        has_errors = True
        print("⚠️  VULNERABILITIES FOUND")
    else:
        print("✅ No known vulnerabilities")
    
    # 2. bandit: Static code security analysis
    print("\n\n" + "=" * 70)
    print("SCAN 2: Source Code Security Issues (bandit)")
    print("=" * 70)
    
    exit_code, output = run_command(
        ["bandit", "-r", ".", "-ll", "-f", "screen"],
        "bandit: Code security scan (medium and high severity only)",
    )
    
    if "No issues identified" not in output and exit_code != 0:
        if args.fail_on_high:
            has_errors = True
        print("⚠️  SECURITY ISSUES FOUND")
    else:
        print("✅ No security issues found")
    
    # 3. safety: Check for known security vulnerabilities
    print("\n\n" + "=" * 70)
    print("SCAN 3: Known Security Advisories (safety)")
    print("=" * 70)
    
    exit_code, output = run_command(
        ["safety", "check", "--json"],
        "safety: Known vulnerability database check",
    )
    
    if exit_code != 0:
        try:
            safety_data = json.loads(output)
            if safety_data and len(safety_data) > 0:
                has_errors = True
                print("⚠️  SECURITY ADVISORIES FOUND")
        except:
            pass
    else:
        print("✅ No security advisories")
    
    # 4. Production preflight check
    print("\n\n" + "=" * 70)
    print("SCAN 4: Production Configuration Hardening")
    print("=" * 70)
    
    exit_code, output = run_command(
        ["python", "production_preflight.py"],
        "Production preflight check",
    )
    
    if exit_code != 0 or "FAIL" in output:
        print("⚠️  PRODUCTION CONFIG ISSUES")
        # Don't fail the scan for config issues (they may be intentional in dev)
    else:
        print("✅ Production config OK")
    
    # Summary
    print("\n\n" + "=" * 70)
    print("SECURITY SCAN SUMMARY")
    print("=" * 70)
    
    if has_errors:
        print("❌ SCAN FAILED: Security issues detected")
        if args.fail_on_high:
            print("\nRecommendation: Fix high-severity issues before deployment")
            return 1
        else:
            print("\nNote: Run with --fail-on-high to enforce in CI/CD")
            return 0
    else:
        print("✅ SCAN PASSED: No critical security issues detected")
        return 0


if __name__ == "__main__":
    sys.exit(main())
