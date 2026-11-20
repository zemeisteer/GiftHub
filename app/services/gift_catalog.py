"""Telegram gift catalog: sync from the Bot API, public listing, bot Stars balance."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GiftHubException
from app.models.base import utc_now
from app.models.gift import GiftSyncState, TelegramGift
from app.models.order import Order, OrderStatus
from app.models.pricing import PricingSetting

logger = logging.getLogger(__name__)

NOT_ON_SALE = "Bu sovg'a hozir sotuvda emas."


async def _get_state(session: AsyncSession) -> GiftSyncState:
    state = await session.get(GiftSyncState, 1)
    if state is None:
        state = GiftSyncState(id=1)
        session.add(state)
        await session.flush()
    return state


async def _record_error(session: AsyncSession, message: str) -> None:
    state = await _get_state(session)
    state.last_sync_error = message[:255]
    await session.commit()


async def sync(session: AsyncSession, bot) -> dict[str, int]:
    """Mirror the Bot API gift list. Admin-edited fields are never touched.

    An API error or an empty list leaves the catalog untouched (nothing is marked
    unavailable), records ``last_sync_error`` and raises GiftHubException.
    """
    try:
        gifts = (await bot.get_available_gifts()).gifts
    except Exception as exc:
        logger.warning("Gift catalog sync failed: %s", exc)
        await _record_error(session, f"get_available_gifts: {exc}")
        raise GiftHubException("Sovg'alar ro'yxatini olib bo'lmadi.", code="GIFT_SYNC_FAILED") from exc

    if not gifts:
        await _record_error(session, "Telegram returned an empty gift list")
        raise GiftHubException("Telegram sovg'alar ro'yxatini bo'sh qaytardi.", code="GIFT_SYNC_EMPTY")

    now = utc_now()
    existing = {g.id: g for g in (await session.execute(select(TelegramGift))).scalars()}
    added = updated = 0
    seen: set[str] = set()
    for gift in gifts:
        seen.add(gift.id)
        is_limited = gift.total_count is not None
        emoji = (gift.sticker.emoji if gift.sticker else None) or "🎁"
        row = existing.get(gift.id)
        if row is None:
            session.add(
                TelegramGift(
                    id=gift.id,
                    emoji=emoji,
                    star_count=gift.star_count,
                    is_limited=is_limited,
                    remaining_count=gift.remaining_count,
                    is_premium=bool(gift.is_premium),
                    available=True,
                    synced_at=now,
                )
            )
            added += 1
        else:
            row.emoji = emoji
            row.star_count = gift.star_count
            row.is_limited = is_limited
            row.remaining_count = gift.remaining_count
            row.is_premium = bool(gift.is_premium)
            row.available = True
            row.synced_at = now
            updated += 1

    unavailable = 0
    for gift_id, row in existing.items():
        if gift_id not in seen and row.available:
            row.available = False
            unavailable += 1

    state = await _get_state(session)
    state.last_sync_at = now
    state.last_sync_error = None
    await session.commit()
    await refresh_balance(session, bot)
    return {"added": added, "updated": updated, "unavailable": unavailable}


async def refresh_balance(session: AsyncSession, bot) -> int | None:
    """Cache the bot's Stars balance. On failure keep the old value and return None."""
    try:
        balance = int((await bot.get_my_star_balance()).amount)
    except Exception as exc:
        logger.warning("Bot Stars balance refresh failed: %s", exc)
        return None
    state = await _get_state(session)
    state.bot_star_balance = balance
    state.balance_synced_at = utc_now()
    await session.commit()
    return balance


async def sync_if_empty(session: AsyncSession, bot) -> bool:
    """First-start bootstrap: sync only when the catalog table is empty."""
    count = (await session.execute(select(func.count()).select_from(TelegramGift))).scalar_one()
    if count:
        return False
    try:
        await sync(session, bot)
    except GiftHubException:
        return False
    return True


def _is_orderable(gift: TelegramGift) -> bool:
    if not gift.enabled or not gift.available or gift.is_premium:
        return False
    if gift.is_limited and (gift.remaining_count or 0) <= 0:
        return False
    return True


async def get_orderable(session: AsyncSession, gift_id: str) -> TelegramGift:
    gift = await session.get(TelegramGift, gift_id)
    if gift is None or not _is_orderable(gift):
        raise GiftHubException(NOT_ON_SALE)
    return gift


async def reserved_stars(session: AsyncSession) -> int:
    """Stars owed for paid gift orders that have not been delivered yet.

    Gift orders store the gift id in ``item_title``.
    """
    stmt = (
        select(func.coalesce(func.sum(TelegramGift.star_count), 0))
        .select_from(Order)
        .join(TelegramGift, TelegramGift.id == Order.item_title)
        .where(
            Order.product_type == "gift",
            Order.status.in_([OrderStatus.PAID.value, OrderStatus.PROCESSING.value]),
            Order.fulfillment_status.in_(["pending", "processing"]),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def spendable_stars(session: AsyncSession) -> int | None:
    state = await session.get(GiftSyncState, 1)
    if state is None or state.bot_star_balance is None:
        return None
    return state.bot_star_balance - await reserved_stars(session)


async def decrement_cached_balance(session: AsyncSession, stars: int) -> None:
    """Lower the cached balance after a successful sendGift (caller commits)."""
    state = await session.get(GiftSyncState, 1)
    if state is None or state.bot_star_balance is None:
        return
    state.bot_star_balance = max(0, state.bot_star_balance - stars)
    await session.flush()


async def list_public(session: AsyncSession) -> list[dict]:
    from app.services.pricing.service import PricingService  # local import: avoid circular import

    pricing = await session.get(PricingSetting, 1)
    rows = (await session.execute(select(TelegramGift).order_by(TelegramGift.star_count, TelegramGift.id))).scalars()
    items: list[dict] = []
    for gift in rows:
        if not _is_orderable(gift):
            continue
        price = PricingService.get_gift_price(gift, pricing)
        items.append(
            {
                "id": gift.id,
                "name": gift.title or f"{gift.star_count} ⭐ sovg'a",
                "icon": gift.emoji,
                "price_uzs": float(price["total_price_decimal"]),
                "type": "gift",
                "stars": gift.star_count,
                "remaining": gift.remaining_count if gift.is_limited else None,
            }
        )
    return items
