from enum import Enum

from sqlalchemy import JSON, BigInteger, Column, DateTime, Integer, String, Text

from app.models.base import Base, utc_now


class DLQStatus(str, Enum):
    EXHAUSTED = "exhausted"  # Retries completely failed
    RETRYING = "retrying"  # Re-queued by admin
    RESOLVED = "resolved"  # Manually marked resolved by admin
    CANCELLED = "cancelled"  # Dismissed / refunded


class FailedJob(Base):
    """
    Dead Letter Queue (DLQ) persistent storage for jobs whose retries were exhausted.
    Surfaces on the Admin Panel for monitoring, manual intervention, and retries.
    """

    __tablename__ = "failed_jobs"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    job_type = Column(String(64), nullable=False, index=True)  # e.g. fulfillment, webhook_dispatch, outbox
    order_id = Column(BigInteger, nullable=True, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=False)
    traceback = Column(Text, nullable=True)
    attempts = Column(Integer, default=1, nullable=False)
    status = Column(String(20), default=DLQStatus.EXHAUSTED.value, nullable=False, index=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_by = Column(BigInteger, nullable=True)  # Admin ID who resolved it
    correlation_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
