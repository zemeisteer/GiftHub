import logging
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from data import config
from database import queries

logger = logging.getLogger(__name__)

async def verify_user_subscriptions(
    bot: Bot | None,
    user_id: int,
    session: AsyncSession
) -> tuple[bool, list[Any]]:
    """
    Checks if a user is subscribed to all mandatory channels.
    Returns (all_passed: bool, missing_channels: list).
    """
    # Admins bypass subscription gate
    if str(user_id) in config.ADMINS:
        return True, []

    user = await queries.get_user_by_id(session, user_id)
    if user and user.role and user.role != "user":
        return True, []

    channels = await queries.list_channels(session, active_only=True)
    missing_channels = []

    for ch in channels:
        # Ignore auto-detected channels waiting for admin confirmation
        if ch.is_detected:
            continue

        is_member = False
        req_type = getattr(ch, "req_type", "ordinary")

        if req_type == "external":
            # External link: cannot be checked via Telegram API
            is_member = True

        elif req_type == "join_request":
            # 1. Check if recorded in user_join_requests table
            if ch.chat_id:
                has_req = await queries.has_user_join_request(session, user_id, ch.chat_id)
                if has_req:
                    is_member = True

            # 2. If not recorded in table, check if already joined the chat
            if not is_member and bot and ch.chat_id:
                try:
                    cm = await bot.get_chat_member(chat_id=ch.chat_id, user_id=user_id)
                    if cm.status in ["creator", "administrator", "member", "restricted"]:
                        is_member = True
                except Exception:
                    is_member = False

        else: # ordinary / group
            # Target chat ID or username
            chat_target = ch.chat_id
            if not chat_target and ch.username_or_link:
                val = ch.username_or_link.strip()
                if val.startswith("@"):
                    chat_target = val
                elif "t.me/" in val:
                    part = val.rstrip("/").split("/")[-1]
                    if not part.startswith("+"):
                        chat_target = f"@{part}"

            if bot and chat_target:
                try:
                    cm = await bot.get_chat_member(chat_id=chat_target, user_id=user_id)
                    if cm.status in ["creator", "administrator", "member", "restricted"]:
                        is_member = True
                    else:
                        is_member = False
                except Exception:
                    # User is not a member or bot has no permission
                    is_member = False
            else:
                is_member = True

        if not is_member:
            missing_channels.append(ch)

    all_passed = len(missing_channels) == 0
    return all_passed, missing_channels
