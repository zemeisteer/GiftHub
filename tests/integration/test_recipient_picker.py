"""Recipient picker: the Mini App asks the bot for a native "choose a user" button, Telegram
shows its own chooser, the bot receives the users_shared message and the Mini App reads the
chosen user back. Only the person who asked can read the answer."""

import types
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.handlers.users.recipient_picker import is_picker_message, on_picker_users_shared
from app.services import recipient_picker
from app.web.server import app
from tests.conftest import make_telegram_init_data

USER_A = 7200001
USER_B = 7200002


class FakeBot:
    def __init__(self):
        self.saved = []
        self.fail = False

    async def save_prepared_keyboard_button(self, user_id, button):
        if self.fail:
            raise RuntimeError("telegram is down")
        self.saved.append((user_id, button))
        return types.SimpleNamespace(id=f"prep-{len(self.saved)}")


def _hdr(uid: int) -> dict:
    return {"X-Telegram-Init-Data": make_telegram_init_data(settings.BOT_TOKEN, uid)}


@pytest_asyncio.fixture
async def bot(monkeypatch):
    fake = FakeBot()
    monkeypatch.setattr("app.web.state.bot_instance", fake)
    return fake


@pytest_asyncio.fixture
async def client(db_session, monkeypatch, bot):
    # Behave like production: no dev/test fallback identity without valid initData.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.web.auth.AsyncSessionLocal", session_factory)
    recipient_picker.reset_memory_store()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    recipient_picker.reset_memory_store()


def _shared(user_id=555000111, first_name="Dost", last_name=None, username="dost_bek"):
    return types.SimpleNamespace(user_id=user_id, first_name=first_name, last_name=last_name, username=username)


def _message(from_id, request_id, users):
    return types.SimpleNamespace(
        from_user=types.SimpleNamespace(id=from_id),
        users_shared=types.SimpleNamespace(request_id=request_id, users=users),
        delete=AsyncMock(),
    )


async def _create(client, uid=USER_A):
    r = await client.post("/api/recipients/picker", headers=_hdr(uid), json={})
    assert r.status_code == 200, r.text
    return r.json()


async def test_unauthenticated_requests_are_rejected(client):
    assert (await client.post("/api/recipients/picker", json={})).status_code == 401
    assert (await client.get("/api/recipients/picker/1000000001")).status_code == 401


async def test_create_prepares_a_user_chooser_button_for_the_caller(client, bot):
    body = await _create(client)
    assert recipient_picker.PICK_REQUEST_MIN <= body["request_id"] <= recipient_picker.PICK_REQUEST_MAX
    assert body["prepared_id"] == "prep-1"
    user_id, button = bot.saved[0]
    assert user_id == USER_A, "the button must be usable only by the user who asked"
    req = button.request_users
    assert req.request_id == body["request_id"]
    assert req.max_quantity == 1
    assert req.user_is_bot is False
    assert req.request_username is True
    assert req.request_name is True


async def test_answer_is_pending_until_the_bot_receives_the_selection(client):
    rid = (await _create(client))["request_id"]
    r = await client.get(f"/api/recipients/picker/{rid}", headers=_hdr(USER_A))
    assert r.status_code == 200
    assert r.json() == {"status": "pending"}


async def test_bot_handler_stores_the_selection_and_the_app_reads_it(client):
    rid = (await _create(client))["request_id"]
    msg = _message(USER_A, rid, [_shared()])
    await on_picker_users_shared(msg)
    r = await client.get(f"/api/recipients/picker/{rid}", headers=_hdr(USER_A))
    assert r.json() == {
        "status": "done",
        "recipient": {"id": 555000111, "username": "dost_bek", "name": "Dost", "value": "@dost_bek"},
    }
    msg.delete.assert_awaited()  # the service message is removed from the chat


async def test_user_without_username_is_returned_by_numeric_id(client):
    rid = (await _create(client))["request_id"]
    await on_picker_users_shared(_message(USER_A, rid, [_shared(username=None, last_name="Valiyev")]))
    rec = (await client.get(f"/api/recipients/picker/{rid}", headers=_hdr(USER_A))).json()["recipient"]
    assert rec["username"] is None
    assert rec["value"] == "555000111"
    assert rec["name"] == "Dost Valiyev"


@pytest.mark.parametrize("bad", ["<b>x</b>", "ab", "1abcdef", "has space", "a" * 40])
async def test_malformed_username_is_never_passed_on(client, bad):
    rid = (await _create(client))["request_id"]
    await on_picker_users_shared(_message(USER_A, rid, [_shared(username=bad)]))
    rec = (await client.get(f"/api/recipients/picker/{rid}", headers=_hdr(USER_A))).json()["recipient"]
    assert rec["username"] is None
    assert rec["value"] == "555000111"


async def test_another_user_cannot_read_or_fill_someone_elses_request(client):
    rid = (await _create(client, USER_A))["request_id"]
    # B cannot read A's request ...
    assert (await client.get(f"/api/recipients/picker/{rid}", headers=_hdr(USER_B))).status_code == 404
    # ... and a users_shared message from B for A's request id is ignored.
    await on_picker_users_shared(_message(USER_B, rid, [_shared()]))
    assert (await client.get(f"/api/recipients/picker/{rid}", headers=_hdr(USER_A))).json() == {"status": "pending"}


async def test_unknown_request_ids_are_ignored_and_not_readable(client):
    await on_picker_users_shared(_message(USER_A, 1_500_000_000, [_shared()]))
    assert (await client.get("/api/recipients/picker/1500000000", headers=_hdr(USER_A))).status_code == 404


def test_only_picker_request_ids_are_handled_by_the_new_handler():
    assert is_picker_message(_message(1, recipient_picker.PICK_REQUEST_MIN, []))
    assert not is_picker_message(_message(1, 1, []))  # the old in-bot chooser uses small ids
    assert not is_picker_message(types.SimpleNamespace(users_shared=None))


async def test_rapid_repeat_requests_are_throttled(client, bot):
    await _create(client)
    r = await client.post("/api/recipients/picker", headers=_hdr(USER_A), json={})
    assert r.status_code == 429
    assert len(bot.saved) == 1
    # A different user is not affected.
    await _create(client, USER_B)


async def test_telegram_failure_is_reported_without_leaving_a_request(client, bot):
    bot.fail = True
    r = await client.post("/api/recipients/picker", headers=_hdr(USER_A), json={})
    assert r.status_code == 502
    assert "telegram is down" not in r.text, "internal error details must not leak"


async def test_missing_bot_gives_service_unavailable(client, monkeypatch):
    monkeypatch.setattr("app.web.state.bot_instance", None)
    r = await client.post("/api/recipients/picker", headers=_hdr(USER_A), json={})
    assert r.status_code == 503
