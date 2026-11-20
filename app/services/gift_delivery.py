"""Guarded delivery of real Telegram gifts (``sendGift``).

The single double-send guard is the compare-and-set UPDATE in :func:`_claim`: ``send_gift`` is only
called after that UPDATE changed exactly one row (pending -> processing) and was committed. Every
later step either finishes the order, refunds it (definite Telegram rejection) or parks it in
``manual_review`` (unknown outcome). Nothing after a won claim ever puts the order back to
``pending``, so no retry path can send the same gift twice.
"""

import asyncio
import html
import re
from datetime import datetime, timedelta
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.gift import TelegramGift
from app.models.order import Order, OrderStatus
from app.utils.notifications import notify_admins_text

logger = get_logger(__name__)

SEND_RETRY_MAX = 2
RETRY_AFTER_MAX_SECONDS = 30
STALE_PROCESSING_MINUTES = 5

_BALANCE_ERROR = re.compile(r"balance|not enough", re.IGNORECASE)


def _result(outcome: str, order_id: int, **extra: Any) -> dict[str, Any]:
    # success is always True so the outbox never re-dispatches; outcome carries the real result.
    return {
        "success": True,
        "handled": True,
        "fulfilled": outcome == "sent",
        "outcome": outcome,
        "order_id": order_id,
        **extra,
    }


async def _tell(bot, chat_id: int | None, text: str) -> None:
    """Message one user; never raises."""
    if not bot or not chat_id:
        return
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:  # noqa: BLE001 - notifications must never break delivery
        logger.warning(f"[GiftDelivery] Xabar yuborilmadi ({chat_id}): {e}")


async def _alert_admins(bot, text: str) -> None:
    try:
        await notify_admins_text(bot, text)
    except Exception as e:  # noqa: BLE001 - notify_admins_text already swallows; belt and braces
        logger.warning(f"[GiftDelivery] Adminlarga xabar yuborilmadi: {e}")


async def _safe_rollback(session: AsyncSession) -> None:
    try:
        await session.rollback()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[GiftDelivery] Rollback xatosi: {e}")


async def _claim(session: AsyncSession, order_id: int) -> bool:
    """Atomically move a paid, pending gift order to processing. True only for the single winner.

    A database error here propagates: nothing has been claimed or sent, so retrying is safe.
    """
    stmt = (
        update(Order)
        .where(
            Order.id == order_id,
            Order.fulfillment_status == "pending",
            Order.product_type == "gift",
            Order.status == OrderStatus.PAID.value,
        )
        .values(
            fulfillment_status="processing",
            processing_at=utc_now(),  # lets sweep_stale_processing find it even if we die right after commit
            fulfillment_attempts=Order.fulfillment_attempts + 1,
        )
        .execution_options(synchronize_session=False)
    )
    res = await session.execute(stmt)
    won = res.rowcount == 1
    # Commit either way (no-op when nothing matched): a rollback would expire the caller's loaded objects.
    await session.commit()
    return won


async def _mark_manual_review(session: AsyncSession, order_id: int, error: str) -> None:
    """Park a claimed order for a human; order status is left as is (PROCESSING). Never raises.

    Only an order still in ``processing`` is touched, so a fulfilled/refunded order is never downgraded.
    If this write fails the order stays ``processing`` and the stale sweep parks it later.
    """
    try:
        await session.execute(
            update(Order)
            .where(Order.id == order_id, Order.fulfillment_status == "processing")
            .values(fulfillment_status="manual_review", fulfillment_error=error[:500])
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[GiftDelivery] manual_review saqlanmadi (order={order_id}): {e}", exc_info=True)
        await _safe_rollback(session)


async def _to_manual_review(session: AsyncSession, bot, order_id: int, order_code: str, error: str) -> dict:
    logger.error(f"[GiftDelivery] order={order_code} manual_review: {error}")
    await _mark_manual_review(session, order_id, error)
    await _alert_admins(
        bot,
        "⚠️ <b>Sovg'a: qo'lda tekshirish kerak</b>\n\n"
        f"🧾 Buyurtma: <code>{html.escape(order_code)}</code>\n"
        f"❗ Sabab: {html.escape(error[:500])}\n\n"
        "Sovg'a yuborilgan-yuborilmaganini botning sovg'alar tarixidan tekshiring, so'ng "
        '"bajarildi" deb belgilang yoki pulni qaytaring. Avtomatik qayta yuborilmaydi.',
    )
    return _result("manual_review", order_id, error=error[:500])


def _buyer_reason(exc: Exception, error: str) -> str:
    if _BALANCE_ERROR.search(error):
        return "Sovg'ani hozir yuborib bo'lmadi (texnik sabab)."
    if isinstance(exc, TelegramForbiddenError):
        return "Qabul qiluvchiga sovg'a yuborib bo'lmadi (sovg'a qabul qilmaydi yoki cheklov qo'ygan)."
    return "Telegram sovg'ani qabul qilmadi (sovg'a tugagan yoki qabul qiluvchi sovg'a qabul qilmaydi)."


async def _notify_refunded(bot, buyer_id: int, code: str, total, exc: Exception, error: str) -> None:
    amount = f"{float(total):,.0f}".replace(",", " ")
    await _tell(
        bot,
        buyer_id,
        "❌ <b>Sovg'a yuborilmadi</b>\n\n"
        f"🧾 Buyurtma: <code>{html.escape(code)}</code>\n"
        f"❗ Sabab: {_buyer_reason(exc, error)}\n"
        f"💸 Hamyoningizga qaytarildi: +{amount} so'm",
    )
    if _BALANCE_ERROR.search(error):
        await _alert_admins(
            bot,
            "🚨 <b>Botning Stars balansi yetmadi</b>\n\n"
            f"🧾 Buyurtma: <code>{html.escape(code)}</code> (pul qaytarildi)\n"
            f"Telegram: {html.escape(error)}\n\n"
            "Botning Stars balansini to'ldiring.",
        )
    else:
        await _alert_admins(
            bot,
            "⚠️ <b>Sovg'a yuborilmadi, pul qaytarildi</b>\n\n"
            f"🧾 Buyurtma: <code>{html.escape(code)}</code>\n"
            f"Telegram: {html.escape(error)}",
        )


async def _refund(session: AsyncSession, bot, order_id: int, order_code: str, exc: Exception) -> dict:
    from app.services.orders.service import order_service  # local import: avoid circular import

    error = str(exc)[:500]
    logger.warning(f"[GiftDelivery] order={order_code} Telegram rad etdi, qaytariladi: {error}")
    try:
        order = await session.get(Order, order_id, populate_existing=True)
        order.fulfillment_status = "failed"
        order.fulfillment_error = error
        await session.flush()  # same transaction as the refund: committed together by refund_order
        order = await order_service.refund_order(session, order_id, reason=f"Sovg'a yuborilmadi: {error}")
    except Exception as e:  # noqa: BLE001 - refund rolled back, so the money was not returned: park it
        logger.error(f"[GiftDelivery] Qaytarish amalga oshmadi (order={order_code}): {e}", exc_info=True)
        await _safe_rollback(session)
        return await _to_manual_review(
            session, bot, order_id, order_code, f"Telegram rad etdi ({error}), lekin pul qaytarilmadi: {e}"
        )

    # The refund is committed: from here on nothing may turn this into a manual-review alert.
    # Plain locals only: a later rollback would expire ``order`` and a lazy load would raise.
    buyer_id, code, total = order.user_id, order.order_code, order.total_price
    try:
        await _notify_refunded(bot, buyer_id, code, total, exc, error)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[GiftDelivery] Qaytarish xabarlari yuborilmadi (order={code}): {e}")
    return _result("refunded", order_id, error=error)


async def _complete(session: AsyncSession, bot, order_id: int, order_code: str, gift_id: str, star_count: int) -> dict:
    from app.services import gift_catalog
    from app.services.notifications.service import notification_service
    from app.services.orders.service import order_service

    try:
        order = await order_service.transition_order_status(
            session,
            order_id,
            OrderStatus.COMPLETED.value,
            actor="SYSTEM",
            reason="Telegram sovg'asi yuborildi (sendGift)",
            payload=f"telegram_sendGift:{gift_id}",
        )
    except Exception as e:  # noqa: BLE001 - the gift IS sent; never resend, let a human record it
        logger.error(f"[GiftDelivery] Yuborildi, lekin saqlanmadi (order={order_code}): {e}", exc_info=True)
        await _safe_rollback(session)
        res = await _to_manual_review(
            session, bot, order_id, order_code, f"Sovg'a YUBORILDI, lekin holat saqlanmadi: {e}"
        )
        res["sent"] = True
        return res

    # COMPLETED is committed: from here on nothing may turn this into a manual-review alert.
    # Plain locals only: a rollback below expires ``order`` and a lazy load would raise MissingGreenlet.
    buyer_id, code = order.user_id, order.order_code
    try:
        await gift_catalog.decrement_cached_balance(session, star_count)
        await session.commit()
    except Exception as e:  # noqa: BLE001 - cache only; the next sync corrects it
        logger.warning(f"[GiftDelivery] Kesh balansi yangilanmadi: {e}")
        await _safe_rollback(session)

    try:
        await notification_service.create_notification(
            session=session,
            user_id=buyer_id,
            type_="order",
            title="Sovg'angiz yuborildi! 🎁",
            message=f"Telegram sovg'asi muvaffaqiyatli yuborildi. Buyurtma ID: {code}",
            related_entity=f"order:{code}",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[GiftDelivery] Ilova bildirishnomasi yaratilmadi: {e}")
        await _safe_rollback(session)

    try:
        await _tell(
            bot,
            buyer_id,
            "🎁 <b>Sovg'a yuborildi!</b>\n\n"
            f"🧾 Buyurtma: <code>{html.escape(code)}</code>\n"
            "✅ Telegram sovg'asi qabul qiluvchiga muvaffaqiyatli yetkazildi.",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[GiftDelivery] Xaridorga xabar yuborilmadi: {e}")
    logger.info(f"[GiftDelivery] order={order_code} yuborildi (gift={gift_id})")
    return _result("sent", order_id)


async def deliver(session: AsyncSession, order_id: int, bot) -> dict[str, Any]:
    """Send the gift of a paid gift order at most once. Always returns ``success=True``."""
    from app.services.orders.service import order_service  # local import: avoid circular import

    if not await _claim(session, order_id):
        logger.info(f"[GiftDelivery] order={order_id} o'tkazib yuborildi (pending/paid/gift emas)")
        return _result("skipped", order_id)

    # From here on the order is ours and must never be sent again by anyone.
    order_code = str(order_id)
    try:
        order = await session.get(Order, order_id, populate_existing=True)
        order_code = order.order_code
        recipient_id = order.recipient_user_id
        gift_id = order.item_title

        try:
            await order_service.transition_order_status(
                session,
                order_id,
                OrderStatus.PROCESSING.value,
                actor="SYSTEM",
                reason="Telegram sovg'asi yuborilmoqda",
            )
        except Exception as e:  # noqa: BLE001 - nothing sent yet, but do not risk it: park for a human
            await _safe_rollback(session)
            return await _to_manual_review(
                session, bot, order_id, order_code, f"PROCESSING ga o'tkazilmadi (yuborilmadi): {e}"
            )

        gift = await session.get(TelegramGift, gift_id) if gift_id else None
        if not recipient_id or gift is None:
            return await _to_manual_review(
                session,
                bot,
                order_id,
                order_code,
                "Eski uslubdagi sovg'a buyurtmasi (qabul qiluvchi ID yoki Telegram sovg'a ID yo'q), yuborilmadi",
            )
        star_count = gift.star_count

        retries = 0
        while True:
            try:
                await bot.send_gift(user_id=recipient_id, gift_id=gift_id)
                break
            except TelegramRetryAfter as e:  # flood control: Telegram did not execute the call
                wait = e.retry_after or 0
                if wait <= RETRY_AFTER_MAX_SECONDS and retries < SEND_RETRY_MAX:
                    retries += 1
                    logger.warning(f"[GiftDelivery] order={order_code} RetryAfter {wait}s ({retries})")
                    await asyncio.sleep(wait)
                    continue
                return await _to_manual_review(session, bot, order_id, order_code, f"RetryAfter: {e}"[:500])
            except (TelegramBadRequest, TelegramForbiddenError) as e:  # definite rejection: not sent
                return await _refund(session, bot, order_id, order_code, e)
            except Exception as e:  # noqa: BLE001 - network/timeout/5xx/unknown: outcome unknown
                return await _to_manual_review(
                    session, bot, order_id, order_code, f"Noma'lum natija ({type(e).__name__}): {e}"
                )

        return await _complete(session, bot, order_id, order_code, gift_id, star_count)
    except Exception as e:  # noqa: BLE001 - last line of defence after a won claim: never resend
        logger.error(f"[GiftDelivery] Kutilmagan xato (order={order_code}): {e}", exc_info=True)
        await _safe_rollback(session)
        return await _to_manual_review(session, bot, order_id, order_code, f"Kutilmagan xato: {e}")


async def sweep_stale_processing(session: AsyncSession, bot, now: datetime | None = None) -> int:
    """Park gift orders stuck in ``processing`` longer than STALE_PROCESSING_MINUTES. Returns the count."""
    cutoff = (now or utc_now()) - timedelta(minutes=STALE_PROCESSING_MINUTES)
    stale = or_(Order.processing_at < cutoff, Order.processing_at.is_(None))
    rows = (
        await session.execute(
            select(Order.id, Order.order_code).where(
                Order.product_type == "gift", Order.fulfillment_status == "processing", stale
            )
        )
    ).all()
    if not rows:
        return 0

    moved_codes: list[str] = []
    for order_id, order_code in rows:
        res = await session.execute(
            update(Order)
            .where(
                Order.id == order_id,
                Order.product_type == "gift",
                Order.fulfillment_status == "processing",
                stale,
            )
            .values(
                fulfillment_status="manual_review",
                fulfillment_error=f"{STALE_PROCESSING_MINUTES} daqiqadan ortiq processing holatida qoldi",
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 1:
            moved_codes.append(order_code)
    await session.commit()

    if moved_codes:
        codes = ", ".join(f"<code>{html.escape(c)}</code>" for c in moved_codes)
        logger.warning(f"[GiftDelivery] {len(moved_codes)} ta sovg'a buyurtmasi manual_review ga o'tdi")
        await _alert_admins(
            bot,
            "⚠️ <b>Sovg'a buyurtmalari qo'lda tekshirishga o'tdi</b>\n\n"
            f"{STALE_PROCESSING_MINUTES} daqiqadan ortiq yuborilish holatida qoldi: {codes}\n\n"
            "Botning sovg'alar tarixini tekshiring. Avtomatik qayta yuborilmaydi.",
        )
    return len(moved_codes)
