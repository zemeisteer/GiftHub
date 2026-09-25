import asyncio
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import GiftHubException
from app.core.logging import get_logger
from app.core.security import Permission
from app.models import (
    BroadcastDraft,
    ChannelRequirement,
    FragmentSetting,
    Order,
    OrderStatus,
    PaymentCard,
    PaymentSetting,
    PromoCode,
    ReferralSetting,
    SupportTicket,
    TicketMessage,
    User,
)
from app.services.fulfillment.service import fulfillment_service
from app.services.orders.service import order_service
from app.services.wallet.service import wallet_service
from app.utils.notifications import (
    send_admin_order_alert,
    send_order_created_notification,
    send_order_status_update_notification,
)
from app.web.auth import get_current_admin, require_permission
from app.web.state import get_bot
from database import queries

logger = get_logger(__name__)

router = APIRouter()


from app.core.redis import get_redis_client
from app.services.providers.circuit_breaker import circuit_breaker
from app.services.worker import get_distributed_worker_heartbeat, get_worker_status


@router.get("/api/admin/system/health")
async def get_admin_system_health(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    """Admin endpoint for consolidated system health monitoring."""
    bot = get_bot()
    bot_info = {
        "status": "online" if (bot and settings.BOT_TOKEN) else "degraded",
        "has_token": bool(settings.BOT_TOKEN),
        "mode": getattr(settings, "TELEGRAM_MODE", "polling"),
    }

    # DB
    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text

            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.error(f"System health DB check failed: {e}")

    # Redis
    r_client = get_redis_client()
    redis_ok = False
    if r_client:
        try:
            pong = await r_client.ping()
            redis_ok = bool(pong)
        except Exception:
            redis_ok = False
    else:
        redis_ok = settings.ENVIRONMENT != "production"

    # Worker heartbeat
    worker_heartbeat = await get_distributed_worker_heartbeat()

    # Providers circuit breakers
    providers = {}
    for p in ["click", "payme", "autopaycard", "fragment"]:
        state = circuit_breaker.get_state(p)
        providers[p] = {"circuit": state.value, "status": "healthy" if state.value == "CLOSED" else "degraded"}

    return {
        "status": "healthy" if (db_ok and redis_ok and worker_heartbeat.get("status") == "online") else "degraded",
        "bot": bot_info,
        "database": {"status": "connected" if db_ok else "disconnected"},
        "redis": {"status": "connected" if redis_ok else "disconnected"},
        "workers": worker_heartbeat,
        "payment_providers": providers,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/api/admin/system/workers")
async def get_worker_heartbeats(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    return await get_distributed_worker_heartbeat()


@router.get("/api/admin/system/circuit-breakers")
async def get_circuit_breakers(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    return {
        p: {
            "state": circuit_breaker.get_state(p).value,
        }
        for p in ["click", "payme", "autopaycard", "fragment"]
    }


@router.post("/api/admin/system/circuit-breakers/{provider}/reset")
async def reset_circuit_breaker(provider: str, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    circuit_breaker.reset(provider)
    return {"status": "ok", "provider": provider, "state": circuit_breaker.get_state(provider).value}
