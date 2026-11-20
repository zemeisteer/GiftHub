from decimal import Decimal

import pytest

from app.core.exceptions import GiftHubException
from app.models.gift import TelegramGift
from app.models.pricing import PricingSetting
from app.services.pricing.service import PricingService


def test_gift_price_equals_same_number_of_stars():
    gift = TelegramGift(id="g50", star_count=50)

    price = PricingService.get_gift_price(gift, None)
    stars = PricingService.calculate_stars_price(50)

    assert price["total_price_decimal"] == stars["total_price_decimal"]
    assert price["cost_total_decimal"] == stars["cost_total_decimal"]
    assert price["total_price_uzs"] == stars["total_price_uzs"]
    assert price["formatted_price"] == stars["formatted_price"]


def test_override_replaces_sell_price_but_cost_stays_stars_cost():
    gift = TelegramGift(id="g50", star_count=50, price_override_uzs=Decimal("99999.00"))

    price = PricingService.get_gift_price(gift, None)

    assert price["total_price_decimal"] == Decimal("99999.00")
    assert price["total_price_uzs"] == 99999.0
    assert price["cost_total_decimal"] == PricingService.calculate_stars_price(50)["cost_total_decimal"]
    assert price["formatted_price"] == "99 999 so'm"


async def test_authoritative_price_for_catalog_gift(db_session):
    db_session.add(TelegramGift(id="g15", star_count=15))
    await db_session.commit()

    price = await PricingService.get_authoritative_price(db_session, "gift", 1, item_title="g15")

    pricing = await db_session.get(PricingSetting, 1)
    assert price["total_price_decimal"] == PricingService.calculate_stars_price(15, pricing)["total_price_decimal"]


@pytest.mark.parametrize("gift_id", ["missing", None, ""])
async def test_authoritative_price_for_unknown_or_disabled_gift_raises(db_session, gift_id):
    db_session.add(TelegramGift(id="off", star_count=15, enabled=False))
    await db_session.commit()

    with pytest.raises(GiftHubException):
        await PricingService.get_authoritative_price(db_session, "gift", 1, item_title=gift_id)
    with pytest.raises(GiftHubException):
        await PricingService.get_authoritative_price(db_session, "gift", 1, item_title="off")


async def test_gift_id_not_lowercased_or_stripped(db_session):
    db_session.add(TelegramGift(id="AbC 123", star_count=15))
    await db_session.commit()

    price = await PricingService.get_authoritative_price(db_session, "gift", 1, item_title="AbC 123")
    assert price["total_price_decimal"] > 0

    for variant in ["abc 123", "abc123", "AbC 123 ", " AbC 123"]:
        with pytest.raises(GiftHubException):
            await PricingService.get_authoritative_price(db_session, "gift", 1, item_title=variant)
