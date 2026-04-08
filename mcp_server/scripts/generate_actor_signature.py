"""Generate signed actor headers for stateless resource authorization.

Usage:
    python generate_actor_signature.py <workspace_id> <actor_id> [actor_type]

Requires:
    ACTOR_SIGNING_SECRET in the environment.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time


def sign_actor_identity(actor_id: str, actor_type: str, workspace_id: str, timestamp: str, secret: str) -> str:
    message = f"{actor_id}:{actor_type}:{workspace_id}:{timestamp}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python generate_actor_signature.py <workspace_id> <actor_id> [actor_type]")
        return 1

    workspace_id = sys.argv[1]
    actor_id = sys.argv[2]
    actor_type = sys.argv[3] if len(sys.argv) > 3 else "user"
    secret = os.getenv("ACTOR_SIGNING_SECRET", "")
    if not secret:
        print("ACTOR_SIGNING_SECRET is not set")
        return 1

    timestamp = str(int(time.time()))
    signature = sign_actor_identity(actor_id, actor_type, workspace_id, timestamp, secret)
    print(f"X-Actor-Id: {actor_id}")
    print(f"X-Actor-Type: {actor_type}")
    print(f"X-Actor-Timestamp: {timestamp}")
    print(f"X-Actor-Signature: {signature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())