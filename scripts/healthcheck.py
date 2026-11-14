"""Docker HEALTHCHECK for each GiftHub runtime mode.

Usage:
    python scripts/healthcheck.py api      # GET http://localhost:$WEB_PORT/health
    python scripts/healthcheck.py worker   # worker heartbeat in Redis is fresh

Exits 0 when healthy, 1 otherwise. Deliberately does not import the app package,
so the check stays fast and does not open DB connections.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# Worker writes the heartbeat every cycle (~2s) with a 60s TTL; allow some slack for slow cycles.
WORKER_HEARTBEAT_MAX_AGE = 90
WORKER_HEARTBEAT_KEY = "gifthub:worker:heartbeat"


def check_api() -> bool:
    port = os.getenv("WEB_PORT", "8000")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=4) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"api unhealthy: {e}")
        return False


def check_worker() -> bool:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("worker unhealthy: REDIS_URL is not set, heartbeat cannot be checked")
        return False
    try:
        import redis

        client = redis.Redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
        raw = client.get(WORKER_HEARTBEAT_KEY)
    except Exception as e:
        print(f"worker unhealthy: Redis error: {e}")
        return False
    if not raw:
        print("worker unhealthy: no heartbeat in Redis")
        return False
    try:
        last = datetime.fromisoformat(json.loads(raw)["last_heartbeat"])
    except Exception as e:
        print(f"worker unhealthy: malformed heartbeat: {e}")
        return False
    age = (datetime.now(timezone.utc) - last).total_seconds()
    if age > WORKER_HEARTBEAT_MAX_AGE:
        print(f"worker unhealthy: last heartbeat {age:.0f}s ago")
        return False
    return True


CHECKS = {"api": check_api, "combined": check_api, "worker": check_worker}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "api"
    check = CHECKS.get(mode)
    if check is None:
        print(f"unknown mode: {mode} (expected one of: {', '.join(CHECKS)})")
        sys.exit(1)
    sys.exit(0 if check() else 1)
