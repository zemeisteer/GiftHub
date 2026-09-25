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
            "gifts": gifts,
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
async def update_admin_pricing(
    req: PricingUpdateRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))
):
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
            gifts_json=gifts_str,
        )
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Narx sozlamalarini yangiladi",
            entity_type="pricing",
            details=f"1 Stars: {req.star_unit_price_uzs} UZS, Marja: {req.margin_percent}%",
        )
        return {"success": True, "message": "Barcha narxlar muvaffaqiyatli saqlandi!"}


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
            "wallet_balance_ton": balance,
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
    req: FragmentSettingsUpdate, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))
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
            simulation_mode=req.simulation_mode,
        )
        return {"success": True, "message": "Fragment va TON sozlamalari muvaffaqiyatli saqlandi!"}


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
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "",
            }
            for s in services
        ]


@router.post("/api/admin/services")
async def api_admin_create_service(
    req: CreateServiceRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))
):
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
            is_active=req.is_active,
        )
        return {"success": True, "id": s.id, "message": "Xizmat muvaffaqiyatli qo'shildi"}


@router.put("/api/admin/services/{service_id}")
async def api_admin_update_service(
    service_id: int, req: UpdateServiceRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))
):
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
            is_active=req.is_active,
        )
        if not s:
            raise HTTPException(status_code=404, detail="Xizmat topilmadi")
        return {"success": True, "message": "Xizmat muvaffaqiyatli yangilandi"}


@router.delete("/api/admin/services/{service_id}")
async def api_admin_delete_service(
    service_id: int, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))
):
    async with AsyncSessionLocal() as session:
        ok = await queries.delete_custom_service(session=session, service_id=service_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Xizmat topilmadi")
        return {"success": True, "message": "Xizmat o'chirildi"}
