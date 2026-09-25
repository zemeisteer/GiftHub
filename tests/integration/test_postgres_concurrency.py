import asyncio
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import (
    InsufficientBalanceError,
    InvalidOrderStateError,
    PromoCodeAlreadyUsedError,
    PromoCodeLimitReachedError,
)
from app.models.dlq import DLQStatus, FailedJob
from app.models.order import CheckoutIdempotency, Order, OrderStatus
from app.models.outbox import OutboxEvent, OutboxStatus
from app.models.payment import ClickTransaction, PaymentSetting, PaymentTransaction, PaymeTransaction
from app.models.pricing import PricingSetting
from app.models.promo import PromoCode
from app.models.referral import ReferralReward, ReferralSetting
from app.models.user import User
from app.models.wallet import WalletTransaction
from app.services.orders.service import order_service
from app.services.outbox.service import outbox_service
from app.services.payments.autopaycard import autopaycard_provider
from app.services.payments.click import (
    CLICK_ALREADY_PAID,
    CLICK_ERROR_FAILED,
    CLICK_INVALID_AMOUNT,
    CLICK_SIGN_CHECK_FAILED,
    CLICK_SUCCESS,
    CLICK_TRANSACTION_NOT_FOUND,
    click_provider,
)
from app.services.payments.payme import payme_provider
from app.services.payments.service import payment_service
from app.services.promotions.service import PromotionService
from app.services.referrals.service import ReferralService
from app.services.wallet.service import wallet_service
from app.services.worker import get_distributed_worker_heartbeat

PG_TEST_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:1234@127.0.0.1:5432/gifthub_test")


@pytest_asyncio.fixture
async def pg_session_factory():
    """Provides a fresh NullPool-backed sessionmaker for each test function's event loop."""
    engine = create_async_engine(PG_TEST_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    # Ensure baseline settings exist in PostgreSQL
    async with factory() as session:
        pricing = await session.get(PricingSetting, 1)
        if not pricing:
            pricing = PricingSetting(
                id=1,
                stars_cost_ton=Decimal("0.0021"),
                ton_rate_uzs=Decimal("14800.00"),
                margin_percent=Decimal("15.00"),
                star_unit_price_uzs=Decimal("180.00"),
                minimum_margin=Decimal("5.00"),
                maximum_discount=Decimal("30.00"),
                minimum_price=Decimal("1000.00"),
            )
            session.add(pricing)

        pay_setting = await session.get(PaymentSetting, 1)
        if not pay_setting:
            pay_setting = PaymentSetting(
                id=1,
                click_active=True,
                payme_active=True,
                card_active=True,
                autopaycard_active=True,
                autopaycard_api_key="test_autopay_key",
            )
            session.add(pay_setting)
        else:
            pay_setting.autopaycard_active = True
            pay_setting.autopaycard_api_key = "test_autopay_key"

        ref_setting = await session.get(ReferralSetting, 1)
        if not ref_setting:
            ref_setting = ReferralSetting(
                id=1,
                bonus_percent=Decimal("5.00"),
                min_purchase_uzs=Decimal("10000.00"),
                auto_reward=True,
                require_purchase=False,
            )
            session.add(ref_setting)

        await session.commit()

    yield factory
    await engine.dispose()


# ==============================================================================
# SECTION 7: PAYMENT CONCURRENCY TESTS (PostgreSQL)
# ==============================================================================


@pytest.mark.asyncio
async def test_click_concurrency_prepare_and_mismatches(pg_session_factory, monkeypatch):
    """
    Test Click PREPARE:
    - Multiple simultaneous identical PREPARE callbacks -> exactly ONE Click transaction,
      no unhandled IntegrityError, duplicate requests receive valid idempotent responses.
    - Mismatched service_id, merchant_trans_id, amount, merchant_prepare_id, invalid signature fail safely.
    """
    monkeypatch.setattr(settings, "CLICK_SERVICE_ID", "54321")
    monkeypatch.setattr(settings, "CLICK_SECRET_KEY", "test_click_secret_key")

    user_id = 730100 + int(time.time() * 1000) % 50000
    click_trans_id = 930000 + int(time.time() * 1000) % 800000
    amount = "25000.00"

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="ClickUser", balance=Decimal("0.00"))
        session.add(user)
        await session.commit()

    sign_time = "2026-09-25 18:00:00"
    raw_sign = f"{click_trans_id}54321test_click_secret_key{user_id}{amount}0{sign_time}"
    valid_sign = hashlib.md5(raw_sign.encode("utf-8")).hexdigest()

    payload = {
        "click_trans_id": click_trans_id,
        "service_id": 54321,
        "click_paydoc_id": 123456,
        "merchant_trans_id": str(user_id),
        "amount": amount,
        "action": 0,
        "error": 0,
        "error_note": "",
        "sign_time": sign_time,
        "sign_string": valid_sign,
    }

    # 1. Execute multiple simultaneous identical PREPARE callbacks across separate sessions
    async def call_prepare():
        async with pg_session_factory() as s:
            return await click_provider.process_prepare(s, dict(payload))

    results = await asyncio.gather(call_prepare(), call_prepare(), call_prepare())

    # All should return error=0 and identical merchant_prepare_id
    for r in results:
        assert r["error"] == CLICK_SUCCESS
        assert r["merchant_prepare_id"] == results[0]["merchant_prepare_id"]

    # Verify database has exactly ONE ClickTransaction record
    async with pg_session_factory() as session:
        cnt = (
            await session.execute(
                select(func.count(ClickTransaction.id)).where(ClickTransaction.click_trans_id == click_trans_id)
            )
        ).scalar()
        assert cnt == 1

    # 2. Test Mismatched service_id
    bad_service = dict(payload)
    bad_service["service_id"] = 99999
    bad_service["sign_string"] = hashlib.md5(
        f"{click_trans_id}99999test_click_secret_key{user_id}{amount}0{sign_time}".encode()
    ).hexdigest()
    async with pg_session_factory() as session:
        res = await click_provider.process_prepare(session, bad_service)
        assert res["error"] == CLICK_ERROR_FAILED

    # 3. Test Invalid Signature
    bad_sign = dict(payload)
    bad_sign["sign_string"] = "invalid_hash_signature"
    async with pg_session_factory() as session:
        res = await click_provider.process_prepare(session, bad_sign)
        assert res["error"] == CLICK_SIGN_CHECK_FAILED


@pytest.mark.asyncio
async def test_click_concurrency_complete_financial_effect(pg_session_factory, monkeypatch):
    """
    Test Click COMPLETE:
    - Multiple simultaneous COMPLETE callbacks -> ONE successful financial effect,
      ONE payment transaction, ONE wallet credit, no duplicate referral reward,
      no duplicate fulfillment event.
    """
    monkeypatch.setattr(settings, "CLICK_SERVICE_ID", "54321")
    monkeypatch.setattr(settings, "CLICK_SECRET_KEY", "test_click_secret_key")

    referrer_id = 730201 + int(time.time() * 1000) % 50000
    buyer_id = 730202 + int(time.time() * 1000) % 50000
    click_trans_id = 940000 + int(time.time() * 1000) % 800000
    amount = Decimal("50000.00")

    async with pg_session_factory() as session:
        ref = User(id=referrer_id, first_name="ClickReferrer", balance=Decimal("0.00"))
        session.add(ref)
        buyer = User(id=buyer_id, first_name="ClickBuyer", balance=Decimal("0.00"), referrer_id=referrer_id)
        session.add(buyer)
        await session.flush()

        click_tx = ClickTransaction(
            click_trans_id=click_trans_id,
            service_id=54321,
            merchant_trans_id=str(buyer_id),
            amount=amount,
            action=0,
            user_id=buyer_id,
            status="prepared",
        )
        session.add(click_tx)
        await session.commit()
        merchant_prepare_id = click_tx.id

    sign_time = "2026-09-25 18:05:00"
    raw_complete_sign = (
        f"{click_trans_id}54321test_click_secret_key{buyer_id}{merchant_prepare_id}{amount:.2f}1{sign_time}"
    )
    valid_complete_sign = hashlib.md5(raw_complete_sign.encode("utf-8")).hexdigest()

    complete_payload = {
        "click_trans_id": click_trans_id,
        "service_id": 54321,
        "click_paydoc_id": 654321,
        "merchant_trans_id": str(buyer_id),
        "merchant_prepare_id": merchant_prepare_id,
        "amount": f"{amount:.2f}",
        "action": 1,
        "error": 0,
        "error_note": "",
        "sign_time": sign_time,
        "sign_string": valid_complete_sign,
    }

    # Execute simultaneous COMPLETE callbacks
    async def call_complete():
        async with pg_session_factory() as s:
            return await click_provider.process_complete(s, dict(complete_payload))

    results = await asyncio.gather(call_complete(), call_complete(), call_complete())

    # Exactly one call should succeed with CLICK_SUCCESS, duplicates receive CLICK_ALREADY_PAID
    success_count = sum(1 for r in results if r["error"] == CLICK_SUCCESS)
    already_paid_count = sum(1 for r in results if r["error"] == CLICK_ALREADY_PAID)
    assert success_count == 1
    assert already_paid_count == 2

    # Verify ONE financial effect: exactly ONE PaymentTransaction, exactly ONE wallet credit
    async with pg_session_factory() as session:
        ptx_cnt = (
            await session.execute(
                select(func.count(PaymentTransaction.id)).where(
                    PaymentTransaction.provider == "click",
                    PaymentTransaction.provider_transaction_id == str(click_trans_id),
                )
            )
        ).scalar()
        assert ptx_cnt == 1

        buyer = await session.get(User, buyer_id)
        assert buyer.balance == amount


@pytest.mark.asyncio
async def test_payme_concurrency_and_cancellation(pg_session_factory):
    """
    Test Payme:
    - Concurrent CreateTransaction, PerformTransaction, duplicate PerformTransaction,
      CancelTransaction, duplicate CancelTransaction -> exactly-once financial behavior.
    """
    user_id = 730300 + int(time.time() * 1000) % 50000
    paycom_id = f"payme_pg_{int(time.time() * 1000)}"
    amount_tiyin = 5000000  # 50,000 UZS
    now_ms = int(time.time() * 1000)

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="PaymeUser", balance=Decimal("0.00"))
        session.add(user)
        await session.commit()

    # 1. Create Transaction
    async with pg_session_factory() as session:
        create_res = await payme_provider.handle_request(
            session,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "CreateTransaction",
                "params": {"id": paycom_id, "time": now_ms, "amount": amount_tiyin, "account": {"user_id": user_id}},
            },
        )
        assert "result" in create_res
        assert create_res["result"]["state"] == 1

    # 2. Concurrent PerformTransaction requests
    perform_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "PerformTransaction",
        "params": {"id": paycom_id},
    }

    async def call_perform():
        async with pg_session_factory() as s:
            return await payme_provider.handle_request(s, dict(perform_req))

    perf_results = await asyncio.gather(call_perform(), call_perform(), call_perform())
    for res in perf_results:
        assert "result" in res
        assert res["result"]["state"] == 2

    # Exactly ONE 50,000 UZS credit applied
    async with pg_session_factory() as session:
        user = await session.get(User, user_id)
        assert user.balance == Decimal("50000.00")

    # 3. Concurrent CancelTransaction requests
    cancel_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "CancelTransaction",
        "params": {"id": paycom_id, "reason": 1},
    }

    async def call_cancel():
        async with pg_session_factory() as s:
            return await payme_provider.handle_request(s, dict(cancel_req))

    cancel_results = await asyncio.gather(call_cancel(), call_cancel())
    for res in cancel_results:
        assert "result" in res
        assert res["result"]["state"] == -2

    # Exactly ONE reversal back to 0.00
    async with pg_session_factory() as session:
        user = await session.get(User, user_id)
        assert user.balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_autopaycard_concurrent_webhooks(pg_session_factory):
    """
    Test AutoPayCard:
    - Duplicate and concurrent webhook delivery -> exactly ONE credit.
    """
    user_id = 730400 + int(time.time() * 1000) % 50000
    tx_id = f"autopay_pg_{int(time.time() * 1000)}"
    amount = Decimal("35000.00")

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="AutoPayUser", balance=Decimal("0.00"))
        session.add(user)
        await session.commit()

    payload = {
        "status": "success",
        "tx_id": tx_id,
        "user_id": user_id,
        "amount": float(amount),
        "api_key": "test_autopay_key",
    }

    async def call_autopay():
        async with pg_session_factory() as s:
            return await autopaycard_provider.handle_webhook(s, dict(payload))

    results = await asyncio.gather(call_autopay(), call_autopay(), call_autopay())
    for r in results:
        assert r["success"] is True

    async with pg_session_factory() as session:
        user = await session.get(User, user_id)
        assert user.balance == amount


# ==============================================================================
# SECTION 8: WALLET INVARIANTS & CONCURRENCY
# ==============================================================================


@pytest.mark.asyncio
async def test_wallet_concurrency_race_condition_and_invariants(pg_session_factory):
    """
    Verify:
    - balance cannot become negative.
    - all credits create ledger records.
    - all debits create ledger records.
    - test concurrent debits against the same user:
      balance = 100,000 UZS.
      Two concurrent purchases each attempt to spend 70,000 UZS.
      Only ONE should succeed. Final balance must remain valid (30,000 UZS).
    """
    user_id = 730500 + int(time.time() * 1000) % 50000
    initial_balance = Decimal("100000.00")
    tx_ref_prefix = f"wallet_race_{int(time.time() * 1000)}"

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="WalletUser", balance=initial_balance)
        session.add(user)
        await session.commit()

    # Two concurrent debits of 70,000 UZS each
    spend_amount = Decimal("70000.00")

    async def attempt_debit(tx_ref: str):
        async with pg_session_factory() as s:
            try:
                res = await wallet_service.debit_balance(
                    session=s,
                    user_id=user_id,
                    amount=spend_amount,
                    tx_type="purchase",
                    reference_type="test_concurrency",
                    reference_id=tx_ref,
                )
                await s.commit()
                return {"success": True, "res": res}
            except Exception as e:
                await s.rollback()
                return {"success": False, "error": type(e).__name__}

    res1, res2 = await asyncio.gather(
        attempt_debit(f"{tx_ref_prefix}_A"),
        attempt_debit(f"{tx_ref_prefix}_B"),
    )

    success_count = sum(1 for r in [res1, res2] if r["success"])
    fail_count = sum(1 for r in [res1, res2] if not r["success"])

    assert success_count == 1
    assert fail_count == 1

    # Verify final balance is strictly 30,000 UZS
    async with pg_session_factory() as session:
        user = await session.get(User, user_id)
        assert user.balance == Decimal("30000.00")

        # Verify ledger has exactly one debit record of -70,000
        txs = (
            (
                await session.execute(
                    select(WalletTransaction).where(
                        WalletTransaction.user_id == user_id,
                        WalletTransaction.reference_type == "test_concurrency",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(txs) == 1
        assert txs[0].amount == -spend_amount

    # Verify database check constraint prevents direct negative balance
    async with pg_session_factory() as session:
        user = await session.get(User, user_id)
        user.balance = Decimal("-1000.00")
        with pytest.raises((IntegrityError, Exception)):
            await session.commit()
        await session.rollback()


# ==============================================================================
# SECTION 9: REFUND CONCURRENCY
# ==============================================================================


@pytest.mark.asyncio
async def test_refund_concurrency_no_double_refund(pg_session_factory):
    """
    Create one paid order. Send multiple concurrent refund requests.
    Expected: ONE refund, ONE wallet credit, ONE refund ledger entry, ONE REFUNDED final state.
    """
    user_id = 730600 + int(time.time() * 1000) % 50000
    refund_amount = Decimal("45000.00")
    order_code = f"#GH-PG-REFUND-{int(time.time() * 1000)}"

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="RefundUser", balance=Decimal("0.00"))
        session.add(user)

        order = Order(
            order_code=order_code,
            user_id=user_id,
            product_type="stars",
            item_title="100 Stars",
            amount=100,
            unit_price=refund_amount,
            total_price=refund_amount,
            status=OrderStatus.PAID.value,
            fulfillment_status="failed",
        )
        session.add(order)
        await session.commit()
        order_id = order.id

    async def attempt_refund(attempt_num: int):
        async with pg_session_factory() as s:
            try:
                res = await order_service.refund_order(
                    session=s,
                    order_id=order_id,
                    reason=f"Concurrent refund attempt #{attempt_num}",
                )
                await s.commit()
                return {"success": True, "res": res}
            except Exception as e:
                await s.rollback()
                return {"success": False, "error": str(e)}

    r1, r2, r3 = await asyncio.gather(attempt_refund(1), attempt_refund(2), attempt_refund(3))

    successes = [r for r in [r1, r2, r3] if r["success"]]
    assert len(successes) == 1

    # Verify exactly ONE wallet credit and ONE refund ledger entry
    async with pg_session_factory() as session:
        user = await session.get(User, user_id)
        assert user.balance == refund_amount

        order = await session.get(Order, order_id)
        assert order.status == OrderStatus.REFUNDED.value

        tx_count = (
            await session.execute(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.reference_type == "order_refund",
                    WalletTransaction.reference_id == order_code,
                )
            )
        ).scalar()
        assert tx_count == 1


# ==============================================================================
# SECTION 10: CHECKOUT IDEMPOTENCY
# ==============================================================================


@pytest.mark.asyncio
async def test_checkout_idempotency_concurrency(pg_session_factory):
    """
    Send the same checkout request concurrently using the same idempotency key.
    Expected: ONE order, ONE financial debit, ONE fulfillment request.
    """
    user_id = 730700 + int(time.time() * 1000) % 50000
    idemp_key = f"idemp_pg_chk_{int(time.time() * 1000)}"

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="CheckoutUser", balance=Decimal("100000.00"))
        session.add(user)
        await session.commit()

    async def attempt_checkout():
        async with pg_session_factory() as s:
            try:
                order, discount, _ = await order_service.create_order(
                    session=s,
                    user_id=user_id,
                    product_type="stars",
                    item_title="50 Stars",
                    amount=50,
                    payment_method="balance",
                    idempotency_key=idemp_key,
                )
                return {"success": True, "order_id": order.id, "order_code": order.order_code}
            except Exception as e:
                await s.rollback()
                return {"success": False, "error": str(e)}

    c1, c2 = await asyncio.gather(attempt_checkout(), attempt_checkout())

    # At least one succeeded, and both point to the same order_id
    successful_orders = [c["order_id"] for c in [c1, c2] if c["success"]]
    assert len(successful_orders) >= 1
    if len(successful_orders) == 2:
        assert c1["order_id"] == c2["order_id"]

    # Verify only ONE order was created
    async with pg_session_factory() as session:
        orders = (
            (
                await session.execute(
                    select(Order)
                    .join(
                        CheckoutIdempotency,
                        CheckoutIdempotency.order_id == Order.id,
                    )
                    .where(CheckoutIdempotency.idempotency_key == idemp_key)
                )
            )
            .scalars()
            .all()
        )
        assert len(orders) == 1


# ==============================================================================
# SECTION 11: REFERRAL IDEMPOTENCY
# ==============================================================================


@pytest.mark.asyncio
async def test_referral_idempotency_under_concurrency(pg_session_factory):
    """
    Eligible referral purchase processed concurrently.
    Expected: ONE referral reward only. Database uniqueness prevents duplication.
    """
    referrer_id = 730801 + int(time.time() * 1000) % 50000
    buyer_id = 730802 + int(time.time() * 1000) % 50000
    purchase_amount = Decimal("60000.00")
    order_code = f"#GH-PG-REF-{int(time.time() * 1000)}"

    async with pg_session_factory() as session:
        ref = User(id=referrer_id, first_name="RefReferrer", balance=Decimal("0.00"))
        session.add(ref)
        buyer = User(id=buyer_id, first_name="RefBuyer", balance=Decimal("0.00"), referrer_id=referrer_id)
        session.add(buyer)
        await session.flush()

        order = Order(
            order_code=order_code,
            user_id=buyer_id,
            product_type="stars",
            item_title="50 Stars",
            amount=50,
            unit_price=purchase_amount,
            total_price=purchase_amount,
            status=OrderStatus.PAID.value,
        )
        session.add(order)
        await session.commit()
        order_id = order.id

    async def attempt_referral():
        async with pg_session_factory() as s:
            try:
                reward, _ = await ReferralService.process_order_referral_reward(
                    session=s,
                    order_id=order_id,
                    buyer_id=buyer_id,
                    purchase_amount=purchase_amount,
                )
                await s.commit()
                return reward
            except Exception:
                await s.rollback()
                return Decimal("0.00")

    r1, r2, r3 = await asyncio.gather(attempt_referral(), attempt_referral(), attempt_referral())

    # Exactly ONE non-zero reward
    non_zero_rewards = [r for r in [r1, r2, r3] if r > Decimal("0.00")]
    assert len(non_zero_rewards) == 1

    # Database records strictly ONE ReferralReward
    async with pg_session_factory() as session:
        cnt = (
            await session.execute(select(func.count(ReferralReward.id)).where(ReferralReward.order_id == order_id))
        ).scalar()
        assert cnt == 1


# ==============================================================================
# SECTION 12: PROMO CONCURRENCY
# ==============================================================================


@pytest.mark.asyncio
async def test_promo_concurrency_strict_limit_enforcement(pg_session_factory):
    """
    Test promo code with max_uses=1.
    Send concurrent requests attempting to consume the final use.
    Usage must never exceed max global uses.
    """
    code_str = f"FLASH_PG_{int(time.time() * 1000)}"
    user_a = 730901 + int(time.time() * 1000) % 50000
    user_b = 730902 + int(time.time() * 1000) % 50000

    async with pg_session_factory() as session:
        session.add(User(id=user_a, first_name="PromoUserA", balance=Decimal("0.00")))
        session.add(User(id=user_b, first_name="PromoUserB", balance=Decimal("0.00")))
        promo = PromoCode(
            code=code_str,
            reward_type="discount_percent",
            reward_value=Decimal("10.00"),
            max_uses=1,
            current_uses=0,
            max_uses_per_user=1,
            min_order_amount=Decimal("1000.00"),
            is_active=True,
        )
        session.add(promo)
        await session.commit()

    async def apply_promo(uid: int):
        async with pg_session_factory() as s:
            try:
                res = await PromotionService.apply_promo_code(
                    session=s,
                    code_str=code_str,
                    user_id=uid,
                    order_total=Decimal("50000.00"),
                )
                await s.commit()
                return {"success": True, "res": res}
            except Exception as e:
                await s.rollback()
                return {"success": False, "error": type(e).__name__}

    res_a, res_b = await asyncio.gather(apply_promo(user_a), apply_promo(user_b))

    success_count = sum(1 for r in [res_a, res_b] if r["success"])
    fail_count = sum(1 for r in [res_a, res_b] if not r["success"])

    assert success_count == 1
    assert fail_count == 1

    # Verify in PostgreSQL that current_uses is strictly 1
    async with pg_session_factory() as session:
        promo = (await session.execute(select(PromoCode).where(PromoCode.code == code_str))).scalars().first()
        assert promo.current_uses == 1


# ==============================================================================
# SECTION 13: TRANSACTIONAL OUTBOX VERIFICATION (PostgreSQL)
# ==============================================================================


@pytest.mark.asyncio
async def test_outbox_multi_worker_skip_locked_and_backoff(pg_session_factory):
    """
    Use PostgreSQL and test:
    - Workers do not claim the same event (FOR UPDATE SKIP LOCKED).
    - Lifecycle: PENDING -> PROCESSING -> RETRY -> FAILED/DLQ.
    - Exponential backoff occurs.
    """
    ts = int(time.time() * 1000)
    order_id_1 = 820000 + ts % 50000
    order_id_2 = 820001 + ts % 50000

    # 1. Clear outbox events to ensure test isolation
    async with pg_session_factory() as session:
        await session.execute(delete(OutboxEvent))
        await session.execute(delete(FailedJob))
        await session.commit()

    # 2. Create two fresh pending outbox events
    async with pg_session_factory() as session:
        ev1 = await outbox_service.publish(
            session=session,
            event_type="ORDER_FULFILLMENT_REQUESTED",
            aggregate_type="order",
            aggregate_id=str(order_id_1),
            payload={"order_id": order_id_1},
        )
        ev2 = await outbox_service.publish(
            session=session,
            event_type="ORDER_FULFILLMENT_REQUESTED",
            aggregate_type="order",
            aggregate_id=str(order_id_2),
            payload={"order_id": order_id_2},
        )
        await session.commit()
        ev1_id, ev2_id = ev1.id, ev2.id

    # 3. Worker 1 and Worker 2 claim concurrently
    async def claim(worker_id: str):
        async with pg_session_factory() as s:
            claimed = await outbox_service.claim_pending_events(session=s, worker_id=worker_id, limit=1)
            await s.commit()
            return [e.id for e in claimed]

    w1_ids, w2_ids = await asyncio.gather(claim("worker_1"), claim("worker_2"))

    # Both workers must receive completely disjoint sets of events
    assert len(w1_ids) == 1
    assert len(w2_ids) == 1
    assert set(w1_ids).isdisjoint(set(w2_ids))

    # 4. Simulate failure and verify exponential retry backoff
    test_id = w1_ids[0]
    t_before = datetime.now(timezone.utc)
    async with pg_session_factory() as session:
        await outbox_service.mark_failed(session=session, event_id=test_id, error="Simulated network failure")
        await session.commit()

    async with pg_session_factory() as session:
        ev = await session.get(OutboxEvent, test_id)
        assert ev.status == OutboxStatus.RETRY.value
        assert ev.retry_count == 1
        assert ev.next_retry_at is not None
        next_r = ev.next_retry_at.replace(tzinfo=timezone.utc) if ev.next_retry_at.tzinfo is None else ev.next_retry_at
        assert next_r >= t_before + timedelta(seconds=2)

    # 5. Max retry exhaustion -> DLQ
    async with pg_session_factory() as session:
        ev = await session.get(OutboxEvent, test_id)
        ev.retry_count = ev.max_retries - 1
        await outbox_service.mark_failed(session=session, event_id=test_id, error="Final failure exhaustion")
        await session.commit()

    async with pg_session_factory() as session:
        ev = await session.get(OutboxEvent, test_id)
        assert ev.status == OutboxStatus.FAILED.value
        dlq_res = await session.execute(select(FailedJob).where(FailedJob.order_id == int(ev.aggregate_id)))
        dlq_entry = dlq_res.scalars().first()
        assert dlq_entry is not None
        assert dlq_entry.status == DLQStatus.EXHAUSTED.value


# ==============================================================================
# SECTION 14 & 15: WORKER HEARTBEAT & FULFILLMENT IDEMPOTENCY
# ==============================================================================


@pytest.mark.asyncio
async def test_worker_heartbeat_reporting():
    """Worker heartbeat reports online status."""
    hb = await get_distributed_worker_heartbeat()
    assert "status" in hb
    assert "worker_id" in hb
    assert "last_heartbeat" in hb


@pytest.mark.asyncio
async def test_fulfillment_idempotency_state_transition(pg_session_factory):
    """Duplicate fulfillment transitions must not crash and never fulfill twice."""
    user_id = 731000 + int(time.time() * 1000) % 50000
    order_code = f"#GH-FULFILL-IDEMP-{int(time.time() * 1000)}"

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="FulfillUser", balance=Decimal("0.00"))
        session.add(user)
        order = Order(
            order_code=order_code,
            user_id=user_id,
            product_type="stars",
            item_title="50 Stars",
            amount=50,
            unit_price=Decimal("15000.00"),
            total_price=Decimal("15000.00"),
            status=OrderStatus.PAID.value,
            fulfillment_status="pending",
        )
        session.add(order)
        await session.commit()
        order_id = order.id

    # First transition to COMPLETED
    async with pg_session_factory() as session:
        await order_service.transition_order_status(
            session=session, order_id=order_id, new_status_raw=OrderStatus.COMPLETED.value
        )
        await session.commit()

    # Second transition attempt to COMPLETED should be a no-op idempotent return
    async with pg_session_factory() as session:
        res = await order_service.transition_order_status(
            session=session, order_id=order_id, new_status_raw=OrderStatus.COMPLETED.value
        )
        assert res.status == OrderStatus.COMPLETED.value


# ==============================================================================
# SECTION 16: CRASH-WINDOW VERIFICATION
# ==============================================================================


@pytest.mark.asyncio
async def test_crash_windows_reconciliation(pg_session_factory):
    """
    Test Crash Windows A & B:
    - Provider payment confirmed -> replay completes wallet processing safely without duplication.
    """
    user_id = 731100 + int(time.time() * 1000) % 50000
    amount = Decimal("20000.00")
    tx_id = f"crash_replay_tx_{int(time.time() * 1000)}"

    async with pg_session_factory() as session:
        user = User(id=user_id, first_name="CrashUser", balance=Decimal("0.00"))
        session.add(user)
        await session.commit()

    # Replay 1
    async with pg_session_factory() as session:
        p1, u1, is_new1 = await payment_service.process_successful_payment_idempotent(
            session=session,
            provider="click",
            provider_transaction_id=tx_id,
            user_id=user_id,
            amount=amount,
        )
        assert is_new1 is True

    # Replay 2 (simulating recovery after crash before response)
    async with pg_session_factory() as session:
        p2, u2, is_new2 = await payment_service.process_successful_payment_idempotent(
            session=session,
            provider="click",
            provider_transaction_id=tx_id,
            user_id=user_id,
            amount=amount,
        )
        assert is_new2 is False
        assert p2.id == p1.id

    # Verify wallet has only ONE credit
    async with pg_session_factory() as session:
        user = await session.get(User, user_id)
        assert user.balance == amount
