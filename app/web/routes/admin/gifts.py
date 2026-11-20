"""Admin API for the Telegram gift catalog (list, edit, sync)."""

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import GiftHubException
from app.core.logging import get_logger
from app.core.security import Permission
from app.models.gift import GiftSyncState, TelegramGift
from app.models.pricing import PricingSetting
from app.models.user import User
from app.services import gift_catalog
from app.services.pricing.service import PricingService
from app.web.auth import require_permission
from app.web.state import get_bot
from database import queries

logger = get_logger(__name__)

router = APIRouter()

LOW_BALANCE_FLOOR = 100
MAX_OVERRIDE_UZS = 1_000_000_000
CENT = Decimal("0.01")


class GiftPatch(BaseModel):
    """Absent field = leave as is; explicit null on title/price_override_uzs = clear."""

    enabled: bool | None = None
    title: str | None = Field(default=None, max_length=64)
    price_override_uzs: float | None = Field(default=None, ge=0, le=MAX_OVERRIDE_UZS, allow_inf_nan=False)


def _serialize(gift: TelegramGift, pricing: PricingSetting | None) -> dict:
    price = PricingService.get_gift_price(gift, pricing)
    return {
        "id": str(gift.id),
        "emoji": gift.emoji,
        "title": gift.title,
        "name": gift.title or f"{gift.star_count} ⭐ sovg'a",
        "star_count": gift.star_count,
        "price_uzs": float(price["total_price_decimal"]),
        "cost_uzs": float(price["cost_total_decimal"]),
        "price_override_uzs": float(gift.price_override_uzs) if gift.price_override_uzs is not None else None,
        "enabled": gift.enabled,
        "available": gift.available,
        "is_limited": gift.is_limited,
        "remaining_count": gift.remaining_count,
        "is_premium": gift.is_premium,
        "synced_at": gift.synced_at.isoformat() if gift.synced_at else None,
    }


def _pure_cost(gift: TelegramGift, pricing: PricingSetting | None) -> Decimal:
    """Cost of the gift ignoring any admin override."""
    bare = TelegramGift(id=gift.id, star_count=gift.star_count, title=None, price_override_uzs=None)
    return PricingService.get_gift_price(bare, pricing)["cost_total_decimal"]


@router.get("/api/admin/gifts")
async def admin_list_gifts(
    admin: User = Depends(require_permission(Permission.PRICING_READ)),
    session: AsyncSession = Depends(get_db),
):
    pricing = await session.get(PricingSetting, 1)
    rows = (
        (await session.execute(select(TelegramGift).order_by(TelegramGift.star_count, TelegramGift.id))).scalars().all()
    )
    state = await session.get(GiftSyncState, 1)
    balance = state.bot_star_balance if state else None

    low_balance = False
    if balance is not None:
        sellable = [g.star_count for g in rows if g.enabled and g.available]
        cheapest = min(sellable) if sellable else None
        low_balance = balance < LOW_BALANCE_FLOOR or (cheapest is not None and balance < cheapest)

    return {
        "gifts": [_serialize(g, pricing) for g in rows],
        "bot_star_balance": balance,
        "reserved_stars": await gift_catalog.reserved_stars(session),
        "last_sync_at": state.last_sync_at.isoformat() if state and state.last_sync_at else None,
        "last_sync_error": state.last_sync_error if state else None,
        "low_balance": low_balance,
    }


@router.post("/api/admin/gifts/sync")
async def admin_sync_gifts(
    admin: User = Depends(require_permission(Permission.PRICING_UPDATE)),
    session: AsyncSession = Depends(get_db),
):
    bot = get_bot()
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot ishga tushmagan, sovg'alarni yangilab bo'lmadi.")
    try:
        result = await gift_catalog.sync(session, bot)
    except GiftHubException as exc:
        # gift_catalog already logged the real cause; only its safe Uzbek text goes to the client
        raise HTTPException(status_code=502, detail=exc.message)
    await queries.log_admin_action(
        session=session,
        admin_id=admin.id,
        admin_username=admin.username,
        action="Sovg'alar katalogini yangiladi",
        entity_type="gift",
        details=(
            f"Qo'shildi: {result['added']}, yangilandi: {result['updated']}, sotuvdan chiqdi: {result['unavailable']}"
        ),
    )
    return {"success": True, **result}


@router.patch("/api/admin/gifts/{gift_id}")
async def admin_patch_gift(
    gift_id: str,
    req: GiftPatch,
    admin: User = Depends(require_permission(Permission.PRICING_UPDATE)),
    session: AsyncSession = Depends(get_db),
):
    gift = await session.get(TelegramGift, gift_id)
    if gift is None:
        raise HTTPException(status_code=404, detail="Sovg'a topilmadi")
    pricing = await session.get(PricingSetting, 1)
    sent = req.model_fields_set

    changes: list[str] = []
    new_override = gift.price_override_uzs
    if "price_override_uzs" in sent:
        if req.price_override_uzs is None:
            new_override = None
        else:
            new_override = Decimal(str(req.price_override_uzs)).quantize(CENT, rounding=ROUND_HALF_UP)
            cost = _pure_cost(gift, pricing)
            if new_override < cost:
                raise HTTPException(
                    status_code=400,
                    detail=f"Narx tannarxdan past bo'lishi mumkin emas (tannarx: {int(cost)} so'm).",
                )
        changes.append(f"narx: {gift.price_override_uzs} -> {new_override}")

    if "enabled" in sent and req.enabled is not None:
        changes.append(f"yoqilgan: {gift.enabled} -> {req.enabled}")
        gift.enabled = req.enabled
    if "title" in sent:
        new_title = (req.title or "").strip() or None
        changes.append(f"nom: {gift.title!r} -> {new_title!r}")
        gift.title = new_title
    if "price_override_uzs" in sent:
        gift.price_override_uzs = new_override

    await session.flush()
    # log_admin_action commits: the change and its audit entry land atomically
    await queries.log_admin_action(
        session=session,
        admin_id=admin.id,
        admin_username=admin.username,
        action="Sovg'ani yangiladi",
        entity_type="gift",
        entity_id=gift.id,
        details="; ".join(changes) or "o'zgarish yo'q",
    )
    return _serialize(gift, pricing)
