import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GiftHubException
from app.models.user import User

# Telegram user ids can reach 2**52 (16 digits), so allow up to 16.
_NUMERIC_ID = re.compile(r"^\d{5,16}$")
_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

UNKNOWN_RECIPIENT = (
    "Bu odam botdan foydalanmagan. «Chatdan tanlash» tugmasi bilan tanlang yoki uning raqamli ID sini yozing."
)
INVALID_RECIPIENT = "Qabul qiluvchi noto'g'ri kiritilgan. @username yoki raqamli ID kiriting."


async def resolve_gift_recipient(session: AsyncSession, buyer_id: int, recipient: str | None) -> int:
    """Resolve the Telegram user id that will receive a gift.

    Empty -> the buyer; digits -> that id; ``@name``/``name`` -> the buyer if it is their own
    username, else the id of a known bot user with that username (case-insensitive).
    """
    value = (recipient or "").strip()
    if not value:
        return buyer_id

    if _NUMERIC_ID.match(value):
        return int(value)

    name = value[1:] if value.startswith("@") else value
    if not _USERNAME.match(name):
        raise GiftHubException(INVALID_RECIPIENT)

    lowered = name.lower()
    buyer = await session.get(User, buyer_id)
    if buyer is not None and (buyer.username or "").lower() == lowered:
        return buyer_id

    found = (await session.execute(select(User.id).where(func.lower(User.username) == lowered))).scalars().first()
    if found is None:
        raise GiftHubException(UNKNOWN_RECIPIENT)
    return int(found)
