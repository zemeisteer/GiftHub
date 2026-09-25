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

@router.get("/api/admin/channels")
async def get_admin_channels(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    async with AsyncSessionLocal() as session:
        channels = await queries.list_channels(session, active_only=False)
        return [
            {
                "id": c.id,
                "title": c.title,
                "username_or_link": c.username_or_link,
                "req_type": c.req_type,
                "is_active": c.is_active,
                "is_detected": c.is_detected,
                "created_at": ""
            }
            for c in channels
        ]


class ChannelCreateRequest(BaseModel):
    username_or_link: str
    title: str | None = None
    req_type: str = "ordinary"
    is_detected: bool = False


@router.post("/api/admin/channels")
async def create_channel_endpoint(
    req: ChannelCreateRequest,
    admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        link = req.username_or_link.strip()
        title = (req.title or "").strip()

        if not title and get_bot():
            try:
                target = link
                if "t.me/" in target:
                    target = target.split("t.me/")[-1].split("/")[0].replace("+", "")
                if not target.startswith("@") and not target.startswith("-100") and not target.isdigit():
                    target = f"@{target}"
                chat = await get_bot().get_chat(target)
                title = chat.title or chat.full_name or link
            except Exception:
                title = link
        elif not title:
            title = link

        final_req_type = req.req_type
        if final_req_type == "ordinary":
            if "/+" in link or "joinchat" in link or link.startswith("+"):
                final_req_type = "join_request"
            elif link.startswith("http") and not ("t.me/" in link or "telegram.me/" in link):
                final_req_type = "external"

        ch = await queries.add_or_update_channel(
            session=session,
            username_or_link=link,
            title=title,
            req_type=final_req_type,
            is_detected=req.is_detected
        )
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Majburiy kanal qo'shdi/yangiladi",
            details=f"{title} ({link}, {final_req_type})"
        )
        return {"success": True, "channel_id": ch.id, "title": title, "req_type": ch.req_type}


@router.delete("/api/admin/channels/{channel_id}")
async def delete_channel_endpoint(channel_id: int, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        await queries.delete_channel(session, channel_id)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Majburiy kanalni o'chirdi (ID: {channel_id})"
        )
        return {"success": True}


@router.post("/api/admin/channels/{channel_id}/toggle")
async def toggle_channel_endpoint(channel_id: int, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ch = await session.get(ChannelRequirement, channel_id)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        ch.is_active = not ch.is_active
        await session.commit()
        return {"success": True, "is_active": ch.is_active}


class ChannelConfirmRequest(BaseModel):
    req_type: str = "ordinary"


@router.post("/api/admin/channels/{channel_id}/confirm")
async def confirm_channel_endpoint(channel_id: int, req: ChannelConfirmRequest, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ch = await queries.confirm_detected_channel(session, channel_id, req.req_type)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        return {"success": True, "channel": {"id": ch.id, "title": ch.title, "req_type": ch.req_type}}


class ChannelTypeUpdateRequest(BaseModel):
    req_type: str


@router.post("/api/admin/channels/{channel_id}/type")
async def update_channel_type_endpoint(channel_id: int, req: ChannelTypeUpdateRequest, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ch = await queries.update_channel_type(session, channel_id, req.req_type)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        return {"success": True, "channel": {"id": ch.id, "title": ch.title, "req_type": ch.req_type}}


# ================= ADMIN PROMOCODES ================= #

