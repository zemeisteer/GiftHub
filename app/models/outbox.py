from enum import Enum

from sqlalchemy import JSON, BigInteger, Column, DateTime, Integer, String, Text

from app.models.base import Base, utc_now


class OutboxStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    PROCESSED = "processed"
    FAILED = "failed"


class OutboxEvent(Base):
    """
    Transactional Outbox pattern for mission-critical events.
    Committed in the same database transaction as financial/order mutations.
    """
    __tablename__ = "outbox_events"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False, index=True) # e.g. PAYMENT_CONFIRMED, ORDER_FULFILLMENT_REQUESTED
    aggregate_type = Column(String(32), nullable=False, index=True) # order, payment, user
    aggregate_id = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), default=OutboxStatus.PENDING.value, nullable=False, index=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=5, nullable=False)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(String(64), nullable=True)
    last_error = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
