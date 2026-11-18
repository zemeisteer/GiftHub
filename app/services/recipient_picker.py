"""Native "choose a user" flow for the Web App.

The Mini App cannot read Telegram's contact list itself. Instead:
1. the app asks the server to prepare a keyboard button (Bot API `savePreparedKeyboardButton`)
   that only the asking user can use;
2. the app opens Telegram's own chooser with `Telegram.WebApp.requestChat(prepared_id)`;
3. Telegram sends the bot a `users_shared` service message with the chosen user;
4. the app reads the answer back from here.

Pending requests and answers live in Redis when it is reachable (the bot and the API may be
separate processes) and in this process otherwise.
"""

import json
import re
import secrets
import time
from typing import Any

from aiogram.types import KeyboardButton, KeyboardButtonRequestUsers

from app.core.logging import get_logger
from app.core.redis import get_redis_client

logger = get_logger(__name__)

# The old in-bot chooser uses small request ids; ours live in a separate range so the handlers never clash.
PICK_REQUEST_MIN = 1_000_000_000
PICK_REQUEST_MAX = 2_000_000_000
PICK_TTL_SECONDS = 600
PICK_COOLDOWN_SECONDS = 2
BUTTON_TEXT = "👤 Do'stni tanlash"

# Same rule as the Web App: a Telegram username starts with a letter and has 5-32 characters.
USERNAME_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

_memory: dict[str, tuple[float, str]] = {}


class PickerCooldown(Exception):
    """The same user asked for a chooser again too quickly."""


def reset_memory_store() -> None:
    _memory.clear()


def _key(user_id: int, request_id: int) -> str:
    return f"gifthub:picker:{user_id}:{request_id}"


def _purge(now: float) -> None:
    for k in [k for k, (exp, _) in _memory.items() if exp <= now]:
        _memory.pop(k, None)


async def _kv_set(key: str, value: str, ttl: int, nx: bool = False) -> bool:
    redis = get_redis_client()
    if redis is not None:
        try:
            return bool(await redis.set(key, value, ex=ttl, nx=nx))
        except Exception as e:
            logger.warning(f"Recipient picker: Redis write failed, using process memory ({e})")
    now = time.monotonic()
    _purge(now)
    if nx and key in _memory:
        return False
    _memory[key] = (now + ttl, value)
    return True


async def _kv_get(key: str) -> str | None:
    redis = get_redis_client()
    if redis is not None:
        try:
            return await redis.get(key)
        except Exception as e:
            logger.warning(f"Recipient picker: Redis read failed, using process memory ({e})")
    now = time.monotonic()
    _purge(now)
    item = _memory.get(key)
    return item[1] if item else None


async def create_request(bot: Any, user_id: int) -> dict[str, Any]:
    """Prepares a user-chooser button for `user_id`. Raises PickerCooldown when asked too fast."""
    if not await _kv_set(f"gifthub:picker:cooldown:{user_id}", "1", PICK_COOLDOWN_SECONDS, nx=True):
        raise PickerCooldown()
    request_id = PICK_REQUEST_MIN + secrets.randbelow(PICK_REQUEST_MAX - PICK_REQUEST_MIN + 1)
    button = KeyboardButton(
        text=BUTTON_TEXT,
        request_users=KeyboardButtonRequestUsers(
            request_id=request_id,
            user_is_bot=False,
            max_quantity=1,
            request_name=True,
            request_username=True,
        ),
    )
    prepared = await bot.save_prepared_keyboard_button(user_id=user_id, button=button)
    await _kv_set(_key(user_id, request_id), json.dumps({"status": "pending"}), PICK_TTL_SECONDS)
    return {"request_id": request_id, "prepared_id": prepared.id}


async def save_pick(user_id: int, request_id: int, shared: Any) -> bool:
    """Stores the chosen user for a request this user created. Unknown or expired requests are ignored."""
    key = _key(user_id, request_id)
    if await _kv_get(key) is None:
        return False
    username = str(getattr(shared, "username", None) or "").lstrip("@")
    username = username if USERNAME_RX.match(username) else None
    name = " ".join(p for p in (getattr(shared, "first_name", None), getattr(shared, "last_name", None)) if p)[:100]
    uid = int(shared.user_id)
    recipient = {"id": uid, "username": username, "name": name, "value": f"@{username}" if username else str(uid)}
    await _kv_set(key, json.dumps({"status": "done", "recipient": recipient}), PICK_TTL_SECONDS)
    return True


async def get_pick(user_id: int, request_id: int) -> dict[str, Any] | None:
    raw = await _kv_get(_key(user_id, request_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
