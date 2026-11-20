"""Background maintenance and admin guards for Telegram gift orders."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_scope
from app.core.logging import get_logger
from app.models.order import Order
from app.services import gift_catalog, gift_delivery

logger = get_logger(__name__)

SWEEP_EVERY_CYCLES = 150  # ~5 minutes
SYNC_EVERY_CYCLES = 1800  # ~1 hour

GIFT_IN_PROGRESS_MESSAGE = (
    "Sovg'a yetkazilmoqda (Telegramga yuborilmoqda). Bir necha daqiqadan so'ng qayta urinib ko'ring."
)
GIFT_RETRY_BLOCKED_MESSAGE = (
    "Sovg'a buyurtmasini qayta yuborib bo'lmaydi: avval botning sovg'alar tarixini Telegramda tekshiring, "
    "so'ng buyurtmani qo'lda «bajarildi» deb belgilang yoki pulini qaytaring."
)


async def gift_order_state(session: AsyncSession, order_id: int) -> tuple[bool, str | None]:
    """Return (is_gift, fulfillment_status) for an order; (False, None) if it does not exist."""
    row = (
        await session.execute(select(Order.product_type, Order.fulfillment_status).where(Order.id == order_id))
    ).first()
    if row is None:
        return False, None
    return row[0] == "gift", row[1]


async def gift_admin_conflict(session: AsyncSession, order_id: int, *, retry: bool = False) -> str | None:
    """Uzbek 409 message if an admin action must be refused for this order, else None.

    ``retry=True`` (retry/fulfill-fragment): refused for gift orders in every state.
    Otherwise (refund/cancel/mark-fulfilled): refused only while a send may be in flight.
    """
    is_gift, fulfillment_status = await gift_order_state(session, order_id)
    if not is_gift:
        return None
    if retry:
        return GIFT_RETRY_BLOCKED_MESSAGE
    if fulfillment_status == "processing":
        return GIFT_IN_PROGRESS_MESSAGE
    return None


async def run_gift_maintenance(bot, cycle_counter: int) -> None:
    """Periodic gift jobs. Each runs in its own session; errors are logged, never raised."""
    if cycle_counter % SWEEP_EVERY_CYCLES == 0:
        try:
            async with async_session_scope() as session:
                await gift_delivery.sweep_stale_processing(session, bot)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[GiftJobs] Qotib qolgan buyurtmalarni tekshirishda xatolik: {e}", exc_info=True)
    if cycle_counter % SYNC_EVERY_CYCLES == 0:
        try:
            async with async_session_scope() as session:
                await gift_catalog.sync(session, bot)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[GiftJobs] Sovg'alar katalogini sinxronlashda xatolik: {e}", exc_info=True)


async def startup_gift_sync(bot) -> None:
    """First-start bootstrap of the gift catalog; errors are swallowed."""
    try:
        async with async_session_scope() as session:
            await gift_catalog.sync_if_empty(session, bot)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[GiftJobs] Boshlang'ich sinxronlashda xatolik: {e}", exc_info=True)
