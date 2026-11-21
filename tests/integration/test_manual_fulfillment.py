"""Stars/Premium have no real automatic delivery: they must never be marked fulfilled by a fabricated tx."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.services import fragment as fragment_module
from app.services.fulfillment.service import fulfillment_service
from app.services.orders.service import OrderService
from tests.gift_fakes import FakeGiftBot

BUYER_ID = 12345678  # sample_user
ADMIN_ID = 777000111


@pytest.fixture(autouse=True)
def _setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "ADMINS", [ADMIN_ID])
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(fragment_module, "AsyncSessionLocal", factory)


async def _paid(db_session, product_type: str, amount: int, title: str) -> Order:
    order, _, _ = await OrderService.create_order(
        db_session,
        user_id=BUYER_ID,
        product_type=product_type,
        item_title=title,
        amount=amount,
        recipient_username="friend_user",
        payment_method="balance",
    )
    return order


async def _reload(db_session, order_id) -> Order:
    return await db_session.get(Order, order_id, populate_existing=True)


@pytest.mark.parametrize("product_type,amount,title", [("stars", 100, "100 Stars"), ("premium", 3, "Premium 3 oy")])
@pytest.mark.parametrize("auto_buy", [True, False])
async def test_stars_and_premium_go_to_manual_review_never_fake_fulfilled(
    db_session, sample_user, monkeypatch, product_type, amount, title, auto_buy
):
    from database import queries

    setting = await queries.get_fragment_settings(db_session)
    setting.is_auto_buy = auto_buy
    setting.simulation_mode = False
    await db_session.commit()

    order = await _paid(db_session, product_type, amount, title)
    bot = FakeGiftBot()

    res = await fulfillment_service.fulfill_order_automated(db_session, order.id, bot=bot)

    fresh = await _reload(db_session, order.id)
    assert res["success"] is True and res.get("manual") is True
    assert fresh.fulfillment_status == "manual_review"
    assert fresh.status != OrderStatus.COMPLETED and fresh.status != OrderStatus.FAILED
    assert not fresh.fragment_tx_hash  # no fabricated transaction id
    assert fresh.completed_at is None
    assert fresh.fulfillment_attempts <= 1
    # buyer is told it was accepted, admins are asked to fulfill by hand
    assert any(m["chat_id"] == BUYER_ID and "qabul qilindi" in m["text"] for m in bot.messages)
    assert any(m["chat_id"] == ADMIN_ID and fresh.order_code in m["text"] for m in bot.messages)


async def test_simulation_mode_does_not_fabricate_success(db_session, sample_user):
    res = await fragment_module.fragment_client.send_ton_transaction(
        to_address="EQ-test", ton_amount=1.0, comment="stars:x:50", setting=_FakeSetting(simulation_mode=True)
    )
    assert res["success"] is False and res.get("manual") is True
    assert "tx_hash" not in res


async def test_live_mode_does_not_fabricate_success(db_session, sample_user):
    res = await fragment_module.fragment_client.send_ton_transaction(
        to_address="EQ-test",
        ton_amount=1.0,
        comment="stars:x:50",
        setting=_FakeSetting(simulation_mode=False, ton_wallet_mnemonic="word " * 12),
    )
    assert res["success"] is False and res.get("manual") is True
    assert "tx_hash" not in res


class _FakeSetting:
    def __init__(self, simulation_mode=False, ton_wallet_mnemonic=""):
        self.simulation_mode = simulation_mode
        self.ton_wallet_mnemonic = ton_wallet_mnemonic
