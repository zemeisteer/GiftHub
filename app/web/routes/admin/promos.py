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
from sqlalchemy import func, select, or_, and_

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

@router.get("/api/admin/promocodes")
async def get_admin_promocodes(admin: User = Depends(require_permission(Permission.PRICING_READ))):
    async with AsyncSessionLocal() as session:
        promos = await queries.list_promo_codes(session)
        return [
            {
                "id": p.id,
                "code": p.code,
                "reward_type": p.reward_type,
                "reward_value": float(p.reward_value),
                "max_uses": p.max_uses,
                "current_uses": p.current_uses,
                "min_order_amount": float(p.min_order_amount),
                "is_active": p.is_active,
                "created_at": p.created_at.strftime("%d %b %Y") if p.created_at else ""
            }
            for p in promos
        ]


class PromoCreateRequest(BaseModel):
    code: str
    reward_type: str = "discount_percent"
    reward_value: float = 10.0
    max_uses: int = 100
    min_order_amount: float = 0.0
    is_active: bool = True


@router.post("/api/admin/promocodes")
async def create_admin_promocode(req: PromoCreateRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        try:
            promo = await queries.create_promo_code(
                session=session,
                code=req.code,
                reward_type=req.reward_type,
                reward_value=req.reward_value,
                max_uses=req.max_uses,
                min_order_amount=req.min_order_amount,
                is_active=req.is_active
            )
            await queries.log_admin_action(
                session=session,
                admin_id=admin.id,
                admin_username=admin.username,
                action="Yangi promo-kod yaratdi",
                entity_type="promo",
                entity_id=str(promo.id),
                details=f"{promo.code} ({promo.reward_type}: {promo.reward_value})"
            )
            return {"success": True, "promo_id": promo.id}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/admin/promocodes/{promo_id}")
async def delete_admin_promocode(promo_id: int, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        deleted = await queries.delete_promo_code(session, promo_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Promo-kod topilmadi")
        return {"success": True}


@router.post("/api/admin/promocodes/{promo_id}/toggle")
async def toggle_admin_promocode(promo_id: int, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        promo = await queries.toggle_promo_code(session, promo_id)
        if not promo:
            raise HTTPException(status_code=404, detail="Promo-kod topilmadi")
        return {"success": True, "is_active": promo.is_active}


# ================= ADMIN PAYMENT SETTINGS ================= #

