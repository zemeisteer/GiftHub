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

@router.get("/api/admin/orders")
async def get_admin_orders(
    search: str | None = None,
    status: str | None = None,
    product_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    admin: User = Depends(require_permission(Permission.ORDERS_READ))
):
    async with AsyncSessionLocal() as session:
        orders = await queries.list_all_orders(session, search=search, status=status, product_type=product_type, limit=limit, offset=offset)
        result = []
        for o in orders:
            u = await session.get(User, o.user_id)
            result.append({
                "id": o.id,
                "order_code": o.order_code,
                "user_id": o.user_id,
                "username": f"@{u.username}" if u and u.username else (u.first_name if u else "Noma'lum"),
                "product_type": o.product_type,
                "item_title": o.item_title,
                "amount": o.amount,
                "total_price": round(float(o.total_price)),
                "cost_price": round(float(o.cost_price)),
                "status": o.status,
                "recipient_username": o.recipient_username,
                "fulfillment_status": o.fulfillment_status or "pending",
                "fragment_payload": o.fragment_payload,
                "fragment_tx_hash": o.fragment_tx_hash,
                "fulfillment_error": o.fulfillment_error,
                "created_at": o.created_at.strftime("%d %b, %H:%M") if o.created_at else ""
            })
        return result


class OrderStatusUpdate(BaseModel):
    status: str
    reason: str | None = None


@router.post("/api/admin/orders/{order_id}/status")
async def update_order_status_endpoint(
    order_id: int,
    req: OrderStatusUpdate,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        order = await queries.update_order_status(
            session=session,
            order_id=order_id,
            new_status=req.status,
            admin_id=admin.id,
            reason=req.reason
        )
        if not order:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

        refund_amount = float(order.total_price) if req.status in ("cancel", OrderStatus.CANCELLED, OrderStatus.REFUNDED) else 0.0
        asyncio.create_task(
            send_order_status_update_notification(
                bot=get_bot(),
                user_id=order.user_id,
                order_code=order.order_code,
                item_title=order.item_title,
                new_status=req.status,
                refund_amount=refund_amount
            )
        )
        return {"success": True, "status": order.status}


class RefundRequest(BaseModel):
    reason: str


@router.post("/api/admin/orders/{order_id}/refund")
async def refund_order_endpoint(
    order_id: int,
    req: RefundRequest,
    admin: User = Depends(require_permission(Permission.ORDERS_REFUND))
):
    """Issues an idempotent refund with traceable wallet ledger transaction and audit log."""
    async with AsyncSessionLocal() as session:
        try:
            order = await order_service.transition_order_status(
                session=session,
                order_id=order_id,
                new_status_raw=OrderStatus.REFUNDED,
                admin_id=admin.id,
                reason=req.reason
            )
            # Notify customer
            asyncio.create_task(
                send_order_status_update_notification(
                    bot=get_bot(),
                    user_id=order.user_id,
                    order_code=order.order_code,
                    item_title=order.item_title,
                    new_status="refunded",
                    refund_amount=float(order.total_price)
                )
            )
            return {"success": True, "status": order.status, "refund_amount": float(order.total_price)}
        except GiftHubException as e:
            raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/api/admin/orders/{order_id}/retry-fulfillment")
async def retry_fulfillment_endpoint(
    order_id: int,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    """Manually retries automated order fulfillment."""
    async with AsyncSessionLocal() as session:
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Yetkazib berishni qayta ishga tushirdi",
            entity_type="order",
            entity_id=str(order_id)
        )
        res = await fulfillment_service.fulfill_order_automated(session=session, order_id=order_id, bot=get_bot())
        return res



@router.post("/api/admin/orders/{order_id}/fulfill-fragment")
async def fulfill_order_fragment_endpoint(
    order_id: int,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    from app.services.fragment import fragment_client
    res = await fragment_client.fulfill_order(order_id=order_id, bot=get_bot())
    return res


@router.post("/api/admin/orders/{order_id}/mark-fulfilled")
async def mark_order_fulfilled_endpoint(
    order_id: int,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        order = await queries.update_order_fulfillment(
            session=session,
            order_id=order_id,
            fulfillment_status="fulfilled",
            status=OrderStatus.COMPLETED
        )
        if not order:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Fragment yetkazishni bajarildi deb belgiladi: {order.order_code}",
            details="Admin tomonidan qo'lda tasdiqlandi"
        )
        return {"success": True, "fulfillment_status": "fulfilled"}



@router.get("/api/admin/export/orders.csv")
async def export_orders_csv(admin: User = Depends(require_permission(Permission.ORDERS_READ))):
    async with AsyncSessionLocal() as session:
        orders = await queries.list_all_orders(session, limit=1000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Buyurtma kodi", "User ID", "Mahsulot", "Miqdor", "Summa (UZS)", "Tannarx (UZS)", "Holat", "Sana"])
        for o in orders:
            writer.writerow([
                o.id,
                o.order_code,
                o.user_id,
                o.item_title,
                o.amount,
                round(float(o.total_price)),
                round(float(o.cost_price)),
                o.status,
                o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else ""
            ])
        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=gifthub_orders.csv"}
        )


# ================= CUSTOM SERVICES API ================= #

