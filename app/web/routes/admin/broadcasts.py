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


class BroadcastRequest(BaseModel):
    segment: str = "all"
    mode: str = "write"
    text: str | None = None
    photo_url: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    buttons: list[dict[str, str]] | None = None
    post_link: str | None = None
    forward_mode: bool = False
    postbot_code: str | None = None
    draft_id: int | None = None


latest_broadcast_status = {"is_running": False, "total": 0, "sent": 0, "blocked": 0, "failed": 0, "completed_at": None}


@router.get("/api/admin/broadcast/status")
async def get_broadcast_status(admin: User = Depends(require_permission(Permission.BROADCAST_CREATE))):
    return latest_broadcast_status


@router.get("/api/admin/broadcast/latest-draft")
async def get_latest_broadcast_draft_endpoint(admin: User = Depends(require_permission(Permission.BROADCAST_CREATE))):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        res = await session.execute(select(BroadcastDraft).order_by(BroadcastDraft.id.desc()).limit(1))
        d = res.scalars().first()
        if not d:
            return {"has_draft": False}
        return {
            "has_draft": True,
            "draft": {
                "id": d.id,
                "mode": d.mode,
                "text": d.text,
                "photo": d.photo,
                "button_text": d.button_text,
                "button_url": d.button_url,
                "forward_chat_id": d.forward_chat_id,
                "forward_message_id": d.forward_message_id,
                "created_at": d.created_at.strftime("%d %b, %H:%M") if d.created_at else "",
            },
        }


@router.post("/api/admin/broadcast")
async def send_broadcast_endpoint(
    req: BroadcastRequest, admin: User = Depends(require_permission(Permission.BROADCAST_SEND))
):
    async with AsyncSessionLocal() as session:
        recipients = await queries.get_broadcast_recipients(session, req.segment)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Broadcast boshlandi: {len(recipients)} ta foydalanuvchiga",
            entity_type="broadcast",
            details=f"Segment: {req.segment}, Rejim: {req.mode}",
        )
        asyncio.create_task(run_broadcast_queue(recipients, req, admin_id=admin.id))
        return {
            "success": True,
            "recipients_count": len(recipients),
            "message": f"Broadcast {len(recipients)} ta foydalanuvchiga yuborilmoqda...",
        }


async def run_broadcast_queue(recipients: list[int], req: BroadcastRequest, admin_id: int | None = None):
    global latest_broadcast_status
    if not get_bot():
        return

    latest_broadcast_status = {
        "is_running": True,
        "total": len(recipients),
        "sent": 0,
        "blocked": 0,
        "failed": 0,
        "completed_at": None,
    }

    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    inline_keyboard = []
    if req.buttons:
        for b in req.buttons:
            t = (b.get("text") or "").strip()
            u = (b.get("url") or "").strip()
            if t and u and (u.startswith("https://") or u.startswith("http://") or u.startswith("tg://")):
                inline_keyboard.append([InlineKeyboardButton(text=t, url=u)])
    elif req.button_text:
        b_url = req.button_url or settings.WEB_APP_URL
        if b_url.startswith("https://") or b_url.startswith("http://"):
            inline_keyboard.append([InlineKeyboardButton(text=req.button_text, url=b_url)])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard) if inline_keyboard else None

    post_info = None
    if req.post_link:
        try:
            clean_link = req.post_link.strip().rstrip("/")
            parts = clean_link.split("/")
            if len(parts) >= 2:
                msg_id = int(parts[-1])
                chat_id_or_user = parts[-2]
                if chat_id_or_user == "c" and len(parts) >= 3:
                    chat_ref = int("-100" + parts[-3])
                elif chat_id_or_user.isdigit() or chat_id_or_user.startswith("-"):
                    chat_ref = int(chat_id_or_user)
                else:
                    chat_ref = f"@{chat_id_or_user}" if not chat_id_or_user.startswith("@") else chat_id_or_user
                post_info = (chat_ref, msg_id)
        except Exception as e:
            logger.warning(f"Broadcast post link parse error: {e}")

    for uid in recipients:
        try:
            if post_info:
                chat_ref, msg_id = post_info
                if req.forward_mode:
                    await get_bot().forward_message(chat_id=uid, from_chat_id=chat_ref, message_id=msg_id)
                else:
                    await get_bot().copy_message(
                        chat_id=uid, from_chat_id=chat_ref, message_id=msg_id, reply_markup=reply_markup
                    )
            elif req.photo_url and req.photo_url.startswith("http"):
                await get_bot().send_photo(
                    chat_id=uid, photo=req.photo_url, caption=req.text or "", reply_markup=reply_markup
                )
            elif req.text:
                await get_bot().send_message(chat_id=uid, text=req.text, reply_markup=reply_markup)
            latest_broadcast_status["sent"] += 1
            await asyncio.sleep(0.04)  # ~25-30 msgs/sec
        except TelegramForbiddenError:
            latest_broadcast_status["blocked"] += 1
        except Exception:
            latest_broadcast_status["failed"] += 1

    latest_broadcast_status["is_running"] = False
    latest_broadcast_status["completed_at"] = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M")

    if admin_id and get_bot():
        report = (
            f"📢 <b>GiftHub Broadcast yakunlandi!</b>\n\n"
            f"👥 Jami: {latest_broadcast_status['total']}\n"
            f"✅ Yetkazildi: {latest_broadcast_status['sent']}\n"
            f"🚫 Bloklagan: {latest_broadcast_status['blocked']}\n"
            f"⚠️ Xatolar: {latest_broadcast_status['failed']}\n"
            f"⏱ Vaqt: {latest_broadcast_status['completed_at']}"
        )
        try:
            await get_bot().send_message(chat_id=admin_id, text=report)
        except Exception as e:
            logger.warning(f"Adminga ({admin_id}) broadcast xulosasini yuborishda xatolik: {e}")
