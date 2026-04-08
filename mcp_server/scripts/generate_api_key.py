#!/usr/bin/env python3
"""
Generate safe API key → workspace_id mappings for RAG_API_KEYS.

This script uses UUIDv5 to deterministically derive workspace_id from the API key,
preventing accidental tenant collision (mathematically unlikely with UUIDv5).

Security Model:
    - API keys MUST be high-entropy random values (32+ characters recommended)
    - Uses HMAC-SHA256 (not plain SHA-256) to prevent offline dictionary attacks
    - Server secret from RAG_SERVER_SECRET env var adds defense-in-depth
    - UUIDv5 derivation makes workspace_id stable and deterministic

Usage:
    export RAG_SERVER_SECRET="your-server-secret-change-me-in-production"
    python generate_api_key.py "my-secret-key-tenant-a"
    python generate_api_key.py "my-secret-key-tenant-a" "my-secret-key-tenant-b"

Output format (add to .env):
    RAG_API_KEYS=<hmac_sha256_hex>:<workspace_uuid>,<hmac_sha256_hex>:<workspace_uuid>,...

CRITICAL:
    - Use strong, random API keys (e.g., from `openssl rand -base64 32`)
    - DO NOT use human-memorable secrets like "tenant-a" or "acme-prod"
    - Store RAG_SERVER_SECRET securely (different from API keys)
"""
import hashlib
import hmac
import os
import sys
import uuid

# Namespace UUID for Notion MCP Governance Server
# IMPORTANT: This is intentionally fixed across all environments.
# If you want dev/staging/prod to have DIFFERENT workspace_id mappings for the
# same API key, use different namespaces per environment. Otherwise, keep this
# constant for stable cross-environment mapping.
NAMESPACE = uuid.UUID("a7c3e8f2-4d9b-5a1c-8e6f-2b4d7a9c1e3f")


def get_server_secret() -> bytes:
    """Get server secret from environment (required for HMAC)."""
    secret = os.environ.get("RAG_SERVER_SECRET", "")
    if not secret:
        print("ERROR: RAG_SERVER_SECRET environment variable not set", file=sys.stderr)
        print("", file=sys.stderr)
        print("Set a strong server secret before generating keys:", file=sys.stderr)
        print('  export RAG_SERVER_SECRET="$(openssl rand -base64 32)"', file=sys.stderr)
        print("", file=sys.stderr)
        sys.exit(1)
    return secret.encode()


def generate_key_id(api_key: str, server_secret: bytes) -> str:
    """Generate HMAC-SHA256 key identifier (prevents offline dictionary attacks)."""
    return hmac.new(server_secret, api_key.encode(), hashlib.sha256).hexdigest()


def generate_workspace_id(key_id: str) -> str:
    """Generate deterministic workspace_id using UUIDv5(namespace, key_id)."""
    return str(uuid.uuid5(NAMESPACE, key_id))


def validate_api_key(api_key: str) -> None:
    """Validate API key meets minimum entropy requirements."""
    if len(api_key) < 16:
        print(f"WARNING: API key '{api_key}' is too short (< 16 chars)", file=sys.stderr)
        print("  Recommendation: Use high-entropy keys (32+ chars)", file=sys.stderr)
        print('  Example: openssl rand -base64 32', file=sys.stderr)
        print("", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nError: Provide at least one API key as argument\n", file=sys.stderr)
        sys.exit(1)
    
    server_secret = get_server_secret()
    api_keys = sys.argv[1:]
    entries = []
    workspace_ids = []  # Track for uniqueness check
    
    print("# Generated API key mappings (add to .env)")
    print("# " + "=" * 70)
    print()
    
    for api_key in api_keys:
        validate_api_key(api_key)
        
        key_id = generate_key_id(api_key, server_secret)
        workspace_id = generate_workspace_id(key_id)
        entry = f"{key_id}:{workspace_id}"
        entries.append(entry)
        workspace_ids.append(workspace_id)
        
        print(f"# API Key: {api_key}")
        print(f"# HMAC-SHA256: {key_id}")
        print(f"# Workspace: {workspace_id}")
        print()
    
    print("# Add this to your .env file:")
    print(f"RAG_API_KEYS={','.join(entries)}")
    print()
    
    # Verify uniqueness (only in this batch, not global)
    if len(workspace_ids) != len(set(workspace_ids)):
        print("ERROR: Duplicate workspace_id detected in this batch!", file=sys.stderr)
        print("This should be mathematically impossible with UUIDv5.", file=sys.stderr)
        print("Please report this as a bug.", file=sys.stderr)
        sys.exit(1)
    
    print(f"✓ Generated {len(entries)} API key mapping(s)")
    print("✓ All workspace_id values are unique in this batch")
    print("✓ Accidental workspace collisions are negligibly unlikely with UUIDv5")
    print()
    print("IMPORTANT:")
    print("  - Store RAG_SERVER_SECRET securely and consistently across deployments")
    print("  - Do NOT change RAG_SERVER_SECRET after keys are generated (breaks auth)")
    print("  - Use different server secrets for dev/staging/prod if isolation needed")


if __name__ == "__main__":
    main()
