import socket
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_client = None
_fsm_storage = None


def is_redis_reachable(url: str, timeout: float = 0.5) -> bool:
    """Synchronously checks if the host and port in Redis URL can be connected to."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_redis_client():
    """Returns async Redis client if available and reachable."""
    global _redis_client
    if _redis_client is None and settings.REDIS_URL:
        if not is_redis_reachable(settings.REDIS_URL):
            return None
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0
            )
        except Exception as e:
            logger.warning(f"Could not connect to Redis: {e}")
            _redis_client = None
    return _redis_client


def get_fsm_storage() -> BaseStorage:
    """
    Returns Redis-backed FSM storage if Redis is available and reachable,
    falling back to MemoryStorage for local development/test.
    """
    global _fsm_storage
    if _fsm_storage is not None:
        return _fsm_storage

    if settings.REDIS_URL and is_redis_reachable(settings.REDIS_URL):
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            _fsm_storage = RedisStorage.from_url(settings.REDIS_URL)
            logger.info("Aiogram FSM configured with Redis storage.")
            return _fsm_storage
        except Exception as e:
            logger.warning(f"Failed to initialize Redis FSM storage ({e}). Falling back to MemoryStorage.")

    logger.info("Aiogram FSM configured with in-memory storage fallback.")
    _fsm_storage = MemoryStorage()
    return _fsm_storage


@asynccontextmanager
async def redis_lock(lock_key: str, timeout_seconds: int = 10):
    """
    Distributed lock context manager using Redis if available.
    """
    client = get_redis_client()
    if client:
        try:
            acquired = await client.set(f"lock:{lock_key}", "1", ex=timeout_seconds, nx=True)
            if not acquired:
                yield False
                return
            try:
                yield True
            finally:
                await client.delete(f"lock:{lock_key}")
            return
        except Exception as e:
            logger.warning(f"Redis lock error: {e}")
    # Local fallback
    yield True


async def check_rate_limit(key: str, max_requests: int = 20, window_seconds: int = 60) -> bool:
    """
    Checks rate limiting against Redis. Returns True if request is allowed, False if limit exceeded.
    """
    client = get_redis_client()
    if not client:
        return True # Soft pass if Redis is not configured

    try:
        current = await client.incr(f"ratelimit:{key}")
        if current == 1:
            await client.expire(f"ratelimit:{key}", window_seconds)
        return current <= max_requests
    except Exception as e:
        logger.warning(f"Rate limiting check error: {e}")
        return True
