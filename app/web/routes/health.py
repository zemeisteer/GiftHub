import time
from datetime import datetime, timezone

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.services.providers.circuit_breaker import circuit_breaker
from app.services.worker import get_worker_status
from app.web.state import get_bot, get_bot_username

logger = get_logger(__name__)

router = APIRouter(tags=["Health & Probes"])


@router.get("/health/live")
@router.get("/health")
async def liveness_probe():
    """Liveness probe: verifies application process is running and event loop is responsive."""
    return {
        "status": "healthy",
        "live": True,
        "app": "GiftHub",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/ready")
@router.get("/ready")
async def readiness_probe():
    """
    Readiness probe: deeply evaluates critical dependencies (PostgreSQL, Redis, Workers, Providers).
    Returns 200 OK if service is ready to accept traffic, or 503 if any critical dependency is unavailable.
    """
    db_ok = False
    db_latency_ms = None
    redis_ok = False
    redis_latency_ms = None

    # 1. PostgreSQL / Database Probe
    t0 = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
            db_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    except Exception as e:
        logger.error(f"Readiness probe: Database connectivity failed: {e}")

    # 2. Redis Probe
    r_client = get_redis_client()
    if r_client:
        t0 = time.perf_counter()
        try:
            pong = await r_client.ping()
            redis_ok = bool(pong)
            redis_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        except Exception as e:
            logger.warning(f"Readiness probe: Redis ping failed: {e}")
            redis_ok = False
    else:
        # In non-production, Redis may be optional fallback
        redis_ok = settings.ENVIRONMENT != "production"

    # 3. Worker Status (Distributed Redis Heartbeat, Req 8 & 9)
    from app.services.worker import get_distributed_worker_heartbeat

    worker_hb = await get_distributed_worker_heartbeat()
    worker_last_hb = worker_hb.get("last_heartbeat")
    worker_alive = False
    worker_age_sec = None

    if worker_last_hb:
        try:
            hb_dt = datetime.fromisoformat(worker_last_hb)
            worker_age_sec = round((datetime.now(timezone.utc) - hb_dt).total_seconds(), 1)
            worker_alive = worker_age_sec <= 60.0
        except Exception:
            worker_alive = False
    elif settings.ENVIRONMENT != "production":
        worker_alive = True

    # 4. Critical Provider Circuit Breakers
    fragment_circuit = circuit_breaker.get_state("fragment").value
    fragment_ok = fragment_circuit != "OPEN"

    is_prod = settings.ENVIRONMENT == "production"
    critical_ok = db_ok and (redis_ok and worker_alive if is_prod else True)

    status_code = status.HTTP_200_OK if critical_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if critical_ok else "not_ready",
            "environment": settings.ENVIRONMENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dependencies": {
                "database": {"status": "healthy" if db_ok else "unhealthy", "latency_ms": db_latency_ms},
                "redis": {
                    "status": "healthy" if redis_ok else "unhealthy",
                    "latency_ms": redis_latency_ms,
                    "required": is_prod,
                },
                "worker": {
                    "status": "healthy" if worker_alive else ("stale" if worker_last_hb else "unavailable"),
                    "last_heartbeat": worker_last_hb,
                    "staleness_seconds": worker_age_sec,
                    "worker_id": worker_hb.get("worker_id"),
                    "required": is_prod,
                },
                "fragment_provider": {
                    "status": "operational" if fragment_ok else "degraded",
                    "circuit": fragment_circuit,
                },
            },
        },
    )


@router.get("/api/bot-info")
async def get_bot_info():
    uname = get_bot_username()
    bot = get_bot()
    if not uname and bot:
        try:
            b_info = await bot.get_me()
            uname = b_info.username
        except Exception as e:
            logger.warning(f"Could not fetch bot username: {e}")
    return {"username": uname or "gifthub_bot"}
