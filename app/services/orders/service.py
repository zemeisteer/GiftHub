import random
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.exceptions import (
    GiftHubException,
    InsufficientBalanceError,
    InvalidOrderStateError,
    OrderNotFoundError,
)
from app.core.logging import get_logger
from app.models.audit import AdminAuditLog
from app.models.base import utc_now
from app.models.order import (
    CheckoutIdempotency,
    Order,
    OrderStatus,
    OrderStatusHistory,
    normalize_status,
    validate_order_transition,
)
from app.models.pricing import PricingSetting
from app.models.user import User
from app.services.feature_flags.service import feature_flag_service
from app.services.outbox.service import outbox_service
from app.services.pricing.service import pricing_service
from app.services.promotions.service import promotion_service
from app.services.referrals.service import referral_service
from app.services.risk.service import risk_service
from app.services.wallet.service import wallet_service

logger = get_logger(__name__)


class OrderService:
    @staticmethod
    def generate_order_code() -> str:
        """Generates public user-facing order code format: GH-XXXXXX"""
        return f"GH-{random.randint(100000, 999999)}"

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
        payment_method: str = "balance",
        idempotency_key: str | None = None,
        correlation_id: str | None = None
    ) -> tuple[Order, Decimal, User | None]:
        """
        Creates and processes a new purchase order with server-side authoritative pricing,
        checkout-level idempotency, outbox event dispatch, and fraud/spam verification.
        """
        cid = correlation_id or get_correlation_id()

        # 0. Check feature flags & maintenance mode
        if await feature_flag_service.is_maintenance_mode(session):
            raise GiftHubException("Platforma texnik ta'mirlash rejimida. Iltimos birozdan so'ng qayta urinib ko'ring.")
        if not await feature_flag_service.is_enabled(session, "store_checkout_enabled", default=True):
            raise GiftHubException("Xarid qilish tizimi vaqtincha to'xtatilgan.")

        # Check product-specific flag
        flag_map = {
            "stars": "stars_purchases_enabled",
            "premium": "premium_purchases_enabled",
            "gift": "gifts_purchases_enabled"
        }
        if product_type in flag_map:
            if not await feature_flag_service.is_enabled(session, flag_map[product_type], default=True):
                raise GiftHubException(f"{product_type.title()} xaridlari vaqtincha o'chirilgan.")

        # 0.1 Check checkout spam
        if not await risk_service.check_checkout_spam(session, user_id):
            raise GiftHubException("Ko'p sonli to'lanmagan buyurtmalar aniqlandi. Iltimos, avval mavjud buyurtmalaringizni to'lang.")

        # 0.2 Checkout-level Idempotency Check
        if idempotency_key:
            stmt_idemp = select(CheckoutIdempotency).where(
                CheckoutIdempotency.idempotency_key == idempotency_key,
                CheckoutIdempotency.user_id == user_id
            )
            res_idemp = await session.execute(stmt_idemp)
            existing_idemp = res_idemp.scalars().first()
            if existing_idemp and existing_idemp.order_id:
                existing_order = await session.get(Order, existing_idemp.order_id)
                if existing_order:
                    logger.info(f"[Checkout Idempotency] Duplicate request returning existing order {existing_order.order_code}")
                    return existing_order, Decimal("0.00"), None

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

        pricing_setting = await session.get(PricingSetting, 1)
        exchange_rate = Decimal(str(pricing_setting.ton_rate_uzs)) if (pricing_setting and pricing_setting.ton_rate_uzs) else Decimal("14800.00")
        order_margin = max(Decimal("0.00"), payable_price - cost_price)

        # 4. Create Order Record with Immutable Financial Snapshot
        order = Order(
            order_code=order_code,
            user_id=user_id,
            product_type=product_type,
            item_title=item_title,
            amount=amount,
            unit_price=unit_price,
            total_price=payable_price,
            cost_price=cost_price,
            margin=order_margin,
            discount_amount=discount_amount,
            exchange_rate=exchange_rate,
            currency="UZS",
            promo_code=applied_promo,
            payment_method=payment_method,
            status=initial_status,
            recipient_username=recipient_username,
            price_lock_id=price_lock_id,
            correlation_id=cid,
            fulfillment_status="pending",
            fulfillment_attempts=0,
            created_at=now,
            paid_at=paid_at
        )
        session.add(order)
        await session.flush()

        # Record Initial Status in Order Timeline
        initial_history = OrderStatusHistory(
            order_id=order.id,
            order_code=order.order_code,
            from_status=None,
            to_status=initial_status,
            actor="USER",
            note=f"Buyurtma yaratildi: {item_title} (To'lov: {payment_method})",
            created_at=now
        )
        session.add(initial_history)

        # 5. Process Referral Bonus and Transactional Outbox if wallet paid
        bonus, referrer = (Decimal("0.00"), None)
        if is_wallet_payment:
            bonus, referrer = await referral_service.process_order_referral_reward(
                session=session,
                order_id=order.id,
                buyer_id=user_id,
                purchase_amount=payable_price
            )

            # Atomic Outbox event for fulfillment dispatch
            await outbox_service.create_event(
                session=session,
                event_type="ORDER_FULFILLMENT_REQUESTED",
                aggregate_type="order",
                aggregate_id=str(order.id),
                payload={
                    "order_id": order.id,
                    "order_code": order.order_code,
                    "user_id": user_id,
                    "product_type": product_type,
                    "amount": amount,
                    "recipient_username": recipient_username
                },
                correlation_id=cid
            )

        # 6. Save Checkout Idempotency if key provided
        if idempotency_key:
            idemp_record = CheckoutIdempotency(
                idempotency_key=idempotency_key,
                user_id=user_id,
                order_id=order.id,
                request_hash=f"{product_type}:{amount}:{payable_price}",
                response_json={"order_id": order.id, "order_code": order.order_code},
                created_at=now,
                expires_at=now + timedelta(hours=24)
            )
            session.add(idemp_record)

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
        payload: str | None = None,
        actor: str | None = None
    ) -> Order:
        """
        Transitions order status adhering to the strict order state machine.
        """
        stmt = select(Order).where(Order.id == order_id).with_for_update()
        res = await session.execute(stmt)
        order = res.scalars().first()
        if not order:
            raise OrderNotFoundError(f"Order #{order_id} topilmadi.")

        current_status = normalize_status(order.status)
        target_status = normalize_status(new_status_raw)

        if target_status == OrderStatus.REFUNDED and current_status == OrderStatus.REFUNDED:
            raise InvalidOrderStateError("Buyurtma allaqachon qaytarilgan.")

        if current_status == target_status:
            return order

        validate_order_transition(current_status, target_status)

        now = utc_now()
        order.status = target_status

        if target_status == OrderStatus.PAID:
            order.paid_at = now
        elif target_status == OrderStatus.PROCESSING:
            order.processing_at = now
            order.fulfillment_status = "processing"
        elif target_status == OrderStatus.COMPLETED:
            order.completed_at = now
            order.fulfillment_status = "fulfilled"
        elif target_status == OrderStatus.CANCELLED:
            order.cancelled_at = now
        elif target_status == OrderStatus.REFUNDED:
            order.refunded_at = now

            if not reason or len(reason.strip()) < 5:
                raise GiftHubException("Buyurtmani qaytarish (refund) uchun kamida 5 belgidan iborat sabab ko'rsatilishi shart.")

            # Process refund balance restoration if paid
            if current_status in (OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.COMPLETED, OrderStatus.FAILED):
                await wallet_service.credit_balance(
                    session=session,
                    user_id=order.user_id,
                    amount=order.total_price,
                    tx_type="refund",
                    reference_type="order_refund",
                    reference_id=order.order_code,
                    note=f"Buyurtma bekor qilindi va qaytarildi: {order.order_code}. Sabab: {reason or 'Admin'}"
                )

                # Emit Outbox event for refund notification
                await outbox_service.create_event(
                    session=session,
                    event_type="ORDER_REFUNDED",
                    aggregate_type="order",
                    aggregate_id=str(order.id),
                    payload={
                        "order_id": order.id,
                        "order_code": order.order_code,
                        "user_id": order.user_id,
                        "refund_amount": str(order.total_price),
                        "reason": reason
                    },
                    correlation_id=order.correlation_id or get_correlation_id()
                )

                if admin_id:
                    audit = AdminAuditLog(
                        admin_id=admin_id,
                        action="order_refund",
                        entity_type="order",
                        entity_id=str(order.id),
                        reason=reason,
                        details=f"Buyurtma #{order.order_code} qaytarildi ({order.total_price} UZS). Sabab: {reason or 'N/A'}",
                        created_at=now
                    )
                    session.add(audit)

        if payload:
            order.fragment_payload = payload

        # Record Status Transition in Order Timeline (Req 13)
        history = OrderStatusHistory(
            order_id=order.id,
            order_code=order.order_code,
            from_status=current_status,
            to_status=target_status,
            actor=actor or (f"ADMIN:{admin_id}" if admin_id else "SYSTEM"),
            note=reason or f"Buyurtma holati o'zgartirildi: {current_status} -> {target_status}",
            created_at=now
        )
        session.add(history)

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
        price_lock_id: str | None = None,
        idempotency_key: str | None = None
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
            payment_method=payment_method,
            idempotency_key=idempotency_key
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
            reason=reason or "Admin tomonidan qaytarildi"
        )

    @classmethod
    async def get_order_by_id_or_code(cls, session: AsyncSession, order_id_or_code: str | int) -> Order | None:
        """Resolves order by internal primary key or public user-facing code (e.g. GH-123456 or #GH-123456)."""
        if isinstance(order_id_or_code, int) or (isinstance(order_id_or_code, str) and order_id_or_code.isdigit()):
            return await session.get(Order, int(order_id_or_code))
        code = str(order_id_or_code).strip()
        stmt = select(Order).where(
            (Order.order_code == code) |
            (Order.order_code == f"#{code}") |
            (Order.order_code == code.lstrip("#"))
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @classmethod
    async def get_order_timeline(cls, session: AsyncSession, order_id_or_code: str | int) -> list[OrderStatusHistory]:
        """Returns chronological status audit timeline for the specified order."""
        order = await cls.get_order_by_id_or_code(session, order_id_or_code)
        if not order:
            return []
        stmt = select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at.asc())
        res = await session.execute(stmt)
        return list(res.scalars().all())


order_service = OrderService()
orderService = order_service
