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

@router.get("/api/admin/support/tickets")
async def list_admin_support_tickets(
    status: str | None = None,
    limit: int = 50,
    admin: User = Depends(require_permission(Permission.SUPPORT_READ))
):
    async with AsyncSessionLocal() as session:
        tickets = await support_service.list_all_tickets(session, status=status, limit=limit)
        return [
            {
                "id": t.id,
                "user_id": t.user_id,
                "subject": t.subject,
                "category": t.category,
                "status": t.status,
                "order_id": t.order_id,
                "assigned_admin_id": t.assigned_admin_id,
                "created_at": t.created_at.strftime("%d %b, %H:%M") if t.created_at else "",
                "updated_at": t.updated_at.strftime("%d %b, %H:%M") if t.updated_at else ""
            }
            for t in tickets
        ]


class AdminTicketStatusUpdate(BaseModel):
    status: str


@router.post("/api/admin/support/tickets/{ticket_id}/status")
async def update_admin_ticket_status(
    ticket_id: int,
    req: AdminTicketStatusUpdate,
    admin: User = Depends(require_permission(Permission.SUPPORT_REPLY))
):
    async with AsyncSessionLocal() as session:
        ticket = await support_service.update_status(
            session=session,
            ticket_id=ticket_id,
            status=req.status,
            assigned_admin_id=admin.id
        )
        return {"success": True, "status": ticket.status}


# ================= BROADCAST ENDPOINTS ================= #

