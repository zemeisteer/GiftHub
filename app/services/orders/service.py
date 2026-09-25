import random
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidOrderStateError,
    OrderNotFoundError,
)
from app.core.logging import get_logger
from app.models.audit import AdminAuditLog
from app.models.base import utc_now
from app.models.order import (
    Order,
    OrderStatus,
    normalize_status,
    validate_order_transition,
)
from app.models.user import User
from app.services.pricing.service import pricing_service
from app.services.promotions.service import promotion_service
from app.services.referrals.service import referral_service
from app.services.wallet.service import wallet_service

logger = get_logger(__name__)


class OrderService:
    @staticmethod
    def generate_order_code() -> str:
        return f"#GH-{random.randint(10000, 99999)}"

    @classmethod
    async def create_order(
        cls,
        session: AsyncSession,
        user_id: int,
        product_type: str,
        item_title: str,
        amount: int = 1,
        recipient_username: str | None = None,
        promo_code_str: str | None = None,
        price_lock_id: str | None = None,
        payment_method: str = "balance"
    ) -> tuple[Order, Decimal, User | None]:
        """
        Creates and processes a new purchase order with server-side authoritative pricing.
        Client-supplied prices are strictly ignored.
        """
        # 1. Authoritative price calculation or price lock consumption
        if price_lock_id:
            lock = await pricing_service.validate_or_consume_price_lock(
                session=session,
                lock_id=price_lock_id,
                product_type=product_type,
                amount=amount
            )
            total_price = Decimal(str(lock.total_price))
            unit_price = Decimal(str(lock.unit_price))
            cost_price = Decimal(str(lock.cost_price))
        else:
            price_info = await pricing_service.get_authoritative_price(
                session=session,
                product_type=product_type,
                amount=amount,
                item_title=item_title
            )
            total_price = price_info["total_price_decimal"]
            unit_price = (total_price / Decimal(amount)).quantize(Decimal(1)) if amount else total_price
            cost_price = price_info["cost_total_decimal"]

        # 2. Promo Code Application (if provided)
        discount_amount = Decimal("0.00")
        applied_promo = None
        if promo_code_str:
            promo_res = await promotion_service.apply_promo_code(
                session=session,
                code_str=promo_code_str,
                user_id=user_id,
                order_total=total_price,
                product_type=product_type
            )
            discount_amount = Decimal(str(promo_res.get("discount_amount", 0)))
            applied_promo = promo_res.get("code")

        payable_price = max(Decimal("0.00"), total_price - discount_amount)

        order_code = cls.generate_order_code()
        now = utc_now()
        is_wallet_payment = (payment_method.lower() in ("wallet", "balance"))

        user = None
        if is_wallet_payment:
            user, wallet_tx = await wallet_service.debit_balance(
                session=session,
                user_id=user_id,
                amount=payable_price,
                tx_type="purchase",
                reference_type="order",
                reference_id=order_code,
                note=f"{item_title} xaridi ({order_code})"
            )
            initial_status = OrderStatus.PAID
            paid_at = now
        else:
            initial_status = OrderStatus.CREATED
            paid_at = None

        # 4. Create Order Record
        order = Order(
            order_code=order_code,
            user_id=user_id,
            product_type=product_type,
            item_title=item_title,
            amount=amount,
            unit_price=unit_price,
            total_price=payable_price,
            cost_price=cost_price,
            discount_amount=discount_amount,
            promo_code=applied_promo,
            payment_method=payment_method,
            status=initial_status,
            recipient_username=recipient_username,
            price_lock_id=price_lock_id,
            fulfillment_status="pending",
            fulfillment_attempts=0,
            created_at=now,
            paid_at=paid_at
        )
        session.add(order)
        await session.flush()

        # 5. Process Referral Bonus only when paid
        bonus, referrer = (Decimal("0.00"), None)
        if is_wallet_payment:
            bonus, referrer = await referral_service.process_order_referral_reward(
                session=session,
                order_id=order.id,
                buyer_id=user_id,
                purchase_amount=payable_price
            )

        await session.commit()
        await session.refresh(order)
        logger.info(f"[Order Created] code={order_code}, user={user_id}, total={payable_price} UZS, status={initial_status}")
        return order, bonus, referrer

    @classmethod
    async def transition_order_status(
        cls,
        session: AsyncSession,
        order_id: int,
        new_status_raw: str,
        admin_id: int | None = None,
        reason: str | None = None,
        payload: str | None = None
    ) -> Order:
        """
        Transitions order status adhering to the strict order state machine.
        Handles refunds and cancellation reversals safely.
        """
        order = await session.get(Order, order_id)
        if not order:
            raise OrderNotFoundError(f"Buyurtma topilmadi: {order_id}")

        current_status = normalize_status(order.status)
        target_status = normalize_status(new_status_raw)

        if target_status == OrderStatus.REFUNDED and current_status == OrderStatus.REFUNDED:
            raise InvalidOrderStateError("Ushbu buyurtma allaqachon qaytarilgan.")

        if current_status == target_status:
            return order

        validate_order_transition(current_status, target_status)
        now = utc_now()

        # Handle REFUND
        if target_status == OrderStatus.REFUNDED and current_status != OrderStatus.REFUNDED:
            # Check if payment needs to be returned to wallet
            refund_amount = Decimal(str(order.total_price))
            if refund_amount > Decimal("0.00"):
                reason_str = reason or "Admin tasdig'i"
                await wallet_service.credit_balance(
                    session=session,
                    user_id=order.user_id,
                    amount=refund_amount,
                    tx_type="refund",
                    reference_type="order",
                    reference_id=str(order.id),
                    note=f"Qaytarilgan buyurtma: {order.order_code} ({reason_str})"
                )
            order.refunded_at = now
            if admin_id:
                audit = AdminAuditLog(
                    admin_id=admin_id,
                    action="order_refund",
                    entity_type="order",
                    entity_id=str(order.id),
                    old_value=current_status,
                    new_value=target_status,
                    reason=reason,
                    details=f"Buyurtma uchun {refund_amount:,.0f} so'm qaytarildi"
                )
                session.add(audit)

        # Handle CANCELLATION
        elif target_status == OrderStatus.CANCELLED:
            if current_status in (OrderStatus.PAID, OrderStatus.PROCESSING):
                refund_amount = Decimal(str(order.total_price))
                if refund_amount > Decimal("0.00"):
                    await wallet_service.credit_balance(
                        session=session,
                        user_id=order.user_id,
                        amount=refund_amount,
                        tx_type="refund",
                        reference_type="order",
                        reference_id=str(order.id),
                        note=f"Bekor qilingan buyurtma uchun mablag' qaytarildi: {order.order_code}"
                    )
            order.cancelled_at = now

        # Handle PAID
        elif target_status == OrderStatus.PAID:
            order.paid_at = now

        # Handle COMPLETION
        elif target_status == OrderStatus.COMPLETED:
            order.completed_at = now
            order.fulfillment_status = "fulfilled"

        # Handle PROCESSING
        elif target_status == OrderStatus.PROCESSING:
            order.processing_at = now
            order.fulfillment_status = "processing"

        order.status = target_status
        if payload is not None:
            order.fragment_payload = payload

        await session.commit()
        await session.refresh(order)
        logger.info(f"[Order Status Transition] order={order.id}, from={current_status} to={target_status}")
        return order

    @classmethod
    async def create_order_authoritative(
        cls,
        session: AsyncSession,
        user_id: int,
        product: str,
        quantity: int,
        recipient: str = "self",
        recipient_id: str | None = None,
        payment_method: str = "wallet",
        promo_code: str | None = None,
        price_lock_id: str | None = None
    ) -> Order:
        order, _, _ = await cls.create_order(
            session=session,
            user_id=user_id,
            product_type=product,
            item_title=f"{quantity} {product.title()}",
            amount=quantity,
            recipient_username=recipient_id,
            promo_code_str=promo_code,
            price_lock_id=price_lock_id,
            payment_method=payment_method
        )
        return order

    @classmethod
    async def transition_order_state(
        cls,
        session: AsyncSession,
        order_id: int,
        new_status: Any,
        admin_id: int | None = None,
        reason: str | None = None
    ) -> Order:
        status_str = new_status.value if hasattr(new_status, "value") else str(new_status)
        return await cls.transition_order_status(
            session=session,
            order_id=order_id,
            new_status_raw=status_str,
            admin_id=admin_id,
            reason=reason
        )

    @classmethod
    async def refund_order(
        cls,
        session: AsyncSession,
        order_id: int,
        admin_telegram_id: int | None = None,
        reason: str | None = None
    ) -> Order:
        return await cls.transition_order_status(
            session=session,
            order_id=order_id,
            new_status_raw=OrderStatus.REFUNDED.value,
            admin_id=admin_telegram_id,
            reason=reason
        )


order_service = OrderService()
orderService = order_service
