from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.order import Order, OrderStatus
from app.models.referral import ReferralReward, ReferralSetting
from app.models.user import User
from app.services.wallet.service import wallet_service

logger = get_logger(__name__)


class ReferralService:
    @classmethod
    async def process_order_referral_reward(
        cls, session: AsyncSession, order_id: int, buyer_id: int, purchase_amount: Decimal
    ) -> tuple[Decimal, User | None]:
        """
        Processes referral reward for a completed/paid order idempotently.
        Guarantees that the same order NEVER creates duplicate referral bonuses.
        """
        # 1. Fetch buyer
        buyer = await session.get(User, buyer_id)
        if not buyer or not buyer.referrer_id or buyer.referrer_id == buyer.id:
            return Decimal("0.00"), None  # Self-referral prevention

        # 2. Idempotency Check: Verify if reward already exists for this order_id
        res_existing = await session.execute(select(ReferralReward).where(ReferralReward.order_id == order_id))
        if res_existing.scalars().first():
            logger.warning(f"[Referral] Duplicate reward attempt blocked for order_id={order_id}")
            return Decimal("0.00"), None

        # 3. Load referral settings
        ref_settings = await session.get(ReferralSetting, 1)
        if not ref_settings:
            return Decimal("0.00"), None

        min_spend = Decimal(str(ref_settings.min_purchase_uzs))
        if ref_settings.require_purchase and purchase_amount < min_spend:
            logger.info(f"[Referral] Order {order_id} below min spend threshold ({purchase_amount} < {min_spend})")
            return Decimal("0.00"), None

        # 4. Fetch referrer
        referrer = await session.get(User, buyer.referrer_id)
        if not referrer:
            return Decimal("0.00"), None

        # 5. Determine commission rate based on referrer's tier
        ref_count = referrer.referrals_count
        rate = Decimal(str(ref_settings.bonus_percent))

        t3_cnt = ref_settings.tier_3_count or 50
        t2_cnt = ref_settings.tier_2_count or 20
        t1_cnt = ref_settings.tier_1_count or 5

        if ref_count >= t3_cnt and ref_settings.tier_3_percent:
            rate = Decimal(str(ref_settings.tier_3_percent))
        elif ref_count >= t2_cnt and ref_settings.tier_2_percent:
            rate = Decimal(str(ref_settings.tier_2_percent))
        elif ref_count >= t1_cnt and ref_settings.tier_1_percent:
            rate = Decimal(str(ref_settings.tier_1_percent))

        commission_amount = (purchase_amount * (rate / Decimal("100.00"))).quantize(Decimal(1))
        if commission_amount <= Decimal("0.00"):
            return Decimal("0.00"), None

        # 6. Record Referral Reward (Unique constraint on order_id enforces idempotency)
        reward = ReferralReward(
            referrer_id=referrer.id,
            referred_user_id=buyer.id,
            order_id=order_id,
            commission_rate=rate,
            commission_amount=commission_amount,
            status="paid" if ref_settings.auto_reward else "pending",
        )
        session.add(reward)

        # 7. Credit wallet if auto_reward is enabled
        if ref_settings.auto_reward:
            await wallet_service.credit_balance(
                session=session,
                user_id=referrer.id,
                amount=commission_amount,
                tx_type="referral_bonus",
                reference_type="order",
                reference_id=str(order_id),
                note=f"Referal bonusi ({buyer.first_name or 'Foydalanuvchi'} xarididan, #{order_id})",
            )
            referrer.referral_earnings = Decimal(str(referrer.referral_earnings)) + commission_amount

        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            logger.warning(f"[Referral] Duplicate reward race caught for order_id={order_id}")
            return Decimal("0.00"), None

        logger.info(
            f"[Referral Reward Credited] referrer={referrer.id}, buyer={buyer.id}, "
            f"order={order_id}, amount={commission_amount} UZS, rate={rate}%"
        )
        return commission_amount, referrer

    @classmethod
    async def get_referral_analytics(cls, session: AsyncSession, user_id: int) -> dict[str, Any]:
        """Provides transparent referral statistics for a user."""
        # Total referrals
        res_total = await session.execute(select(func.count(User.id)).where(User.referrer_id == user_id))
        total_referrals = res_total.scalar() or 0

        # Purchasing referrals (users who have at least one completed order)
        res_purchasing = await session.execute(
            select(func.count(func.distinct(Order.user_id)))
            .select_from(Order)
            .join(User, Order.user_id == User.id)
            .where(User.referrer_id == user_id, Order.status.in_([OrderStatus.COMPLETED, OrderStatus.PAID, "done"]))
        )
        purchasing_referrals = res_purchasing.scalar() or 0

        # Referral revenue generated
        res_revenue = await session.execute(
            select(func.coalesce(func.sum(Order.total_price), 0))
            .select_from(Order)
            .join(User, Order.user_id == User.id)
            .where(User.referrer_id == user_id, Order.status.in_([OrderStatus.COMPLETED, OrderStatus.PAID, "done"]))
        )
        referral_revenue = Decimal(str(res_revenue.scalar() or 0))

        # Total earned commissions
        res_earned = await session.execute(
            select(func.coalesce(func.sum(ReferralReward.commission_amount), 0)).where(
                ReferralReward.referrer_id == user_id, ReferralReward.status == "paid"
            )
        )
        total_earned = Decimal(str(res_earned.scalar() or 0))

        # Current commission rate
        ref_settings = await session.get(ReferralSetting, 1)
        base_rate = float(ref_settings.bonus_percent) if ref_settings else 5.0

        return {
            "total_referrals": total_referrals,
            "purchasing_referrals": purchasing_referrals,
            "referral_revenue": float(referral_revenue),
            "total_earned": float(total_earned),
            "commission_rate": base_rate,
            "min_purchase_uzs": float(ref_settings.min_purchase_uzs) if ref_settings else 20000.0,
        }


referral_service = ReferralService()
