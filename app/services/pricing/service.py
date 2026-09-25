import json
import uuid
from datetime import timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import GiftHubException, PriceExpiredError
from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.pricing import PriceLock, PricingSetting

logger = get_logger(__name__)

# Fragment baseline constants
FRAGMENT_STAR_BASE_UZS = Decimal("176.46")
FRAGMENT_PREMIUM_BASE_UZS = {
    "3": Decimal("138000.00"),
    "6": Decimal("205000.00"),
    "12": Decimal("375000.00")
}
DEFAULT_GIFTS = [
    {"id": "bear", "name": "Teddy Bear", "price_uzs": 64000, "cost_uzs": 50000, "icon": "🧸", "type": "3d"},
    {"id": "heart", "name": "Neon Heart", "price_uzs": 85000, "cost_uzs": 68000, "icon": "💖", "type": "3d"},
    {"id": "rocket", "name": "Cosmo Rocket", "price_uzs": 120000, "cost_uzs": 95000, "icon": "🚀", "type": "3d"},
    {"id": "star", "name": "Cosmic Star", "price_uzs": 60000, "cost_uzs": 45000, "icon": "⭐", "type": "classic"},
    {"id": "ring", "name": "Diamond Ring", "price_uzs": 165000, "cost_uzs": 130000, "icon": "💍", "type": "3d"},
    {"id": "trophy", "name": "Gold Trophy", "price_uzs": 195000, "cost_uzs": 155000, "icon": "🏆", "type": "vip"},
    {"id": "yacht", "name": "Luxury Yacht", "price_uzs": 270000, "cost_uzs": 220000, "icon": "🛥️", "type": "vip"},
    {"id": "crown", "name": "Ruby Crown", "price_uzs": 225000, "cost_uzs": 180000, "icon": "👑", "type": "vip"},
    {"id": "medal", "name": "Star Medal", "price_uzs": 95000, "cost_uzs": 75000, "icon": "🎖️", "type": "classic"},
    {"id": "hat", "name": "Magic Hat", "price_uzs": 78000, "cost_uzs": 60000, "icon": "🎩", "type": "classic"},
    {"id": "eagle", "name": "Flying Eagle", "price_uzs": 110000, "cost_uzs": 88000, "icon": "🦅", "type": "3d"},
    {"id": "lion", "name": "Golden Lion", "price_uzs": 175000, "cost_uzs": 140000, "icon": "🦁", "type": "vip"}
]


class PricingService:
    @staticmethod
    def round_money(val: Decimal) -> Decimal:
        """Rounds to whole sum according to UZS standards."""
        return val.quantize(Decimal(1), rounding=ROUND_HALF_UP)

    @classmethod
    def calculate_stars_price(cls, amount: int, pricing: PricingSetting | None = None) -> dict[str, Any]:
        """
        Calculates authoritative price for Telegram Stars with safeguards and bulk discounts.
        """
        if amount <= 0:
            raise ValueError("Stars miqdori kamida 1 bo'lishi kerak.")

        # Unit cost
        unit_cost = FRAGMENT_STAR_BASE_UZS
        if pricing and pricing.star_unit_price_uzs and Decimal(str(pricing.star_unit_price_uzs)) > 0:
            unit_cost = Decimal(str(pricing.star_unit_price_uzs))

        # Margin with minimum safeguard
        margin_pct = Decimal(str(pricing.margin_percent)) if (pricing and pricing.margin_percent is not None) else Decimal("15.00")
        min_margin = Decimal(str(pricing.minimum_margin)) if (pricing and pricing.minimum_margin is not None) else Decimal("5.00")
        effective_margin = max(margin_pct, min_margin)

        unit_sell = unit_cost * (Decimal("1.00") + (effective_margin / Decimal("100.00")))

        base_total = unit_sell * Decimal(amount)
        cost_total = unit_cost * Decimal(amount)

        # Bulk discounts with maximum safeguard
        applied_discount = Decimal("0.00")
        max_discount = Decimal(str(pricing.maximum_discount)) if (pricing and pricing.maximum_discount is not None) else Decimal("30.00")

        if pricing and pricing.stars_discounts_json:
            try:
                discounts = json.loads(pricing.stars_discounts_json)
                sorted_disc = sorted(discounts, key=lambda x: x.get("min_amount", 0), reverse=True)
                for d in sorted_disc:
                    if amount >= d.get("min_amount", 0):
                        raw_disc = Decimal(str(d.get("discount_pct", 0)))
                        applied_discount = min(raw_disc, max_discount)
                        break
            except Exception:
                applied_discount = Decimal("0.00")

        discount_multiplier = Decimal("1.00") - (applied_discount / Decimal("100.00"))
        final_total = cls.round_money(base_total * discount_multiplier)

        # Minimum price safeguard
        min_price = Decimal(str(pricing.minimum_price)) if (pricing and pricing.minimum_price is not None) else Decimal("1000.00")
        if final_total < min_price and amount >= 10:
            final_total = min_price

        return {
            "amount": amount,
            "unit_cost_uzs": float(unit_cost),
            "unit_sell_uzs": float(cls.round_money(unit_sell)),
            "margin_percent": float(effective_margin),
            "discount_percent": float(applied_discount),
            "total_price_uzs": float(final_total),
            "total_price_decimal": final_total,
            "cost_total_uzs": float(cls.round_money(cost_total)),
            "cost_total_decimal": cls.round_money(cost_total),
            "formatted_price": f"{int(final_total):,} so'm".replace(",", " ")
        }

    @classmethod
    def calculate_premium_price(cls, months: int, pricing: PricingSetting | None = None) -> dict[str, Any]:
        """Calculates authoritative Telegram Premium subscription price."""
        m_str = str(months)
        base_cost = FRAGMENT_PREMIUM_BASE_UZS.get(m_str, Decimal("140000.00"))

        if pricing and pricing.premium_prices_json:
            try:
                p_map = json.loads(pricing.premium_prices_json)
                if m_str in p_map:
                    sell_price = Decimal(str(p_map[m_str]))
                    return {
                        "months": months,
                        "base_cost_uzs": float(base_cost),
                        "total_price_uzs": float(sell_price),
                        "total_price_decimal": sell_price,
                        "cost_total_decimal": base_cost,
                        "formatted_price": f"{int(sell_price):,} so'm".replace(",", " ")
                    }
            except Exception as e:
                logger.warning(f"telegram_premium_json ni o'qishda xatolik: {e}")

        sell_price = base_cost + Decimal("5000.00")
        return {
            "months": months,
            "base_cost_uzs": float(base_cost),
            "total_price_uzs": float(sell_price),
            "total_price_decimal": sell_price,
            "cost_total_decimal": base_cost,
            "formatted_price": f"{int(sell_price):,} so'm".replace(",", " ")
        }

    @classmethod
    def calculate_gift_price(cls, gift_id: str, pricing: PricingSetting | None = None) -> dict[str, Any]:
        """Calculates authoritative Gift price from catalog."""
        gifts_list = DEFAULT_GIFTS
        if pricing and pricing.gifts_json:
            try:
                parsed = json.loads(pricing.gifts_json)
                if parsed:
                    gifts_list = parsed
            except Exception as e:
                logger.warning(f"gifts_json ni o'qishda xatolik: {e}")

        for g in gifts_list:
            if g.get("id") == gift_id:
                p = Decimal(str(g.get("price_uzs", 60000)))
                c = Decimal(str(g.get("cost_uzs", 45000)))
                return {
                    "id": gift_id,
                    "name": g.get("name"),
                    "total_price_uzs": float(p),
                    "total_price_decimal": p,
                    "cost_total_decimal": c,
                    "formatted_price": f"{int(p):,} so'm".replace(",", " ")
                }

        fallback_p = Decimal("60000.00")
        fallback_c = Decimal("45000.00")
        return {
            "id": gift_id,
            "name": gift_id.title(),
            "total_price_uzs": float(fallback_p),
            "total_price_decimal": fallback_p,
            "cost_total_decimal": fallback_c,
            "formatted_price": f"{int(fallback_p):,} so'm".replace(",", " ")
        }

    @classmethod
    async def get_authoritative_price(
        cls,
        session: AsyncSession,
        product_type: str,
        amount: int,
        item_title: str | None = None
    ) -> dict[str, Any]:
        """
        CRITICAL SECURITY METHOD: Calculates authoritative backend price.
        Client-supplied prices are completely ignored to prevent tampering.
        """
        res = await session.execute(select(PricingSetting).where(PricingSetting.id == 1))
        pricing = res.scalars().first()

        p_type = product_type.lower()
        if p_type == "stars":
            return cls.calculate_stars_price(amount=amount, pricing=pricing)
        elif p_type == "premium":
            return cls.calculate_premium_price(months=amount, pricing=pricing)
        elif p_type == "gift":
            gift_id = (item_title or "").lower().replace(" ", "")
            return cls.calculate_gift_price(gift_id=gift_id, pricing=pricing)
        elif p_type == "service":
            # Lookup custom service
            from app.models.services import CustomService
            res_srv = await session.execute(
                select(CustomService).where(CustomService.name == item_title, CustomService.is_active == True)
            )
            srv = res_srv.scalars().first()
            if srv:
                p = Decimal(str(srv.price_uzs))
                c = Decimal(str(srv.cost_uzs))
                return {
                    "total_price_decimal": p,
                    "cost_total_decimal": c,
                    "total_price_uzs": float(p),
                    "formatted_price": f"{int(p):,} so'm".replace(",", " ")
                }
            raise GiftHubException(f"Xizmat topilmadi yoki faol emas: {item_title}")
        else:
            raise GiftHubException(f"Noma'lum mahsulot turi: {product_type}")

    @classmethod
    async def create_price_lock(
        cls,
        session: AsyncSession,
        product_type: str,
        amount: int,
        user_id: int | None = None
    ) -> PriceLock:
        """
        Creates a checkout price lock valid for configured duration (e.g., 10 minutes).
        """
        price_data = await cls.get_authoritative_price(session, product_type, amount)
        res = await session.execute(select(PricingSetting).where(PricingSetting.id == 1))
        pricing = res.scalars().first()

        lock_id = f"pl_{uuid.uuid4().hex[:16]}"
        now = utc_now()
        expires_at = now + timedelta(seconds=settings.PRICE_LOCK_SECONDS)

        ton_rate = Decimal(str(pricing.ton_rate_uzs)) if pricing else Decimal("14800.00")
        margin = Decimal(str(pricing.margin_percent)) if pricing else Decimal("15.00")

        lock = PriceLock(
            id=lock_id,
            product_type=product_type,
            amount=amount,
            unit_price=price_data.get("unit_sell_uzs", price_data["total_price_uzs"]),
            total_price=price_data["total_price_decimal"],
            cost_price=price_data["cost_total_decimal"],
            ton_rate_snapshot=ton_rate,
            margin_snapshot=margin,
            discount_snapshot=Decimal(str(price_data.get("discount_percent", 0.0))),
            user_id=user_id,
            is_used=False,
            expires_at=expires_at,
            created_at=now
        )
        session.add(lock)
        await session.commit()
        await session.refresh(lock)
        logger.info(f"[Price Lock Created] id={lock_id}, product={product_type}, total={lock.total_price}, expires_at={expires_at}")
        return lock

    @classmethod
    async def validate_or_consume_price_lock(
        cls,
        session: AsyncSession,
        lock_id: str,
        product_type: str,
        amount: int
    ) -> PriceLock:
        """
        Validates active price lock and marks it as consumed upon order placement.
        """
        lock = await session.get(PriceLock, lock_id)
        if not lock:
            raise PriceExpiredError("Narx qulfi topilmadi.")

        if lock.is_used:
            raise PriceExpiredError("Ushbu narx qulfi allaqachon ishlatilgan.")

        now = utc_now()
        # Ensure timezone-aware comparison
        lock_expires = lock.expires_at
        if lock_expires.tzinfo is None:
            lock_expires = lock_expires.replace(tzinfo=timezone.utc)

        if now > lock_expires:
            raise PriceExpiredError("Narx qulflangan vaqt muddati tugagan. Iltimos, qaytadan hisoblang.")

        if lock.product_type != product_type or lock.amount != amount:
            raise GiftHubException("Narx qulfidagi mahsulot parametrlari mos kelmadi.")

        lock.is_used = True
        return lock


pricing_service = PricingService()
