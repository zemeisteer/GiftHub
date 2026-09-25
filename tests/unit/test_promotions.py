from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PromoCodeExpiredError, PromoCodeLimitReachedError
from app.models.promo import PromoCode
from app.models.user import User
from app.services.promotions.service import promo_service


@pytest.mark.asyncio
async def test_apply_valid_percentage_promo(db_session: AsyncSession, sample_user: User):
    code = PromoCode(
        code="PERCENT10",
        reward_type="discount_percent",
        reward_value=Decimal("10.00"),
        max_discount=Decimal("20000.00"),
        min_order_amount=Decimal("50000.00"),
        max_uses=100,
        max_uses_per_user=1,
        is_active=True
    )
    db_session.add(code)
    await db_session.commit()

    order_amount = Decimal("100000.00")
    res = await promo_service.apply_promo_code(
        session=db_session,
        code_str="PERCENT10",
        user_id=sample_user.id,
        order_total=order_amount,
        product_type="stars"
    )
    assert res["success"] is True
    # 10% of 100,000 = 10,000
    assert Decimal(str(res["discount_amount"])) == Decimal("10000.0")


@pytest.mark.asyncio
async def test_apply_expired_promo(db_session: AsyncSession, sample_user: User):
    code = PromoCode(
        code="EXPIRED10",
        reward_type="fixed_discount",
        reward_value=Decimal("10000.00"),
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    db_session.add(code)
    await db_session.commit()

    with pytest.raises(PromoCodeExpiredError):
        await promo_service.apply_promo_code(
            session=db_session,
            code_str="EXPIRED10",
            user_id=sample_user.id,
            order_total=Decimal("50000.00"),
            product_type="stars"
        )


@pytest.mark.asyncio
async def test_apply_promo_user_limit_exceeded(db_session: AsyncSession, sample_user: User):
    code = PromoCode(
        code="ONCEONLY",
        reward_type="fixed_discount",
        reward_value=Decimal("5000.00"),
        max_uses_per_user=1,
        is_active=True
    )
    db_session.add(code)
    await db_session.commit()

    # First redemption with order_id=1
    await promo_service.apply_promo_code(
        session=db_session,
        code_str="ONCEONLY",
        user_id=sample_user.id,
        order_total=Decimal("50000.00"),
        product_type="stars",
        order_id=1
    )

    # Second redemption attempt should fail because max_uses_per_user=1
    with pytest.raises(PromoCodeLimitReachedError):
        await promo_service.apply_promo_code(
            session=db_session,
            code_str="ONCEONLY",
            user_id=sample_user.id,
            order_total=Decimal("50000.00"),
            product_type="stars"
        )
