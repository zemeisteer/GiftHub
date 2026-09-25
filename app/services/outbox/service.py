import json
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select, update
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
        event = OutboxEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            payload=payload,
            status=OutboxStatus.PENDING.value,
            retry_count=0,
            max_retries=5,
            correlation_id=cid,
            created_at=datetime.now(timezone.utc)
        )
        session.add(event)
        await session.flush()
        logger.info(f"Outbox event created: {event_type} for {aggregate_type}:{aggregate_id}")
        return event

    @staticmethod
    async def fetch_pending_events(
        session: AsyncSession,
        limit: int = 20
    ) -> List[OutboxEvent]:
        """Fetches pending outbox events ordered by creation time."""
        stmt = (
            select(OutboxEvent)
            .where(
                and_(
                    OutboxEvent.status.in_([OutboxStatus.PENDING.value, OutboxStatus.PROCESSING.value]),
                    OutboxEvent.retry_count < OutboxEvent.max_retries
                )
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def mark_processed(
        session: AsyncSession,
        event_id: int
    ) -> None:
        """Marks outbox event as successfully processed."""
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status=OutboxStatus.PROCESSED.value,
                processed_at=datetime.now(timezone.utc)
            )
        )
        await session.flush()

    @staticmethod
    async def mark_failed(
        session: AsyncSession,
        event_id: int,
        error: str
    ) -> None:
        """Increments retry count or marks event FAILED if max retries reached."""
        event = await session.get(OutboxEvent, event_id)
        if not event:
            return
        event.retry_count += 1
        event.last_error = error[:2000]
        if event.retry_count >= event.max_retries:
            event.status = OutboxStatus.FAILED.value
            logger.error(f"Outbox event {event_id} failed permanently after {event.retry_count} retries: {error}")
        else:
            event.status = OutboxStatus.PENDING.value # Allow retry on next cycle
        await session.flush()


outbox_service = OutboxService()
