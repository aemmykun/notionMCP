"""Minimal signed load test for governed read paths.

Examples:
    python minimal_load_test.py --path /health --requests 20 --concurrency 5
    python minimal_load_test.py --path /rag_tool/resource.list --requests 20 --concurrency 5
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import hmac
import json
import os
from pathlib import Path
import statistics
import time
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


_ENV = {**_load_env_file(), **dict(os.environ)}

BASE_URL = _ENV.get("LOAD_TEST_BASE_URL", "http://127.0.0.1:8080")
API_KEY = _ENV.get("INTEGRATION_TEST_API_KEY", "local-resource-test-key")
WORKSPACE_ID = _ENV.get("LOAD_TEST_WORKSPACE_ID", "5f549ae7-db3a-57f2-a5e7-3344f6e4013c")
ACTOR_ID = _ENV.get("LOAD_TEST_ACTOR_ID", "actor-local")
ACTOR_TYPE = _ENV.get("LOAD_TEST_ACTOR_TYPE", "user")
ACTOR_SECRET = _ENV.get("ACTOR_SIGNING_SECRET", "")
RESOURCE_MEMBER_ID = _ENV.get("RESOURCE_LIST_MEMBER_ID", "22222222-2222-2222-2222-222222222222")
RESOURCE_TYPE = _ENV.get("RESOURCE_LIST_EXPECTED_TYPE", "plan")


def sign_headers() -> dict[str, str]:
    timestamp = str(int(time.time()))
    message = f"{ACTOR_ID}:{ACTOR_TYPE}:{WORKSPACE_ID}:{timestamp}".encode()
    signature = hmac.new(ACTOR_SECRET.encode(), message, hashlib.sha256).hexdigest()
    return {
        "X-API-Key": API_KEY,
        "X-Actor-Id": ACTOR_ID,
        "X-Actor-Type": ACTOR_TYPE,
        "X-Actor-Timestamp": timestamp,
        "X-Actor-Signature": signature,
        "Content-Type": "application/json",
    }


def send_request(path: str) -> tuple[int, float]:
    headers = sign_headers() if path != "/health" else {"X-API-Key": API_KEY}
    data = None
    if path == "/rag_tool/resource.list":
        payload = {
            "memberId": RESOURCE_MEMBER_ID,
            "resourceType": RESOURCE_TYPE,
            "limit": 10,
            "requestId": f"load-{time.time_ns()}",
        }
        data = json.dumps(payload).encode()
    request = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers)
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return response.status, elapsed_ms


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a minimal governed-path load test")
    parser.add_argument("--path", default="/health")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    if args.path != "/health" and not ACTOR_SECRET:
        print("ACTOR_SIGNING_SECRET is required for signed governed-path load tests")
        return 1

    latencies: list[float] = []
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(send_request, args.path) for _ in range(args.requests)]
        for future in concurrent.futures.as_completed(futures):
            try:
                status, latency = future.result()
                latencies.append(latency)
                if status != 200:
                    failures += 1
            except (urllib.error.URLError, TimeoutError):
                failures += 1

    success = len(latencies) - failures
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies, default=0.0)
    print(f"path={args.path}")
    print(f"requests={args.requests}")
    print(f"concurrency={args.concurrency}")
    print(f"success={success}")
    print(f"failures={failures}")
    print(f"avg_ms={statistics.mean(latencies):.1f}" if latencies else "avg_ms=0.0")
    print(f"p95_ms={p95:.1f}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())