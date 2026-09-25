from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import Order, OrderStatus, SupportTicket, TicketMessage, User
from app.services.notifications.service import notification_service
from app.services.referrals.service import referral_service
from app.services.support.service import support_service
from app.web.auth import get_current_user
from app.web.state import get_bot
from database import queries

logger = get_logger(__name__)

router = APIRouter(tags=["User & Gate"])


@router.get("/api/user/me")
async def get_me(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        # Count total orders
        res = await session.execute(
            select(func.count(Order.id)).where(Order.user_id == user.id)
        )
        orders_count = res.scalar() or 0

        # Count completed orders
        res_done = await session.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user.id,
                Order.status.in_([OrderStatus.COMPLETED, "done"])
            )
        )
        completed_orders = res_done.scalar() or 0

        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "photo_url": user.photo_url,
            "balance": round(float(user.balance)),
            "role": user.role,
            "referrals_count": user.referrals_count,
            "referral_earnings": round(float(user.referral_earnings)),
            "orders_count": orders_count,
            "completed_orders": completed_orders,
            "created_at": user.created_at.strftime("%d %b %Y") if user.created_at else ""
        }


@router.get("/api/gate/check")
async def check_gate_channels(user: User = Depends(get_current_user)):
    """Checks mandatory subscription conditions (gate screen)."""
    async with AsyncSessionLocal() as session:
        if user.id in settings.ADMINS or (user.role and user.role != "user"):
            return {"all_passed": True, "channels": []}

        channels = await queries.list_channels(session, active_only=True)
        results = []
        all_passed = True
        bot = get_bot()

        for ch in channels:
            if ch.is_detected:
                continue

            is_member = False
            if ch.req_type == "external":
                is_member = True
            elif ch.req_type == "join_request":
                has_req = False
                if ch.chat_id:
                    has_req = await queries.has_user_join_request(session, user.id, ch.chat_id)
                if not has_req and bot and ch.chat_id:
                    try:
                        chat_member = await bot.get_chat_member(chat_id=ch.chat_id, user_id=user.id)
                        has_req = chat_member.status in ["creator", "administrator", "member", "restricted"]
                    except Exception:
                        has_req = False
                is_member = has_req
            else:
                target = ch.chat_id
                if not target and ch.username_or_link:
                    val = ch.username_or_link.strip()
                    if val.startswith("@"):
                        target = val
                    elif "t.me/" in val:
                        part = val.rstrip("/").split("/")[-1]
                        if not part.startswith("+"):
                            target = f"@{part}"

                if bot and target:
                    try:
                        chat_member = await bot.get_chat_member(chat_id=target, user_id=user.id)
                        is_member = chat_member.status in ["creator", "administrator", "member", "restricted"]
                    except Exception:
                        is_member = False
                else:
                    is_member = True

            if not is_member:
                all_passed = False

            channel_title = ch.title if (ch.title and ch.title.strip()) else ch.username_or_link
            ch_link = ch.username_or_link
            if not ch_link.startswith("http"):
                ch_link = f"https://t.me/{ch_link.lstrip('@')}"

            results.append({
                "id": ch.id,
                "title": channel_title,
                "link": ch_link,
                "display_name": channel_title,
                "username": ch.username_or_link,
                "type": ch.req_type,
                "passed": is_member
            })

        return {"all_passed": all_passed, "channels": results}


@router.get("/api/referrals/analytics")
async def get_referral_analytics_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        analytics = await referral_service.get_referral_analytics(session, user.id)
        return analytics


@router.get("/api/notifications")
async def get_notifications_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        notifs = await notification_service.list_notifications(session, user.id)
        return [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "related_entity": n.related_entity,
                "is_read": n.is_read,
                "created_at": n.created_at.strftime("%d %b, %H:%M") if n.created_at else ""
            }
            for n in notifs
        ]


@router.post("/api/notifications/{notification_id}/read")
async def mark_notification_read_endpoint(notification_id: int, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ok = await notification_service.mark_as_read(session, notification_id, user.id)
        return {"success": ok}


@router.post("/api/notifications/read-all")
async def mark_all_notifications_read_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        count = await notification_service.mark_all_as_read(session, user.id)
        return {"success": True, "count": count}


class TicketCreateRequest(BaseModel):
    subject: str
    category: str = "other"
    message: str
    order_id: int | None = None


@router.post("/api/support/tickets")
async def create_ticket_endpoint(req: TicketCreateRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ticket = await support_service.create_ticket(
            session=session,
            user_id=user.id,
            subject=req.subject,
            category=req.category,
            initial_message=req.message,
            order_id=req.order_id
        )
        return {"success": True, "ticket_id": ticket.id}


@router.get("/api/support/tickets")
async def list_user_tickets_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        tickets = await support_service.list_user_tickets(session, user.id)
        return [
            {
                "id": t.id,
                "subject": t.subject,
                "category": t.category,
                "status": t.status,
                "order_id": t.order_id,
                "created_at": t.created_at.strftime("%d %b, %H:%M") if t.created_at else ""
            }
            for t in tickets
        ]


@router.get("/api/support/tickets/{ticket_id}/messages")
async def get_ticket_messages_endpoint(ticket_id: int, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket or (ticket.user_id != user.id and user.role == "user" and user.id not in settings.ADMINS):
            raise HTTPException(status_code=404, detail="Murojaat topilmadi")

        res = await session.execute(
            select(TicketMessage).where(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at)
        )
        messages = res.scalars().all()
        return [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "sender_type": m.sender_type,
                "text": m.text,
                "created_at": m.created_at.strftime("%d %b, %H:%M") if m.created_at else ""
            }
            for m in messages
        ]


class TicketReplyRequest(BaseModel):
    text: str


@router.post("/api/support/tickets/{ticket_id}/reply")
async def reply_ticket_endpoint(ticket_id: int, req: TicketReplyRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Murojaat topilmadi")

        sender_type = "admin" if (user.role != "user" or user.id in settings.ADMINS) else "user"
        msg = await support_service.add_reply(
            session=session,
            ticket_id=ticket_id,
            sender_id=user.id,
            sender_type=sender_type,
            text=req.text
        )
        return {"success": True, "message_id": msg.id}
