from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import OrderNotFoundError
from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.order import Order, OrderStatus
from app.services.fragment import fragment_client
from app.services.notifications.service import notification_service

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
        Executes automated Fragment/blockchain delivery with retry limits and duplicate delivery protection.
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

        # RETRY LIMIT CHECK
        if order.fulfillment_attempts >= MAX_FULFILLMENT_RETRIES:
            logger.warning(f"[Fulfillment] Order {order.order_code} exceeded max retries. Routing to manual review.")
            order.fulfillment_status = "manual_review"
            await session.commit()
            return {"success": False, "manual_review": True, "error": "Maksimal urinishlar soni tugadi"}

        order.fulfillment_attempts += 1
        order.fulfillment_status = "processing"
        order.processing_at = utc_now()
        await session.commit()

        try:
            # Call fragment client
            result = await fragment_client.fulfill_order(order_id=order.id, bot=bot)

            if result.get("success") and result.get("fulfilled"):
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
                order.fulfillment_error = err_msg
                if order.fulfillment_attempts >= MAX_FULFILLMENT_RETRIES:
                    order.fulfillment_status = "manual_review"
                    order.status = OrderStatus.FAILED
                else:
                    order.fulfillment_status = "retry_scheduled"
                await session.commit()

                logger.error(f"[Fulfillment Failed] order={order.order_code}, attempt={order.fulfillment_attempts}, error={err_msg}")
                return {"success": False, "error": err_msg}

        except Exception as e:
            logger.error(f"[Fulfillment Exception] order={order.order_code}: {e}", exc_info=True)
            order.fulfillment_error = str(e)
            if order.fulfillment_attempts >= MAX_FULFILLMENT_RETRIES:
                order.fulfillment_status = "manual_review"
                order.status = OrderStatus.FAILED
            await session.commit()
            return {"success": False, "error": str(e)}


fulfillment_service = FulfillmentService()
