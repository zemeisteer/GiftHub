"""Bot shop sells real gifts from the catalog (no gifts_json, no hard-coded fallback list)."""

import asyncio
import types
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.handlers.users import shop
from app.models.gift import GiftSyncState, TelegramGift
from app.models.order import Order
from app.models.outbox import OutboxEvent
from app.services import gift_catalog

BUYER_ID = 12345678  # sample_user
GIFT_ID = "5170145012310081615"  # real gift ids are 19-digit strings


@pytest.fixture
def factory(db_session, monkeypatch):
    f = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(shop, "AsyncSessionLocal", f)
    return f


@pytest.fixture
def state():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=BUYER_ID, user_id=BUYER_ID))


def _callback(data):
    return types.SimpleNamespace(
        data=data,
        from_user=types.SimpleNamespace(id=BUYER_ID, username="testbuyer"),
        message=types.SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
        bot=object(),
    )


def _buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


async def _seed(db_session, balance_stars=1000):
    db_session.add(TelegramGift(id=GIFT_ID, star_count=15, title="Ayiqcha", emoji="🧸"))
    db_session.add(TelegramGift(id="999", star_count=25, title="Yashirin", emoji="🎩", enabled=False))
    db_session.add(GiftSyncState(id=1, bot_star_balance=balance_stars))
    await db_session.commit()


async def _selected_state(state, recipient="testbuyer", total=500000):
    await state.update_data(
        product_type="gift",
        gift_id=GIFT_ID,
        item_title="🧸 Ayiqcha",
        amount=1,
        total_price=total,
        cost_price=0,
        recipient=recipient,
    )


async def test_gifts_menu_uses_catalog_and_hides_unorderable(db_session, factory, state):
    await _seed(db_session)
    cb = _callback("shop:gifts")
    await shop.cb_shop_gifts(cb, state)

    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    texts = [b.text for b in _buttons(markup)]
    assert any("Ayiqcha" in t for t in texts)
    assert not any("Yashirin" in t for t in texts)
    assert not any("Teddy Bear" in t or "Neon Heart" in t for t in texts)
    pkg = [b.callback_data for b in _buttons(markup) if b.callback_data.startswith("gift:pkg:")]
    assert pkg == [f"gift:pkg:{GIFT_ID}"]
    assert all(len(c.encode()) <= 64 for c in pkg)


async def test_gifts_menu_empty_catalog_shows_no_fallback_list(db_session, factory, state):
    cb = _callback("shop:gifts")
    await shop.cb_shop_gifts(cb, state)
    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    assert [b.callback_data for b in _buttons(markup) if b.callback_data.startswith("gift:pkg:")] == []


async def test_gift_package_selection_stores_gift_id_and_server_price(db_session, factory, state):
    await _seed(db_session)
    expected = (await gift_catalog.list_public(db_session))[0]["price_uzs"]
    cb = _callback(f"gift:pkg:{GIFT_ID}")
    await shop.cb_gift_package(cb, state)

    data = await state.get_data()
    assert data["product_type"] == "gift"
    assert data["gift_id"] == GIFT_ID and isinstance(data["gift_id"], str)
    assert data["total_price"] == pytest.approx(expected)
    assert "Ayiqcha" in data["item_title"]


async def test_gift_package_unorderable_gift_is_refused(db_session, factory, state):
    await _seed(db_session)
    cb = _callback("gift:pkg:999")  # disabled gift
    await shop.cb_gift_package(cb, state)
    cb.answer.assert_awaited()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
    assert "gift_id" not in await state.get_data()


async def test_gift_purchase_uses_order_service_and_surfaces_error(db_session, sample_user, factory, state):
    await _seed(db_session, balance_stars=1)  # bot cannot afford 15 stars -> create_order raises
    await _selected_state(state, total=1000)
    before = sample_user.balance
    cb = _callback("buy:confirm:gift:1")
    await shop.cb_execute_purchase(cb, state)

    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
    assert "yuborib bo'lmaydi" in cb.answer.await_args.args[0]
    await db_session.refresh(sample_user)
    assert sample_user.balance == before
    assert (await db_session.execute(select(func.count()).select_from(Order))).scalar_one() == 0


async def test_gift_purchase_creates_gift_order_with_catalog_price(db_session, sample_user, factory, state):
    await _seed(db_session)
    price = Decimal(str((await gift_catalog.list_public(db_session))[0]["price_uzs"]))
    await _selected_state(state, total=1)  # stale/tampered FSM price: the server price must win
    cb = _callback("buy:confirm:gift:1")
    await shop.cb_execute_purchase(cb, state)

    order = (await db_session.execute(select(Order))).scalars().one()
    assert order.product_type == "gift"
    assert order.item_title == GIFT_ID
    assert order.recipient_user_id == BUYER_ID
    assert Decimal(order.total_price) == price
    await db_session.refresh(sample_user)
    assert sample_user.balance == Decimal("150000.00") - price
    text = cb.message.edit_text.await_args.args[0]
    assert "Ayiqcha" in text and "Stars / Premium" not in text
    assert len((await db_session.execute(select(OutboxEvent))).scalars().all()) == 1


async def test_gift_purchase_does_not_start_fragment_task(db_session, sample_user, factory, state, monkeypatch):
    await _seed(db_session)
    from app.services.fragment import fragment_client

    spy = AsyncMock()
    monkeypatch.setattr(fragment_client, "fulfill_order", spy)
    await _selected_state(state)
    cb = _callback("buy:confirm:gift:1")
    await shop.cb_execute_purchase(cb, state)
    await asyncio.sleep(0)
    spy.assert_not_called()
    assert (await db_session.execute(select(func.count()).select_from(Order))).scalar_one() == 1


async def test_picker_recipient_id_wins_over_unknown_username(db_session, sample_user, factory, state):
    await _seed(db_session)
    await _selected_state(state, recipient="never_started_bot")
    await state.update_data(recipient_id=555000999, recipient_name="Dost")
    cb = _callback("buy:confirm:gift:1")
    await shop.cb_execute_purchase(cb, state)

    order = (await db_session.execute(select(Order))).scalars().one()
    assert order.recipient_user_id == 555000999


async def test_manually_typed_numeric_id_recipient_works(db_session, sample_user, factory, state):
    await _seed(db_session)
    await _selected_state(state, recipient="777000111")
    await state.update_data(recipient_id=None)
    cb = _callback("buy:confirm:gift:1")
    await shop.cb_execute_purchase(cb, state)

    order = (await db_session.execute(select(Order))).scalars().one()
    assert order.recipient_user_id == 777000111


async def test_unknown_username_without_recipient_id_still_errors(db_session, sample_user, factory, state):
    await _seed(db_session)
    await _selected_state(state, recipient="nobody_here")
    await state.update_data(recipient_id=None)
    before = sample_user.balance
    cb = _callback("buy:confirm:gift:1")
    await shop.cb_execute_purchase(cb, state)

    assert cb.answer.await_args.kwargs.get("show_alert") is True
    assert "botdan foydalanmagan" in cb.answer.await_args.args[0]
    await db_session.refresh(sample_user)
    assert sample_user.balance == before
    assert (await db_session.execute(select(func.count()).select_from(Order))).scalar_one() == 0


async def test_double_confirmation_creates_one_order_and_one_debit(db_session, sample_user, factory, state):
    await _seed(db_session)
    price = Decimal(str((await gift_catalog.list_public(db_session))[0]["price_uzs"]))
    await shop.cb_gift_package(_callback(f"gift:pkg:{GIFT_ID}"), state)
    await state.update_data(recipient="testbuyer")
    snapshot = await state.get_data()  # a double tap reads the same FSM data before the first one clears it

    await shop.cb_execute_purchase(_callback("buy:confirm:gift:1"), state)
    await state.set_data(snapshot)
    await shop.cb_execute_purchase(_callback("buy:confirm:gift:1"), state)

    assert (await db_session.execute(select(func.count()).select_from(Order))).scalar_one() == 1
    await db_session.refresh(sample_user)
    assert sample_user.balance == Decimal("150000.00") - price
