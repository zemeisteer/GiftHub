from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.order import OrderStatus
from app.models.payment import PaymentTransaction
from app.models.user import User
from app.services.wallet.service import wallet_service

logger = get_logger(__name__)


class ProcessPaymentResult(tuple):
    """Tuple subclass enabling both tuple unpacking and direct PaymentTransaction attribute access."""
    def __new__(cls, payment_tx, user, is_new):
        return super().__new__(cls, (payment_tx, user, is_new))

    @property
    def payment_tx(self):
        return self[0]

    @property
    def user(self):
        return self[1]

    @property
    def is_new(self):
        return self[2]

    def __getattr__(self, name):
        return getattr(self[0], name)


class PaymentService:
    @classmethod
    async def process_successful_payment_idempotent(
        cls,
        session: AsyncSession,
        provider: str,
        provider_transaction_id: str,
        amount: Decimal,
        user_id: int | None = None,
        telegram_id: int | None = None,
        currency: str = "UZS",
        order_id: int | None = None,
        note: str | None = None,
        raw_payload: str | None = None,
        correlation_id: str | None = None
    ) -> ProcessPaymentResult:
        """
        ATOMIC, IDEMPOTENT payment confirmation pipeline with Transactional Outbox.
        
        Guarantees that regardless of how many times a payment provider webhook is delivered:
        1. User balance is credited EXACTLY ONCE (if topup) or order is marked PAID EXACTLY ONCE.
        2. PaymentTransaction ledger record is recorded EXACTLY ONCE.
        3. Associated order is marked PAID EXACTLY ONCE.
        4. Referral bonus is awarded EXACTLY ONCE.
        5. OutboxEvent is committed ATOMICALLY for reliable downstream fulfillment.
        """
        from app.core.correlation import get_correlation_id
        from app.services.outbox.service import outbox_service
        from app.services.providers.circuit_breaker import circuit_breaker

        cid = correlation_id or get_correlation_id()
        effective_user_id = user_id or telegram_id
        if not effective_user_id:
            raise ValueError("user_id yoki telegram_id kiritilishi shart.")

        idempotency_key = f"{provider}:{provider_transaction_id}"

        # Record provider success in circuit breaker
        circuit_breaker.record_success(provider)

        # 1. Row-level lock on PaymentTransaction to handle simultaneous concurrent webhooks
        stmt = (
            select(PaymentTransaction)
            .where(
                PaymentTransaction.provider == provider,
                PaymentTransaction.provider_transaction_id == str(provider_transaction_id)
            )
            .with_for_update()
        )
        res = await session.execute(stmt)
        existing_tx = res.scalars().first()

        if existing_tx:
            if existing_tx.status == "success":
                logger.warning(
                    f"[Payment Idempotency] Duplicate webhook blocked for {provider} tx={provider_transaction_id}"
                )
                user = await session.get(User, effective_user_id)
                return ProcessPaymentResult(existing_tx, user, False)
            else:
                existing_tx.status = "success"
                existing_tx.paid_at = utc_now()
                if not existing_tx.correlation_id:
                    existing_tx.correlation_id = cid
                payment_tx = existing_tx
        else:
            payment_tx = PaymentTransaction(
                provider=provider,
                provider_transaction_id=str(provider_transaction_id),
                idempotency_key=idempotency_key,
                user_id=effective_user_id,
                order_id=order_id,
                amount=amount,
                currency=currency,
                status="success",
                correlation_id=cid,
                raw_payload=raw_payload,
                created_at=utc_now(),
                paid_at=utc_now()
            )
            session.add(payment_tx)

        # 2. If tied to an order, transition order to PAID and reward referrer
        if order_id:
            from app.services.orders.service import order_service
            from app.services.referrals.service import referral_service

            await order_service.transition_order_status(
                session=session,
                order_id=order_id,
                new_status_raw=OrderStatus.PAID.value
            )
            await referral_service.process_order_referral_reward(
                session=session,
                order_id=order_id,
                buyer_id=effective_user_id,
                purchase_amount=amount
            )

            # Atomic Outbox event for fulfillment dispatch
            await outbox_service.create_event(
                session=session,
                event_type="ORDER_FULFILLMENT_REQUESTED",
                aggregate_type="order",
                aggregate_id=str(order_id),
                payload={
                    "order_id": order_id,
                    "provider": provider,
                    "amount": str(amount),
                    "user_id": effective_user_id
                },
                correlation_id=cid
            )
            user = await session.get(User, effective_user_id)
        else:
            # 3. Direct wallet balance credit
            user, wallet_tx = await wallet_service.credit_balance(
                session=session,
                user_id=effective_user_id,
                amount=amount,
                tx_type="deposit",
                reference_type="payment",
                reference_id=idempotency_key,
                note=note or f"{provider.upper()} orqali hisob to'ldirildi (ID: {provider_transaction_id})"
            )
            await outbox_service.create_event(
                session=session,
                event_type="WALLET_DEPOSIT_COMPLETED",
                aggregate_type="user",
                aggregate_id=str(effective_user_id),
                payload={
                    "user_id": effective_user_id,
                    "amount": str(amount),
                    "provider": provider
                },
                correlation_id=cid
            )

        await session.flush()
        await session.commit()
        if user:
            await session.refresh(user)

        logger.info(
            f"[Payment Success Processed] provider={provider}, tx={provider_transaction_id}, "
            f"user={effective_user_id}, amount={amount} {currency}"
        )
        return ProcessPaymentResult(payment_tx, user, True)


payment_service = PaymentService()
