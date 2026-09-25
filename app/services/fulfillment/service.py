import traceback
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import OrderNotFoundError
from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.order import Order, OrderStatus
from app.services.dlq.service import dlq_service
from app.services.fragment import fragment_client
from app.services.notifications.service import notification_service
from app.services.providers.circuit_breaker import circuit_breaker

logger = get_logger(__name__)

MAX_FULFILLMENT_RETRIES = 3


class FulfillmentService:
    @classmethod
    async def fulfill_order_automated(
        cls,
        session: AsyncSession,
        order_id: int,
        bot=None
    ) -> dict[str, Any]:
        """
        Executes automated Fragment/blockchain delivery with retry limits,
        circuit breaker protection, and Dead Letter Queue (DLQ) persistent storage.
        """
        stmt = select(Order).where(Order.id == order_id).with_for_update()
        res = await session.execute(stmt)
        order = res.scalars().first()

        if not order:
            raise OrderNotFoundError(f"Buyurtma topilmadi: {order_id}")

        # DUPLICATE DELIVERY PREVENTION
        if order.fulfillment_status == "fulfilled" or order.status == OrderStatus.COMPLETED:
            logger.warning(f"[Fulfillment] Order {order.order_code} is already fulfilled. Skipping duplicate delivery.")
            return {"success": True, "already_fulfilled": True, "order_code": order.order_code}

        # CIRCUIT BREAKER CHECK
        if not circuit_breaker.can_execute("fragment"):
            logger.warning(f"[Fulfillment] Fragment provider circuit breaker is OPEN. Deferring order {order.order_code}")
            return {"success": False, "circuit_open": True, "error": "Fragment provayderi vaqtincha nofaol"}

        # RETRY LIMIT CHECK -> Route to DLQ
        if order.fulfillment_attempts >= MAX_FULFILLMENT_RETRIES:
            logger.warning(f"[Fulfillment] Order {order.order_code} exceeded max retries. Routing to DLQ.")
            order.fulfillment_status = "manual_review"
            order.status = OrderStatus.FAILED
            await session.commit()

            # Record in DLQ
            await dlq_service.record_failed_job(
                session=session,
                job_type="fulfillment",
                payload={"order_id": order.id, "order_code": order.order_code, "recipient": order.recipient_username},
                error_message=order.fulfillment_error or "Maksimal urinishlar soni tugadi",
                order_id=order.id,
                attempts=order.fulfillment_attempts,
                correlation_id=order.correlation_id
            )
            await session.commit()
            return {"success": False, "manual_review": True, "error": "Maksimal urinishlar soni tugadi, DLQ ga yuborildi"}

        order.fulfillment_attempts += 1
        order.fulfillment_status = "processing"
        order.processing_at = utc_now()
        await session.commit()

        try:
            # Call fragment client
            result = await fragment_client.fulfill_order(order_id=order.id, bot=bot)

            if result.get("success") and result.get("fulfilled"):
                circuit_breaker.record_success("fragment")
                await circuit_breaker.sync_to_db(session, "fragment", is_success=True)

                tx_hash = result.get("tx_hash", "tx_done")
                order.fulfillment_status = "fulfilled"
                order.status = OrderStatus.COMPLETED
                order.completed_at = utc_now()
                order.fragment_tx_hash = tx_hash
                await session.commit()

                # Create in-app notification
                await notification_service.create_notification(
                    session=session,
                    user_id=order.user_id,
                    type_="order",
                    title="Buyurtmangiz yetkazildi! ⭐",
                    message=f"{order.item_title} muvaffaqiyatli yetkazildi. Buyurtma ID: {order.order_code}",
                    related_entity=f"order:{order.order_code}"
                )

                logger.info(f"[Fulfillment Succeeded] order={order.order_code}, tx={tx_hash}")
                return {"success": True, "fulfilled": True, "tx_hash": tx_hash}
            else:
                err_msg = result.get("error", "Yetkazib berishda xatolik")
                circuit_breaker.record_failure("fragment", err_msg)
                await circuit_breaker.sync_to_db(session, "fragment", error=err_msg, is_success=False)

                order.fulfillment_error = err_msg
                if order.fulfillment_attempts >= MAX_FULFILLMENT_RETRIES:
                    order.fulfillment_status = "manual_review"
                    order.status = OrderStatus.FAILED
                    # Route to DLQ
                    await dlq_service.record_failed_job(
                        session=session,
                        job_type="fulfillment",
                        payload={"order_id": order.id, "order_code": order.order_code, "recipient": order.recipient_username},
                        error_message=err_msg,
                        order_id=order.id,
                        attempts=order.fulfillment_attempts,
                        correlation_id=order.correlation_id
                    )
                else:
                    order.fulfillment_status = "retry_scheduled"
                await session.commit()

                logger.error(f"[Fulfillment Failed] order={order.order_code}, attempt={order.fulfillment_attempts}, error={err_msg}")
                return {"success": False, "error": err_msg}

        except Exception as e:
            err_str = str(e)
            circuit_breaker.record_failure("fragment", err_str)
            await circuit_breaker.sync_to_db(session, "fragment", error=err_str, is_success=False)

            logger.error(f"[Fulfillment Exception] order={order.order_code}: {e}", exc_info=True)
            order.fulfillment_error = err_str
            if order.fulfillment_attempts >= MAX_FULFILLMENT_RETRIES:
                order.fulfillment_status = "manual_review"
                order.status = OrderStatus.FAILED
                await dlq_service.record_failed_job(
                    session=session,
                    job_type="fulfillment",
                    payload={"order_id": order.id, "order_code": order.order_code, "recipient": order.recipient_username},
                    error_message=err_str,
                    tb=traceback.format_exc(),
                    order_id=order.id,
                    attempts=order.fulfillment_attempts,
                    correlation_id=order.correlation_id
                )
            await session.commit()
            return {"success": False, "error": err_str}


fulfillment_service = FulfillmentService()
