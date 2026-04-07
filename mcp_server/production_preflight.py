"""Production preflight checks for safer redeploys.

Usage:
    python production_preflight.py
    python production_preflight.py --strict
    python production_preflight.py --live-url http://127.0.0.1:8080/health
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

from dotenv import dotenv_values


def _load_env_file() -> dict[str, str]:
    raw_values = dotenv_values(Path(__file__).with_name('.env'))
    normalized: dict[str, str] = {}
    for key, value in raw_values.items():
        if key is None or value is None:
            continue
        normalized[key.lstrip('\ufeff')] = value
    return normalized


REQUIRED_NOTION_VARS = [
    "NOTION_TOKEN",
    "GOVERNANCE_DB_ID",
    "AUDIT_DB_ID",
    "WORKFLOW_DB_ID",
    "APPROVAL_DB_ID",
]


def env_enabled(name: str, env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return source.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def collect_preflight_findings(env: dict[str, str] | None = None, *, strict: bool = False) -> tuple[list[str], list[str]]:
    source = env if env is not None else {**_load_env_file(), **dict(os.environ)}
    errors: list[str] = []
    warnings: list[str] = []

    missing_notion = [name for name in REQUIRED_NOTION_VARS if not source.get(name)]
    if missing_notion:
        target = errors if strict else warnings
        target.append(f"Missing required Notion env vars: {', '.join(missing_notion)}")

    debug_enabled = env_enabled("DEBUG", source)
    traceback_enabled = env_enabled("ALLOW_DEBUG_TRACEBACKS", source)
    skip_notion = env_enabled("SKIP_NOTION_API", source)
    rag_db_url = source.get("RAG_DATABASE_URL", "")
    rag_secret = source.get("RAG_SERVER_SECRET", "")
    actor_secret = source.get("ACTOR_SIGNING_SECRET", "")
    redis_url = source.get("REDIS_URL", "")

    if debug_enabled:
        (errors if strict else warnings).append("DEBUG is enabled")
    if traceback_enabled:
        (errors if strict else warnings).append("ALLOW_DEBUG_TRACEBACKS is enabled")
    if skip_notion:
        (errors if strict else warnings).append("SKIP_NOTION_API is enabled")
    if rag_db_url and "CHANGE_ME_IN_PRODUCTION" in rag_db_url:
        errors.append("RAG_DATABASE_URL still contains the default mcp_app password")
    if source.get("RAG_API_KEYS") and not rag_secret:
        errors.append("RAG_SERVER_SECRET is missing while RAG_API_KEYS is configured")
    if rag_secret and len(rag_secret) < 32:
        warnings.append("RAG_SERVER_SECRET appears short; use a high-entropy secret")
    if actor_secret and len(actor_secret) < 32:
        warnings.append("ACTOR_SIGNING_SECRET appears short; use a high-entropy secret")
    if strict and rag_db_url and not actor_secret:
        errors.append("ACTOR_SIGNING_SECRET is required in strict production mode when RAG is enabled")
    if strict and not redis_url:
        warnings.append("REDIS_URL is not set; this is acceptable for single-instance deployments only")

    return errors, warnings


def check_live_url(live_url: str) -> str | None:
    try:
        with urllib.request.urlopen(live_url, timeout=5) as response:
            if response.status != 200:
                return f"Health endpoint returned HTTP {response.status}"
    except urllib.error.URLError as exc:
        return f"Health endpoint check failed: {exc}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production preflight checks")
    parser.add_argument("--strict", action="store_true", help="Treat unsafe config as fatal")
    parser.add_argument("--live-url", help="Optional health endpoint to verify after deploy")
    args = parser.parse_args()

    errors, warnings = collect_preflight_findings(strict=args.strict or env_enabled("STRICT_PRODUCTION_MODE"))
    if args.live_url:
        live_error = check_live_url(args.live_url)
        if live_error:
            errors.append(live_error)

    if errors:
        print("FAIL")
        for item in errors:
            print(f"- {item}")
    if warnings:
        print("WARN")
        for item in warnings:
            print(f"- {item}")
    if not errors and not warnings:
        print("PASS")
        print("- Production preflight checks passed")

    if errors:
        print("\nSuggested fixes:")
        print("- Disable DEBUG, ALLOW_DEBUG_TRACEBACKS, and SKIP_NOTION_API for production redeploys")
        print("- Set ACTOR_SIGNING_SECRET and RAG_SERVER_SECRET to strong random values")
        print("- Replace any CHANGE_ME_IN_PRODUCTION password in RAG_DATABASE_URL")
        print("- Re-run: python production_preflight.py --strict")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())