import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_scope
from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.dlq import DLQStatus, FailedJob
from app.models.order import Order
from app.models.outbox import OutboxEvent, OutboxStatus
from app.models.pricing import PriceLock
from app.services.dlq.service import dlq_service
from app.services.fulfillment.service import fulfillment_service
from app.services.outbox.service import outbox_service
from app.services.reconciliation.service import reconciliation_service

logger = get_logger("GiftHubWorker")

# Shared in-memory async task queue
_async_queue = asyncio.Queue()
_shutdown_event = asyncio.Event()


def stop_worker():
    """Signals background worker to stop gracefully."""
    _shutdown_event.set()


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


async def _process_outbox_events_with_session(session: AsyncSession, bot=None):
    events = await outbox_service.fetch_pending_events(session=session, limit=10)
    for ev in events:
        try:
            if ev.event_type == "ORDER_FULFILLMENT_REQUESTED":
                order_id = int(ev.payload.get("order_id"))
                res = await fulfillment_service.fulfill_order_automated(session=session, order_id=order_id, bot=bot)
                if res.get("success"):
                    await outbox_service.mark_processed(session, ev.id)
                else:
                    await outbox_service.mark_failed(session, ev.id, res.get("error", "Fulfillment failed"))
            elif ev.event_type == "ORDER_REFUNDED":
                await outbox_service.mark_processed(session, ev.id)
            elif ev.event_type == "WALLET_DEPOSIT_COMPLETED":
                await outbox_service.mark_processed(session, ev.id)
            else:
                await outbox_service.mark_processed(session, ev.id)
        except Exception as e:
            logger.error(f"Error processing outbox event #{ev.id} ({ev.event_type}): {e}")
            await outbox_service.mark_failed(session, ev.id, str(e))


async def process_outbox_events_cycle(session: Optional[AsyncSession] = None, bot=None):
    """
    Transactional Outbox Poller.
    Picks up pending Outbox events committed with payments/orders and executes downstream tasks.
    Guarantees no paid order disappears without fulfillment being queued.
    """
    if session:
        await _process_outbox_events_with_session(session, bot)
    else:
        async with async_session_scope() as s:
            await _process_outbox_events_with_session(s, bot)


async def _process_dlq_retries_with_session(session: AsyncSession, bot=None):
    retrying_jobs = await dlq_service.list_failed_jobs(session=session, status=DLQStatus.RETRYING.value, limit=5)
    for job in retrying_jobs:
        try:
            if job.job_type == "fulfillment" and job.order_id:
                res = await fulfillment_service.fulfill_order_automated(session=session, order_id=job.order_id, bot=bot)
                if res.get("success") and res.get("fulfilled"):
                    await dlq_service.resolve_job(
                        session=session,
                        job_id=job.id,
                        admin_id=job.resolved_by or 0,
                        notes="Admin re-try succeeded."
                    )
                else:
                    job.status = DLQStatus.EXHAUSTED.value
                    job.error_message = res.get("error", "Retry failed")
                    await session.flush()
        except Exception as e:
            logger.error(f"Failed to retry DLQ job #{job.id}: {e}")


async def process_dlq_retries_cycle(session: Optional[AsyncSession] = None, bot=None):
    """
    Checks for DLQ jobs flagged as RETRYING by an admin and re-processes them.
    """
    if session:
        await _process_dlq_retries_with_session(session, bot)
    else:
        async with async_session_scope() as s:
            await _process_dlq_retries_with_session(s, bot)


async def run_worker_loop(bot=None):
    """Continuous background worker loop processing jobs from memory queue and database outbox."""
    logger.info("Starting GiftHub background worker loop with Outbox & DLQ support...")
    cycle_counter = 0

    while not _shutdown_event.is_set():
        try:
            # 1. Process in-memory tasks if any
            try:
                task = await asyncio.wait_for(_async_queue.get(), timeout=2.0)
                try:
                    await process_task(task, bot=bot)
                except Exception as e:
                    logger.error(f"Error processing background task {task}: {e}", exc_info=True)
                finally:
                    _async_queue.task_done()
            except asyncio.TimeoutError:
                pass # Queue was empty during timeout, proceed to outbox check

            # 2. Process Transactional Outbox events
            await process_outbox_events_cycle(bot=bot)

            # 3. Periodically check DLQ manual retries
            cycle_counter += 1
            if cycle_counter % 15 == 0: # Every ~30s
                await process_dlq_retries_cycle(bot=bot)

            # 4. Periodically run reconciliation audit
            if cycle_counter % 1800 == 0: # Every ~1 hour
                async with async_session_scope() as session:
                    await reconciliation_service.run_reconciliation_audit(session)

        except asyncio.CancelledError:
            logger.info("GiftHub background worker received cancellation signal.")
            break
        except Exception as e:
            logger.error(f"Unexpected worker loop exception: {e}", exc_info=True)
            await asyncio.sleep(2.0)

    logger.info("GiftHub background worker loop exited gracefully.")


if __name__ == "__main__":
    from app.core.logging import setup_logger
    setup_logger("INFO")
    logger.info("Running standalone GiftHub worker process...")
    asyncio.run(run_worker_loop())
