from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PriceExpiredError
from app.models.pricing import PriceLock
from app.services.pricing.service import pricing_service


@pytest.mark.asyncio
async def test_calculate_stars_price_and_rounding(db_session: AsyncSession):
    res = await pricing_service.get_authoritative_price(
        session=db_session,
        product_type="stars",
        amount=50
    )
    assert res["total_price_decimal"] > Decimal(0)
    assert res["total_price_uzs"] > 0
    assert "formatted_price" in res


@pytest.mark.asyncio
async def test_bulk_discount_calculation(db_session: AsyncSession):
    # Check that bulk quantity (e.g. 1000 stars) gets bulk discount
    res_small = await pricing_service.get_authoritative_price(
        session=db_session,
        product_type="stars",
        amount=50
    )
    res_large = await pricing_service.get_authoritative_price(
        session=db_session,
        product_type="stars",
        amount=1000
    )
    price_per_star_small = res_small["total_price_decimal"] / Decimal(50)
    price_per_star_large = res_large["total_price_decimal"] / Decimal(1000)
    assert price_per_star_large <= price_per_star_small


@pytest.mark.asyncio
async def test_create_and_validate_price_lock(db_session: AsyncSession):
    lock = await pricing_service.create_price_lock(
        session=db_session,
        product_type="stars",
        amount=100,
        user_id=12345678
    )
    lock_exp = lock.expires_at.replace(tzinfo=timezone.utc) if lock.expires_at.tzinfo is None else lock.expires_at
    assert lock_exp > datetime.now(timezone.utc)
    assert lock.total_price > Decimal(0)

    # Validate active lock
    validated = await pricing_service.validate_or_consume_price_lock(
        session=db_session,
        lock_id=lock.id,
        product_type="stars",
        amount=100
    )
    assert validated.is_used is True


@pytest.mark.asyncio
async def test_expired_price_lock_raises_exception(db_session: AsyncSession):
    # Create manually expired price lock
    expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    lock = PriceLock(
        id="pl_expired_test_123",
        product_type="stars",
        amount=50,
        unit_price=Decimal("1500.00"),
        total_price=Decimal("75000.00"),
        cost_price=Decimal("60000.00"),
        ton_rate_snapshot=Decimal("14800.00"),
        margin_snapshot=Decimal("15.00"),
        user_id=12345678,
        expires_at=expired_time,
        is_used=False
    )
    db_session.add(lock)
    await db_session.commit()

    with pytest.raises(PriceExpiredError):
        await pricing_service.validate_or_consume_price_lock(
            session=db_session,
            lock_id="pl_expired_test_123",
            product_type="stars",
            amount=50
        )
