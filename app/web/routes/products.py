import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.core.exceptions import GiftHubException
from app.models.payment import PaymentSetting
from app.models.user import User
from app.services.pricing.service import pricing_service
from app.services.promotions.service import promotion_service
from app.web.auth import get_current_user
from database import queries

router = APIRouter(tags=["Products & Pricing"])


@router.get("/api/products")
async def get_products(stars_amount: int | None = None, session: AsyncSession = Depends(get_db)):
    """Returns calculated product packages for Stars, Premium, and Gifts with authoritative pricing."""
    pricing = await queries.get_pricing(session)

    popular_amounts = [50, 100, 250, 500, 1000]
    stars_packages = []
    for amt in popular_amounts:
        calc = pricing_service.calculate_stars_price(amt, pricing)
        stars_packages.append(
            {
                "amount": amt,
                "name": f"{amt} ⭐",
                "price_uzs": calc["total_price_uzs"],
                "discount_pct": calc["discount_percent"],
                "formatted_price": calc["formatted_price"],
            }
        )

    custom_calc = None
    if stars_amount and stars_amount > 0:
        custom_calc = pricing_service.calculate_stars_price(stars_amount, pricing)

    try:
        prem_data = json.loads(pricing.premium_prices_json)
    except Exception:
        prem_data = {"3": 142000, "6": 210000, "12": 380000}

    premium_packages = [
        {"months": 3, "name": "Premium — 3 oy", "price_uzs": prem_data.get("3", 142000), "icon": "💎"},
        {"months": 6, "name": "Premium — 6 oy", "price_uzs": prem_data.get("6", 210000), "icon": "💎"},
        {"months": 12, "name": "Premium — 12 oy", "price_uzs": prem_data.get("12", 380000), "icon": "👑"},
    ]

    try:
        gifts_list = json.loads(pricing.gifts_json) if pricing and pricing.gifts_json else []
    except Exception:
        gifts_list = []

    payment_setting = await session.get(PaymentSetting, 1)
    payment_methods = []
    card_info = None
    if payment_setting:
        if getattr(payment_setting, "card_active", True):
            c_num = getattr(payment_setting, "card_number", "8600 1234 5678 9012")
            c_holder = getattr(payment_setting, "card_holder", "ANVAR S.")
            b_name = getattr(payment_setting, "bank_name", "TBC Bank")
            card_info = {"card_number": c_num, "card_holder": c_holder, "bank_name": b_name}
            payment_methods.append(
                {
                    "id": "card",
                    "name": "Karta orqali to'lov",
                    "icon": "💳",
                    "type": "card",
                    "card_number": c_num,
                    "card_holder": c_holder,
                    "bank_name": b_name,
                }
            )
        if payment_setting.click_active:
            payment_methods.append({"id": "click", "name": "Click", "icon": "💳", "type": "official"})
        if payment_setting.payme_active:
            payment_methods.append({"id": "payme", "name": "Payme", "icon": "💳", "type": "official"})
        if payment_setting.autopaycard_active:
            payment_methods.append({"id": "autopaycard", "name": "AutoPayCard (Karta)", "icon": "⚠️", "type": "backup"})

    star_base_cost = float(pricing.star_unit_price_uzs or 180.0)
    margin = float(pricing.margin_percent or 15.0)
    star_sell = round(star_base_cost * (1 + margin / 100), 2)

    return {
        "stars_unit_cost_uzs": star_base_cost,
        "stars_unit_sell_uzs": star_sell,
        "stars_packages": stars_packages,
        "custom_stars_calc": custom_calc,
        "premium_packages": premium_packages,
        "gifts": gifts_list,
        "payment_methods": payment_methods,
        "card_info": card_info,
    }


class PriceLockRequest(BaseModel):
    product_type: str
    amount: int = 1


@router.post("/api/checkout/price-lock")
async def create_price_lock_endpoint(req: PriceLockRequest, user: User = Depends(get_current_user)):
    """Creates a temporary price lock for checkout."""
    async with AsyncSessionLocal() as session:
        lock = await pricing_service.create_price_lock(
            session=session, product_type=req.product_type, amount=req.amount, user_id=user.id
        )
        now = datetime.now(timezone.utc)
        time_left = max(0, int((lock.expires_at - now).total_seconds()))
        return {
            "success": True,
            "lock_id": lock.id,
            "product_type": lock.product_type,
            "amount": lock.amount,
            "total_price_uzs": float(lock.total_price),
            "unit_price_uzs": float(lock.unit_price),
            "expires_at": lock.expires_at.isoformat(),
            "time_left_seconds": time_left,
        }


class PromoApplyRequest(BaseModel):
    code: str
    order_total: float = 0.0
    product_type: str = "all"


@router.post("/api/promo/apply")
async def apply_promocode_endpoint(req: PromoApplyRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        try:
            res = await promotion_service.apply_promo_code(
                session=session,
                code_str=req.code,
                user_id=user.id,
                order_total=Decimal(str(req.order_total)),
                product_type=req.product_type,
            )
            return res
        except GiftHubException as e:
            return {"success": False, "detail": e.message}
