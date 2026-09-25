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


