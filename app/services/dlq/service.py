import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.logging import get_logger
from app.models.dlq import DLQStatus, FailedJob

logger = get_logger(__name__)


class DLQService:
    @staticmethod
    async def record_failed_job(
        session: AsyncSession,
        job_type: str,
        payload: Dict[str, Any],
        error_message: str,
        tb: Optional[str] = None,
        order_id: Optional[int] = None,
        attempts: int = 1,
        correlation_id: Optional[str] = None
    ) -> FailedJob:
        """
        Stores an exhausted failed job in the Dead Letter Queue for admin review/recovery.
        """
        cid = correlation_id or get_correlation_id()
        failed_job = FailedJob(
            job_type=job_type,
            order_id=order_id,
            payload=payload,
            error_message=str(error_message)[:2000],
            traceback=(tb or traceback.format_exc())[:4000],
            attempts=attempts,
            status=DLQStatus.EXHAUSTED.value,
            correlation_id=cid,
            created_at=datetime.now(timezone.utc)
        )
        session.add(failed_job)
        await session.flush()
        logger.warning(f"Job moved to Dead Letter Queue (DLQ ID {failed_job.id}): {job_type} - {error_message}")
        return failed_job

    @staticmethod
    async def list_failed_jobs(
        session: AsyncSession,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[FailedJob]:
        """Lists DLQ jobs with optional status filter."""
        stmt = select(FailedJob).order_by(FailedJob.created_at.desc())
        if status:
            stmt = stmt.where(FailedJob.status == status)
        stmt = stmt.offset(offset).limit(limit)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def mark_retrying(
        session: AsyncSession,
        job_id: int,
        admin_id: Optional[int] = None
    ) -> Optional[FailedJob]:
        """Sets status to RETRYING for re-queueing by background workers."""
        job = await session.get(FailedJob, job_id)
        if not job:
            return None
        job.status = DLQStatus.RETRYING.value
        job.resolved_by = admin_id
        await session.flush()
        return job

    @staticmethod
    async def resolve_job(
        session: AsyncSession,
        job_id: int,
        admin_id: int,
        notes: str
    ) -> Optional[FailedJob]:
        """Marks a DLQ job as manually resolved."""
        job = await session.get(FailedJob, job_id)
        if not job:
            return None
        job.status = DLQStatus.RESOLVED.value
        job.resolved_by = admin_id
        job.resolution_notes = notes
        job.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        logger.info(f"DLQ job {job_id} resolved by admin {admin_id}: {notes}")
        return job


dlq_service = DLQService()
