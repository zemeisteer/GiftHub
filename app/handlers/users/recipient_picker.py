"""Receives the user chosen in Telegram's native chooser opened from the Web App."""

import logging

from aiogram import Router
from aiogram.types import Message

from app.services import recipient_picker

router = Router()
logger = logging.getLogger(__name__)


def is_picker_message(message: Message) -> bool:
    shared = getattr(message, "users_shared", None)
    return bool(shared) and recipient_picker.PICK_REQUEST_MIN <= shared.request_id <= recipient_picker.PICK_REQUEST_MAX


@router.message(is_picker_message)
async def on_picker_users_shared(message: Message) -> None:
    shared = message.users_shared
    if not shared.users:
        return
    # Keyed by the sender, so one user can never answer another user's request.
    saved = await recipient_picker.save_pick(message.from_user.id, shared.request_id, shared.users[0])
    if not saved:
        logger.info("users_shared for an unknown or expired picker request was ignored")
        return
    try:
        await message.delete()  # keep the chat clean; the Web App already shows the choice
    except Exception as e:
        logger.debug(f"Could not delete the users_shared service message: {e}")
