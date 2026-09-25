import asyncio
from typing import Any

from sqlalchemy import select

from app.core.database import async_session_scope
from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.order import Order
from app.models.pricing import PriceLock
from app.services.fulfillment.service import fulfillment_service

logger = get_logger("GiftHubWorker")

# Shared in-memory async task queue when running standalone or in single-process mode
_async_queue = asyncio.Queue()


async def enqueue_task(task_type: str, payload: dict[str, Any]):
    """Enqueues a background job to be processed outside of request cycles."""
    await _async_queue.put({"type": task_type, "payload": payload})
    logger.debug(f"Enqueued task: {task_type}")


async def process_task(task: dict[str, Any], bot=None):
    t_type = task.get("type")
    payload = task.get("payload", {})

    if t_type == "fulfill_order":
        order_id = payload.get("order_id")
        if order_id:
            async with async_session_scope() as session:
                await fulfillment_service.fulfill_order_automated(session=session, order_id=order_id, bot=bot)

    elif t_type == "cleanup_expired_price_locks":
        async with async_session_scope() as session:
            now = utc_now()
            from sqlalchemy import delete
            await session.execute(
                delete(PriceLock).where(PriceLock.expires_at < now, PriceLock.is_used == False)
            )

    elif t_type == "retry_failed_fulfillments":
        async with async_session_scope() as session:
            res = await session.execute(
                select(Order.id).where(
                    Order.fulfillment_status == "retry_scheduled",
                    Order.fulfillment_attempts < 3
                )
            )
            order_ids = res.scalars().all()
            for oid in order_ids:
                await fulfillment_service.fulfill_order_automated(session=session, order_id=oid, bot=bot)


async def run_worker_loop(bot=None):
    """Continuous background worker loop processing jobs from the queue."""
    logger.info("Starting GiftHub background worker loop...")
    while True:
        try:
            task = await _async_queue.get()
            try:
                await process_task(task, bot=bot)
            except Exception as e:
                logger.error(f"Error processing background task {task}: {e}", exc_info=True)
            finally:
                _async_queue.task_done()
        except asyncio.CancelledError:
            logger.info("GiftHub background worker shutting down.")
            break
        except Exception as e:
            logger.error(f"Unexpected worker loop exception: {e}", exc_info=True)
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    from app.core.logging import setup_logger
    setup_logger("INFO")
    logger.info("Running standalone GiftHub worker process...")
    asyncio.run(run_worker_loop())
