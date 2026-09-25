from datetime import timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    GiftHubException,
    PromoCodeAlreadyUsedError,
    PromoCodeExpiredError,
    PromoCodeLimitReachedError,
)
from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.promo import PromoCode, PromoCodeUsage, PromoRedemption
from app.services.wallet.service import wallet_service

logger = get_logger(__name__)


class PromotionService:
    @classmethod
    async def apply_promo_code(
        cls,
        session: AsyncSession,
        code_str: str,
        user_id: int,
        order_total: Decimal,
        product_type: str = "all",
        order_id: int | None = None
    ) -> dict[str, Any]:
        """
        Atomically validates and redeems a promo code under row-level lock.
        Protects against race conditions and usage limit bypass.
        """
        clean_code = code_str.strip().upper()
        # Row-level lock on promo code
        stmt = select(PromoCode).where(PromoCode.code == clean_code).with_for_update()
        res = await session.execute(stmt)
        promo = res.scalars().first()

        if not promo:
            raise GiftHubException(f"Promo-kod topilmadi: {clean_code}", code="PROMO_NOT_FOUND", status_code=404)

        if not promo.is_active:
            raise GiftHubException("Ushbu promo-kod faol emas.", code="PROMO_INACTIVE", status_code=400)

        now = utc_now()
        if promo.starts_at:
            starts = promo.starts_at.replace(tzinfo=timezone.utc) if promo.starts_at.tzinfo is None else promo.starts_at
            if now < starts:
                raise PromoCodeExpiredError("Ushbu promo-kod hali kuchga kirmagan.")

        if promo.expires_at:
            expires = promo.expires_at.replace(tzinfo=timezone.utc) if promo.expires_at.tzinfo is None else promo.expires_at
            if now > expires:
                raise PromoCodeExpiredError("Promo-kodning amal qilish muddati tugagan.")

        if promo.current_uses >= promo.max_uses:
            raise PromoCodeLimitReachedError("Promo-koddan foydalanishning umumiy limiti tugagan.")

        # Check applicable products
        if promo.applicable_products and promo.applicable_products != "all":
            allowed = [p.strip().lower() for p in promo.applicable_products.split(",")]
            if product_type.lower() not in allowed:
                raise GiftHubException(
                    f"Ushbu promo-kod faqat quyidagi mahsulotlar uchun amal qiladi: {promo.applicable_products}",
                    code="PROMO_PRODUCT_MISMATCH"
                )

        # Check per-user usage limit
        user_usages_count_stmt = select(func.count(PromoRedemption.id)).where(
            PromoRedemption.promo_code_id == promo.id,
            PromoRedemption.user_id == user_id
        )
        count_res = await session.execute(user_usages_count_stmt)
        user_count = count_res.scalar() or 0

        if user_count >= promo.max_uses_per_user:
            raise PromoCodeAlreadyUsedError("Siz ushbu promo-koddan belgilangan limitdan ortiq foydalana olmaysiz.")

        min_order = Decimal(str(promo.min_order_amount))
        if order_total < min_order:
            raise GiftHubException(
                f"Ushbu promo-kod faqat kamida {min_order:,.0f} so'mlik buyurtmalar uchun amal qiladi.",
                code="MIN_ORDER_NOT_MET"
            )

        reward_val = Decimal(str(promo.reward_value))
        discount_amount = Decimal("0.00")

        if promo.reward_type in ("discount_percent", "percent"):
            discount_amount = (order_total * (reward_val / Decimal("100.00"))).quantize(Decimal(1))
            if promo.max_discount:
                max_d = Decimal(str(promo.max_discount))
                discount_amount = min(discount_amount, max_d)
            discount_amount = min(discount_amount, order_total)
            new_total = max(Decimal("0.00"), order_total - discount_amount)

            # Record usage
            promo.current_uses += 1
            redemption = PromoRedemption(
                promo_code_id=promo.id,
                user_id=user_id,
                order_id=order_id,
                benefit_amount=discount_amount,
                redeemed_at=now
            )
            session.add(redemption)

            # Legacy usage
            legacy_usage = PromoCodeUsage(
                promo_code_id=promo.id,
                user_id=user_id,
                benefit_amount=discount_amount,
                used_at=now
            )
            session.add(legacy_usage)
            await session.flush()

            logger.info(f"[Promo Redeemed] user={user_id}, code={clean_code}, discount={discount_amount}")
            return {
                "success": True,
                "reward_type": "discount_percent",
                "code": clean_code,
                "discount_amount": float(discount_amount),
                "discount_amount_decimal": discount_amount,
                "original_total": float(order_total),
                "new_total": float(new_total),
                "new_total_decimal": new_total,
                "message": f"🎉 {reward_val:.0f}% chegirma qo'llandi! (-{discount_amount:,.0f} so'm)"
            }

        elif promo.reward_type in ("fixed_discount", "fixed"):
            discount_amount = min(reward_val, order_total)
            new_total = max(Decimal("0.00"), order_total - discount_amount)

            promo.current_uses += 1
            redemption = PromoRedemption(
                promo_code_id=promo.id,
                user_id=user_id,
                order_id=order_id,
                benefit_amount=discount_amount,
                redeemed_at=now
            )
            session.add(redemption)

            legacy_usage = PromoCodeUsage(
                promo_code_id=promo.id,
                user_id=user_id,
                benefit_amount=discount_amount,
                used_at=now
            )
            session.add(legacy_usage)
            await session.flush()

            logger.info(f"[Promo Redeemed Fixed] user={user_id}, code={clean_code}, discount={discount_amount}")
            return {
                "success": True,
                "reward_type": "fixed_discount",
                "code": clean_code,
                "discount_amount": float(discount_amount),
                "discount_amount_decimal": discount_amount,
                "original_total": float(order_total),
                "new_total": float(new_total),
                "new_total_decimal": new_total,
                "message": f"🎉 {discount_amount:,.0f} so'm chegirma qo'llandi!"
            }

        elif promo.reward_type == "balance_bonus":
            # Direct wallet credit
            user, tx = await wallet_service.credit_balance(
                session=session,
                user_id=user_id,
                amount=reward_val,
                tx_type="promo_bonus",
                reference_type="promo",
                reference_id=str(promo.id),
                note=f"Promo-kod ({clean_code}) bonusi"
            )

            promo.current_uses += 1
            redemption = PromoRedemption(
                promo_code_id=promo.id,
                user_id=user_id,
                benefit_amount=reward_val,
                redeemed_at=now
            )
            session.add(redemption)

            legacy_usage = PromoCodeUsage(
                promo_code_id=promo.id,
                user_id=user_id,
                benefit_amount=reward_val,
                used_at=now
            )
            session.add(legacy_usage)

            logger.info(f"[Promo Redeemed Bonus] user={user_id}, code={clean_code}, bonus={reward_val}")
            return {
                "success": True,
                "reward_type": "balance_bonus",
                "code": clean_code,
                "bonus_amount": float(reward_val),
                "new_balance": float(user.balance),
                "message": f"🎁 Hamyoningizga +{reward_val:,.0f} so'm bonus qo'shildi!"
            }

        raise GiftHubException(f"Noma'lum promo-kod turi: {promo.reward_type}")


promotion_service = PromotionService()
promo_service = promotion_service
