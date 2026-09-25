from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.logging import get_logger
from app.models.outbox import OutboxEvent, OutboxStatus

logger = get_logger(__name__)


class OutboxService:
    @staticmethod
    async def create_event(
        session: AsyncSession,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None
    ) -> OutboxEvent:
        """
        Creates an OutboxEvent within the caller's active database transaction.
        Guarantees that the event is committed together with the domain entity.
        """
        cid = correlation_id or get_correlation_id()
        now = datetime.now(timezone.utc)
        event = OutboxEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            payload=payload,
            status=OutboxStatus.PENDING.value,
            retry_count=0,
            max_retries=5,
            next_retry_at=now,
            correlation_id=cid,
            created_at=now
        )
        session.add(event)
        await session.flush()
        logger.info(f"Outbox event created: {event_type} for {aggregate_type}:{aggregate_id}")
        return event

    publish = create_event

    @classmethod
    async def claim_pending_events(
        cls,
        session: AsyncSession,
        worker_id: str = "worker-1",
        limit: int = 10,
        lock_timeout_seconds: int = 300
    ) -> List[OutboxEvent]:
        """
        Safely claims pending outbox events for a specific worker.
        Uses SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL to prevent multiple
        workers from claiming or executing the same event concurrently.
        Also re-claims stale PROCESSING events where locked_at > lock_timeout_seconds.
        Respects next_retry_at exponential backoff.
        """
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(seconds=lock_timeout_seconds)

        is_ready = and_(
            OutboxEvent.status.in_([OutboxStatus.PENDING.value, OutboxStatus.RETRY.value]),
            or_(OutboxEvent.next_retry_at.is_(None), OutboxEvent.next_retry_at <= now)
        )
        is_stale = and_(
            OutboxEvent.status == OutboxStatus.PROCESSING.value,
            or_(OutboxEvent.locked_at.is_(None), OutboxEvent.locked_at <= stale_threshold)
        )

        stmt = (
            select(OutboxEvent)
            .where(
                and_(
                    or_(is_ready, is_stale),
                    OutboxEvent.retry_count < OutboxEvent.max_retries
                )
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )

        bind = session.bind
        if bind and bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        else:
            stmt = stmt.with_for_update()

        res = await session.execute(stmt)
        events = list(res.scalars().all())

        for ev in events:
            ev.status = OutboxStatus.PROCESSING.value
            ev.locked_at = now
            ev.locked_by = worker_id

        if events:
            await session.flush()
        return events

    @classmethod
    async def fetch_pending_events(
        cls,
        session: AsyncSession,
        limit: int = 20,
        worker_id: str = "worker-default"
    ) -> List[OutboxEvent]:
        """Fetches and claims pending outbox events ordered by creation time."""
        return await cls.claim_pending_events(session=session, worker_id=worker_id, limit=limit)

    @staticmethod
    async def mark_processed(
        session: AsyncSession,
        event_id: int
    ) -> None:
        """Marks outbox event as successfully processed."""
        now = datetime.now(timezone.utc)
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status=OutboxStatus.PROCESSED.value,
                processed_at=now,
                locked_by=None,
                locked_at=None
            )
        )
        await session.flush()

    @staticmethod
    async def mark_failed(
        session: AsyncSession,
        event_id: int,
        error: str
    ) -> None:
        """
        Increments retry count, computes exponential backoff, and schedules next retry
        or routes to FAILED/DLQ if max retries reached.
        """
        event = await session.get(OutboxEvent, event_id)
        if not event:
            return
        now = datetime.now(timezone.utc)
        event.retry_count += 1
        event.last_error = error[:2000]
        event.locked_by = None
        event.locked_at = None

        if event.retry_count >= event.max_retries:
            event.status = OutboxStatus.FAILED.value
            logger.error(
                f"[Outbox Event Exhausted] event_id={event_id}, type={event.event_type} "
                f"failed permanently after {event.retry_count} retries: {error}"
            )
            if event.event_type == "ORDER_FULFILLMENT_REQUESTED" and event.aggregate_id:
                try:
                    from app.services.dlq.service import dlq_service
                    await dlq_service.record_failed_job(
                        session=session,
                        job_type="outbox_fulfillment",
                        payload=event.payload,
                        error_message=f"Outbox retries exhausted ({event.retry_count}): {error}",
                        order_id=int(event.aggregate_id) if str(event.aggregate_id).isdigit() else None,
                        attempts=event.retry_count,
                        correlation_id=event.correlation_id
                    )
                except Exception as dlq_err:
                    logger.error(f"Failed to record outbox failure to DLQ: {dlq_err}")
        else:
            # Exponential backoff: retry 1: 4s, retry 2: 8s, retry 3: 16s, retry 4: 32s (capped at 300s)
            backoff_sec = min(300, (2 ** event.retry_count) * 2)
            event.next_retry_at = now + timedelta(seconds=backoff_sec)
            event.status = OutboxStatus.RETRY.value
            logger.warning(
                f"[Outbox Retry Scheduled] event_id={event_id}, type={event.event_type}, "
                f"attempt={event.retry_count}/{event.max_retries}, backoff={backoff_sec}s, next={event.next_retry_at.isoformat()}"
            )
        await session.flush()


outbox_service = OutboxService()
