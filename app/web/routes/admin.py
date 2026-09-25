import asyncio
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select

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

router = APIRouter(tags=["Admin"])


@router.get("/api/admin/stats")
async def get_admin_dashboard(admin: User = Depends(require_permission(Permission.ANALYTICS_READ))):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func, select
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        users_total = (await session.execute(select(func.count(User.id)))).scalar() or 0
        new_users_week = (await session.execute(select(func.count(User.id)).where(User.created_at >= week_ago))).scalar() or 0

        sales_total = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        costs_total = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        profit_total = max(0.0, float(sales_total) - float(costs_total))

        ref_sales_count = (await session.execute(
            select(func.count(Order.id))
            .select_from(Order)
            .join(User, Order.user_id == User.id)
            .where(User.referrer_id.isnot(None), Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0

        stars_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "stars", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0
        stars_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "stars", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        prem_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "premium", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0
        prem_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "premium", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        gifts_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "gift", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0
        gifts_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "gift", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        month_ago = now - timedelta(days=30)
        orders_q = await session.execute(
            select(Order.total_price, Order.created_at, Order.completed_at)
            .where(Order.status.in_([OrderStatus.COMPLETED, "done"]), Order.created_at >= month_ago)
        )
        done_orders = orders_q.all()

        today_date = now.date()
        daily_chart = [
            {"label": "00-04", "start_h": 0, "end_h": 4, "sales": 0, "count": 0},
            {"label": "04-08", "start_h": 4, "end_h": 8, "sales": 0, "count": 0},
            {"label": "08-12", "start_h": 8, "end_h": 12, "sales": 0, "count": 0},
            {"label": "12-16", "start_h": 12, "end_h": 16, "sales": 0, "count": 0},
            {"label": "16-20", "start_h": 16, "end_h": 20, "sales": 0, "count": 0},
            {"label": "20-24", "start_h": 20, "end_h": 24, "sales": 0, "count": 0},
        ]
        for row in done_orders:
            dt = row.completed_at or row.created_at
            if dt and dt.date() == today_date:
                h = dt.hour
                for slot in daily_chart:
                    if slot["start_h"] <= h < slot["end_h"]:
                        slot["sales"] += round(float(row.total_price or 0))
                        slot["count"] += 1
                        break

        uz_weekdays = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
        weekly_chart = []
        for d in range(6, -1, -1):
            target_dt = (now - timedelta(days=d)).date()
            day_label = uz_weekdays[target_dt.weekday()]
            day_sales = 0
            day_count = 0
            for row in done_orders:
                dt = row.completed_at or row.created_at
                if dt and dt.date() == target_dt:
                    day_sales += round(float(row.total_price or 0))
                    day_count += 1
            weekly_chart.append({
                "label": day_label,
                "date": target_dt.strftime("%d-%m"),
                "sales": day_sales,
                "count": day_count
            })

        monthly_chart = []
        for w in range(3, -1, -1):
            start_date = (now - timedelta(days=(w+1)*7)).date()
            end_date = (now - timedelta(days=w*7)).date()
            week_label = f"{4-w}-hafta"
            week_sales = 0
            week_count = 0
            for row in done_orders:
                dt = row.completed_at or row.created_at
                if dt and start_date < dt.date() <= end_date:
                    week_sales += round(float(row.total_price or 0))
                    week_count += 1
            monthly_chart.append({
                "label": week_label,
                "range": f"{start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m')}",
                "sales": week_sales,
                "count": week_count
            })

        return {
            "users_total": users_total,
            "new_users_week": new_users_week,
            "sales_total": round(float(sales_total)),
            "profit_total": round(float(profit_total)),
            "ref_sales_count": ref_sales_count,
            "breakdown": [
                {"name": "Stars (jami)", "sales": round(float(stars_sales)), "cost": round(float(stars_cost)), "profit": round(float(stars_sales) - float(stars_cost))},
                {"name": "Premium (jami)", "sales": round(float(prem_sales)), "cost": round(float(prem_cost)), "profit": round(float(prem_sales) - float(prem_cost))},
                {"name": "Sovg'alar (jami)", "sales": round(float(gifts_sales)), "cost": round(float(gifts_cost)), "profit": round(float(gifts_sales) - float(gifts_cost))}
            ],
            "charts": {"daily": daily_chart, "weekly": weekly_chart, "monthly": monthly_chart}
        }


@router.get("/api/admin/pricing")
async def get_admin_pricing(admin: User = Depends(require_permission(Permission.PRICING_READ))):
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        frag_star_base = float(pricing.star_unit_price_uzs or 180.0)
        margin = float(pricing.margin_percent or 15.0)
        unit_sell = frag_star_base * (1 + margin / 100)

        discounts = []
        try:
            discounts = json.loads(pricing.stars_discounts_json) if pricing.stars_discounts_json else []
        except Exception:
            discounts = []

        prem_bases = {"3": 138000, "6": 205000, "12": 375000}
        prem_prices = {}
        try:
            prem_prices = json.loads(pricing.premium_prices_json) if pricing.premium_prices_json else {}
        except Exception:
            prem_prices = {"3": 143000, "6": 210000, "12": 380000}

        prem_margins = {}
        for k in ["3", "6", "12"]:
            base = prem_bases.get(k, 140000)
            curr = prem_prices.get(k, base + 5000)
            prem_margins[k] = max(0, curr - base)

        gifts = []
        try:
            gifts = json.loads(pricing.gifts_json) if pricing.gifts_json else []
        except Exception:
            gifts = []

        return {
            "stars_cost_ton": float(pricing.stars_cost_ton),
            "ton_rate_uzs": float(pricing.ton_rate_uzs),
            "margin_percent": margin,
            "fragment_stars_base_uzs": frag_star_base,
            "star_unit_price_uzs": frag_star_base,
            "unit_cost_uzs": frag_star_base,
            "unit_sell_uzs": round(unit_sell, 2),
            "discounts": discounts,
            "fragment_premium_bases": prem_bases,
            "premium_prices": prem_prices,
            "premium_margins": prem_margins,
            "gifts": gifts
        }


class PricingUpdateRequest(BaseModel):
    stars_cost_ton: float = 0.0021
    ton_rate_uzs: float = 14800.0
    margin_percent: float = 20.0
    star_unit_price_uzs: float | None = None
    discounts: list[dict[str, Any]] | None = None
    premium_prices: dict[str, Any] | None = None
    premium_margins: dict[str, Any] | None = None
    gifts: list[dict[str, Any]] | None = None


@router.post("/api/admin/pricing")
async def update_admin_pricing(req: PricingUpdateRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        disc_str = json.dumps(req.discounts) if req.discounts is not None else None
        prem_str = json.dumps(req.premium_prices) if req.premium_prices is not None else None
        gifts_str = json.dumps(req.gifts) if req.gifts is not None else None
        pricing = await queries.update_pricing(
            session=session,
            stars_cost_ton=req.stars_cost_ton,
            ton_rate_uzs=req.ton_rate_uzs,
            margin_percent=req.margin_percent,
            star_unit_price_uzs=req.star_unit_price_uzs,
            stars_discounts_json=disc_str,
            premium_prices_json=prem_str,
            gifts_json=gifts_str
        )
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Narx sozlamalarini yangiladi",
            entity_type="pricing",
            details=f"1 Stars: {req.star_unit_price_uzs} UZS, Marja: {req.margin_percent}%"
        )
        return {"success": True, "message": "Barcha narxlar muvaffaqiyatli saqlandi!"}


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


class BalanceAdjustRequest(BaseModel):
    amount: float
    reason: str


@router.post("/api/admin/users/{user_id}/adjust-balance")
async def adjust_user_balance_endpoint(
    user_id: int,
    req: BalanceAdjustRequest,
    admin: User = Depends(require_permission(Permission.ADMINS_MANAGE))
):
    """Manually adjusts user balance with required reason and immutable audit log."""
    async with AsyncSessionLocal() as session:
        user, tx = await wallet_service.adjust_balance_admin(
            session=session,
            admin_id=admin.id,
            user_id=user_id,
            amount=Decimal(str(req.amount)),
            reason=req.reason,
            admin_username=admin.username
        )
        await session.commit()
        return {
            "success": True,
            "user_id": user.id,
            "new_balance": float(user.balance),
            "amount_adjusted": req.amount
        }


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


@router.get("/api/admin/fragment/settings")
async def get_fragment_settings_endpoint(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    from app.services.fragment import fragment_client
    async with AsyncSessionLocal() as session:
        s = await queries.get_fragment_settings(session)
        balance = await fragment_client.get_wallet_balance(s.ton_wallet_address, s.network)
        return {
            "is_auto_buy": s.is_auto_buy,
            "ton_wallet_address": s.ton_wallet_address,
            "has_mnemonic": bool(s.ton_wallet_mnemonic),
            "ton_wallet_mnemonic_masked": "••••••••••••••••••••" if s.ton_wallet_mnemonic else "",
            "tonapi_key": s.tonapi_key,
            "network": s.network,
            "min_ton_balance": float(s.min_ton_balance or 1.0),
            "simulation_mode": s.simulation_mode,
            "wallet_balance_ton": balance
        }


class FragmentSettingsUpdate(BaseModel):
    is_auto_buy: bool | None = None
    ton_wallet_address: str | None = None
    ton_wallet_mnemonic: str | None = None
    tonapi_key: str | None = None
    network: str | None = None
    min_ton_balance: float | None = None
    simulation_mode: bool | None = None


@router.post("/api/admin/fragment/settings")
async def update_fragment_settings_endpoint(
    req: FragmentSettingsUpdate,
    admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        mnemonic = req.ton_wallet_mnemonic
        if mnemonic and "•••" in mnemonic:
            mnemonic = None

        s = await queries.update_fragment_settings(
            session=session,
            is_auto_buy=req.is_auto_buy,
            ton_wallet_address=req.ton_wallet_address,
            ton_wallet_mnemonic=mnemonic,
            tonapi_key=req.tonapi_key,
            network=req.network,
            min_ton_balance=req.min_ton_balance,
            simulation_mode=req.simulation_mode
        )
        return {"success": True, "message": "Fragment va TON sozlamalari muvaffaqiyatli saqlandi!"}


@router.get("/api/admin/users")
async def get_admin_users(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(require_permission(Permission.USERS_READ))
):
    async with AsyncSessionLocal() as session:
        users = await queries.list_users(session, search=search, limit=limit, offset=offset)
        from sqlalchemy import func, select
        result = []
        for u in users:
            q = await session.execute(
                select(func.count(Order.id), func.sum(Order.total_price)).where(Order.user_id == u.id, Order.status.in_([OrderStatus.COMPLETED, "done"]))
            )
            count, total = q.first()
            result.append({
                "id": u.id,
                "first_name": u.first_name,
                "username": f"@{u.username}" if u.username else str(u.id),
                "role": u.role,
                "balance": round(float(u.balance)),
                "orders_count": count or 0,
                "total_spent": round(float(total or 0.0)),
                "referrals_count": u.referrals_count,
                "created_at": u.created_at.strftime("%d %b %Y") if u.created_at else ""
            })
        return result


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

@router.get("/api/admin/payments")
async def get_payment_settings_endpoint(admin: User = Depends(require_permission(Permission.PAYMENTS_READ))):
    async with AsyncSessionLocal() as session:
        p = await session.get(PaymentSetting, 1)
        return {
            "click_active": p.click_active if p else True,
            "payme_active": p.payme_active if p else True,
            "card_active": getattr(p, "card_active", True) if p else True,
            "card_number": getattr(p, "card_number", "8600 1234 5678 9012") if p else "8600 1234 5678 9012",
            "card_holder": getattr(p, "card_holder", "ANVAR S.") if p else "ANVAR S.",
            "bank_name": getattr(p, "bank_name", "TBC Bank") if p else "TBC Bank",
            "autopaycard_active": p.autopaycard_active if p else False,
            "autopaycard_last4": p.autopaycard_last4 if p else "6412",
            "autopaycard_email": p.autopaycard_email if p else "payments.gifthub@gmail.com",
            "autopaycard_webhook_url": p.autopaycard_webhook_url if p else "https://gifthub.uz/webhook/autopaycard"
        }


class PaymentSettingsUpdate(BaseModel):
    click_active: bool = True
    payme_active: bool = True
    card_active: bool = True
    card_number: str | None = "8600 1234 5678 9012"
    card_holder: str | None = "ANVAR S."
    bank_name: str | None = "TBC Bank"
    autopaycard_active: bool = False
    autopaycard_api_key: str | None = None
    autopaycard_last4: str | None = None
    autopaycard_email: str | None = None


@router.post("/api/admin/payments")
async def update_payment_settings_endpoint(
    req: PaymentSettingsUpdate,
    admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        p = await session.get(PaymentSetting, 1)
        if not p:
            p = PaymentSetting(id=1)
            session.add(p)
        p.click_active = req.click_active
        p.payme_active = req.payme_active
        p.card_active = req.card_active
        if req.card_number is not None:
            p.card_number = req.card_number.strip()
        if req.card_holder is not None:
            p.card_holder = req.card_holder.strip()
        if req.bank_name is not None:
            p.bank_name = req.bank_name.strip()
        p.autopaycard_active = req.autopaycard_active
        if req.autopaycard_api_key is not None:
            p.autopaycard_api_key = req.autopaycard_api_key
        if req.autopaycard_last4 is not None:
            p.autopaycard_last4 = req.autopaycard_last4
        if req.autopaycard_email is not None:
            p.autopaycard_email = req.autopaycard_email
        await session.commit()
        return {"success": True}


class PaymentCardCreate(BaseModel):
    card_number: str
    card_holder: str
    bank_name: str
    card_type: str = "UZCARD"
    is_active: bool = True


class PaymentCardUpdate(BaseModel):
    card_number: str | None = None
    card_holder: str | None = None
    bank_name: str | None = None
    card_type: str | None = None
    is_active: bool | None = None


@router.get("/api/admin/cards")
async def get_admin_cards_endpoint(admin: User = Depends(require_permission(Permission.PAYMENTS_READ))):
    async with AsyncSessionLocal() as session:
        cards = await queries.list_payment_cards(session)
        return [
            {
                "id": c.id,
                "card_number": c.card_number,
                "card_holder": c.card_holder,
                "bank_name": c.bank_name,
                "card_type": c.card_type,
                "is_active": c.is_active,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""
            }
            for c in cards
        ]


@router.post("/api/admin/cards")
async def create_admin_card_endpoint(req: PaymentCardCreate, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        c = await queries.create_payment_card(
            session=session,
            card_number=req.card_number,
            card_holder=req.card_holder,
            bank_name=req.bank_name,
            card_type=req.card_type,
            is_active=req.is_active
        )
        return {"success": True, "id": c.id}


@router.put("/api/admin/cards/{card_id}")
async def update_admin_card_endpoint(card_id: int, req: PaymentCardUpdate, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        c = await queries.update_payment_card(
            session=session,
            card_id=card_id,
            card_number=req.card_number,
            card_holder=req.card_holder,
            bank_name=req.bank_name,
            card_type=req.card_type,
            is_active=req.is_active
        )
        if not c:
            raise HTTPException(status_code=404, detail="Karta topilmadi")
        return {"success": True}


@router.delete("/api/admin/cards/{card_id}")
async def delete_admin_card_endpoint(card_id: int, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ok = await queries.delete_payment_card(session, card_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Karta topilmadi")
        return {"success": True}


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
                "created_at": a.created_at.strftime("%d %b %Y") if a.created_at else ""
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
            details=f"Rol: {req.role}"
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
            entity_id=str(user_id)
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
                "created_at": log_item.created_at.strftime("%d %b, %H:%M") if log_item.created_at else ""
            }
            for log_item in logs
        ]


# ================= ADMIN SUPPORT TICKETS ================= #

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


latest_broadcast_status = {
    "is_running": False,
    "total": 0,
    "sent": 0,
    "blocked": 0,
    "failed": 0,
    "completed_at": None
}


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
                "created_at": d.created_at.strftime("%d %b, %H:%M") if d.created_at else ""
            }
        }


@router.post("/api/admin/broadcast")
async def send_broadcast_endpoint(req: BroadcastRequest, admin: User = Depends(require_permission(Permission.BROADCAST_SEND))):
    async with AsyncSessionLocal() as session:
        recipients = await queries.get_broadcast_recipients(session, req.segment)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Broadcast boshlandi: {len(recipients)} ta foydalanuvchiga",
            entity_type="broadcast",
            details=f"Segment: {req.segment}, Rejim: {req.mode}"
        )
        asyncio.create_task(run_broadcast_queue(recipients, req, admin_id=admin.id))
        return {
            "success": True,
            "recipients_count": len(recipients),
            "message": f"Broadcast {len(recipients)} ta foydalanuvchiga yuborilmoqda..."
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
        "completed_at": None
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
                    await get_bot().copy_message(chat_id=uid, from_chat_id=chat_ref, message_id=msg_id, reply_markup=reply_markup)
            elif req.photo_url and req.photo_url.startswith("http"):
                await get_bot().send_photo(chat_id=uid, photo=req.photo_url, caption=req.text or "", reply_markup=reply_markup)
            elif req.text:
                await get_bot().send_message(chat_id=uid, text=req.text, reply_markup=reply_markup)
            latest_broadcast_status["sent"] += 1
            await asyncio.sleep(0.04) # ~25-30 msgs/sec
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

class CreateServiceRequest(BaseModel):
    name: str
    price_uzs: float
    cost_uzs: float = 0.0
    category: str = "Xizmatlar"
    icon: str = "⚡"
    description: str = ""
    is_active: bool = True


class UpdateServiceRequest(BaseModel):
    name: str | None = None
    price_uzs: float | None = None
    cost_uzs: float | None = None
    category: str | None = None
    icon: str | None = None
    description: str | None = None
    is_active: bool | None = None


@router.get("/api/admin/services")
async def api_admin_list_services(admin: User = Depends(require_permission(Permission.PRICING_READ))):
    async with AsyncSessionLocal() as session:
        services = await queries.list_custom_services(session=session, active_only=False)
        return [
            {
                "id": s.id,
                "name": s.name,
                "price_uzs": float(s.price_uzs),
                "cost_uzs": float(s.cost_uzs),
                "category": s.category,
                "icon": s.icon,
                "description": s.description,
                "is_active": s.is_active,
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else ""
            }
            for s in services
        ]


@router.post("/api/admin/services")
async def api_admin_create_service(req: CreateServiceRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Xizmat nomi kiritilishi shart")
    async with AsyncSessionLocal() as session:
        s = await queries.create_custom_service(
            session=session,
            name=req.name,
            price_uzs=req.price_uzs,
            cost_uzs=req.cost_uzs,
            category=req.category,
            icon=req.icon,
            description=req.description,
            is_active=req.is_active
        )
        return {"success": True, "id": s.id, "message": "Xizmat muvaffaqiyatli qo'shildi"}


@router.put("/api/admin/services/{service_id}")
async def api_admin_update_service(service_id: int, req: UpdateServiceRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        s = await queries.update_custom_service(
            session=session,
            service_id=service_id,
            name=req.name,
            price_uzs=req.price_uzs,
            cost_uzs=req.cost_uzs,
            category=req.category,
            icon=req.icon,
            description=req.description,
            is_active=req.is_active
        )
        if not s:
            raise HTTPException(status_code=404, detail="Xizmat topilmadi")
        return {"success": True, "message": "Xizmat muvaffaqiyatli yangilandi"}


@router.delete("/api/admin/services/{service_id}")
async def api_admin_delete_service(service_id: int, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        ok = await queries.delete_custom_service(session=session, service_id=service_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Xizmat topilmadi")
        return {"success": True, "message": "Xizmat o'chirildi"}


