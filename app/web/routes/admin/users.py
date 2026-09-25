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


class BalanceAdjustRequest(BaseModel):
    amount: float
    reason: str


@router.post("/api/admin/users/{user_id}/adjust-balance")
async def adjust_user_balance_endpoint(
    user_id: int, req: BalanceAdjustRequest, admin: User = Depends(require_permission(Permission.ADMINS_MANAGE))
):
    """Manually adjusts user balance with required reason and immutable audit log."""
    async with AsyncSessionLocal() as session:
        user, tx = await wallet_service.adjust_balance_admin(
            session=session,
            admin_id=admin.id,
            user_id=user_id,
            amount=Decimal(str(req.amount)),
            reason=req.reason,
            admin_username=admin.username,
        )
        await session.commit()
        return {"success": True, "user_id": user.id, "new_balance": float(user.balance), "amount_adjusted": req.amount}


@router.get("/api/admin/users")
async def get_admin_users(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(require_permission(Permission.USERS_READ)),
):
    async with AsyncSessionLocal() as session:
        users = await queries.list_users(session, search=search, limit=limit, offset=offset)
        from sqlalchemy import func, select

        result = []
        for u in users:
            q = await session.execute(
                select(func.count(Order.id), func.sum(Order.total_price)).where(
                    Order.user_id == u.id, Order.status.in_([OrderStatus.COMPLETED, "done"])
                )
            )
            count, total = q.first()
            result.append(
                {
                    "id": u.id,
                    "first_name": u.first_name,
                    "username": f"@{u.username}" if u.username else str(u.id),
                    "role": u.role,
                    "balance": round(float(u.balance)),
                    "orders_count": count or 0,
                    "total_spent": round(float(total or 0.0)),
                    "referrals_count": u.referrals_count,
                    "created_at": u.created_at.strftime("%d %b %Y") if u.created_at else "",
                }
            )
        return result


@router.get("/api/admin/admins")
async def get_admins_list(admin: User = Depends(require_permission(Permission.ADMINS_READ))):
    async with AsyncSessionLocal() as session:
        admins = await queries.list_admins(session)
        return [
            {
                "id": a.id,
                "first_name": a.first_name,
                "username": f"@{a.username}" if a.username else str(a.id),
                "role": a.role,
                "created_at": a.created_at.strftime("%d %b %Y") if a.created_at else "",
            }
            for a in admins
        ]


class AddAdminRequest(BaseModel):
    identifier: str
    role: str


@router.post("/api/admin/admins")
async def add_admin_endpoint(req: AddAdminRequest, admin: User = Depends(require_permission(Permission.ADMINS_MANAGE))):
    async with AsyncSessionLocal() as session:
        target_user = None
        ident = req.identifier.strip()
        if ident.isdigit():
            target_user = await queries.get_user_by_id(session, int(ident))
        else:
            target_user = await queries.get_user_by_username(session, ident)

        if not target_user:
            raise HTTPException(status_code=404, detail=f"Foydalanuvchi topilmadi: {ident}")

        updated = await queries.set_user_role(session, target_user.id, req.role)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Yangi admin tayinladi: @{updated.username or updated.id}",
            entity_type="admin",
            entity_id=str(updated.id),
            details=f"Rol: {req.role}",
        )
        return {"success": True, "message": f"@{updated.username or updated.id} ga '{req.role}' roli berildi!"}


@router.delete("/api/admin/admins/{user_id}")
async def revoke_admin_endpoint(user_id: int, admin: User = Depends(require_permission(Permission.ADMINS_MANAGE))):
    async with AsyncSessionLocal() as session:
        if user_id in settings.ADMINS and admin.id != user_id:
            raise HTTPException(status_code=400, detail="Bosh adminni olib tashlab bo'lmaydi!")
        await queries.set_user_role(session, user_id, "user")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Admin huquqini bekor qildi: ID {user_id}",
            entity_type="admin",
            entity_id=str(user_id),
        )
        return {"success": True}


@router.get("/api/admin/audit-logs")
async def get_audit_logs(admin: User = Depends(require_permission(Permission.ADMINS_READ))):
    async with AsyncSessionLocal() as session:
        logs = await queries.list_audit_logs(session, limit=50)
        return [
            {
                "id": log_item.id,
                "admin": f"@{log_item.admin_username}" if log_item.admin_username else f"ID {log_item.admin_id}",
                "action": log_item.action,
                "entity_type": log_item.entity_type,
                "details": log_item.details,
                "created_at": log_item.created_at.strftime("%d %b, %H:%M") if log_item.created_at else "",
            }
            for log_item in logs
        ]


# ================= ADMIN SUPPORT TICKETS ================= #
