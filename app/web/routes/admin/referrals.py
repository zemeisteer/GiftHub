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

@router.get("/api/admin/referral")
async def get_referral_settings_endpoint(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    async with AsyncSessionLocal() as session:
        r = await session.get(ReferralSetting, 1)
        return {
            "bonus_percent": float(r.bonus_percent) if r else 5.0,
            "min_purchase_uzs": float(r.min_purchase_uzs) if r else 20000.0,
            "auto_reward": r.auto_reward if r else True,
            "require_purchase": r.require_purchase if r else True
        }


class ReferralSettingsUpdate(BaseModel):
    bonus_percent: float
    min_purchase_uzs: float
    auto_reward: bool
    require_purchase: bool


@router.post("/api/admin/referral")
async def update_referral_settings_endpoint(req: ReferralSettingsUpdate, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        r = await session.get(ReferralSetting, 1)
        if not r:
            r = ReferralSetting(id=1)
            session.add(r)
        r.bonus_percent = Decimal(str(req.bonus_percent))
        r.min_purchase_uzs = Decimal(str(req.min_purchase_uzs))
        r.auto_reward = req.auto_reward
        r.require_purchase = req.require_purchase
        await session.commit()
        return {"success": True}


