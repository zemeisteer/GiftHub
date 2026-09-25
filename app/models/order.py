from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.exceptions import InvalidOrderStateError
from app.models.base import Base, utc_now


class OrderStatus(str, Enum):
    CREATED = "created"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    EXPIRED = "expired"

    # Backward compatibility aliases
    DONE = "completed"
    CANCEL = "cancelled"
    PENDING = "awaiting_payment"


VALID_ORDER_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.CREATED: {
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.PAID,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED
    },
    OrderStatus.AWAITING_PAYMENT: {
        OrderStatus.PAID,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED
    },
    OrderStatus.PAID: {
        OrderStatus.PROCESSING,
        OrderStatus.COMPLETED,
        OrderStatus.FAILED,
        OrderStatus.REFUNDED
    },
    OrderStatus.PROCESSING: {
        OrderStatus.COMPLETED,
        OrderStatus.FAILED,
        OrderStatus.REFUNDED
    },
    OrderStatus.COMPLETED: {
        OrderStatus.REFUNDED # Admin recovery or explicit refund
    },
    OrderStatus.FAILED: {
        OrderStatus.PROCESSING, # Manual or automated retry
        OrderStatus.REFUNDED,
        OrderStatus.CANCELLED
    },
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
    OrderStatus.EXPIRED: set()
}


def normalize_status(status: str) -> str:
    """Normalizes legacy status strings ('done' -> 'completed', 'cancel' -> 'cancelled', 'pending' -> 'awaiting_payment')."""
    s = (status or "").lower()
    if s == "done":
        return OrderStatus.COMPLETED
    if s == "cancel":
        return OrderStatus.CANCELLED
    if s == "pending":
        return OrderStatus.AWAITING_PAYMENT
    return s


def validate_order_transition(current_status: str, new_status: str) -> None:
    current_norm = normalize_status(current_status)
    new_norm = normalize_status(new_status)

    if current_norm == new_norm:
        return

    allowed = VALID_ORDER_TRANSITIONS.get(current_norm, set())
    if new_norm not in allowed:
        raise InvalidOrderStateError(
            f"Buyurtma holatini '{current_norm}' dan '{new_norm}' ga o'tkazish mumkin emas."
        )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_price >= 0", name="chk_orders_total_price_non_neg"),
        CheckConstraint("amount > 0", name="chk_orders_amount_positive"),
        CheckConstraint("unit_price >= 0", name="chk_orders_unit_price_non_neg"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_code = Column(String(32), unique=True, index=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_type = Column(String(32), nullable=False) # stars, premium, gift, service
    item_title = Column(String(128), nullable=False)
    amount = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    total_price = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    cost_price = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    margin = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    discount_amount = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    exchange_rate = Column(Numeric(18, 4), default=Decimal("1.0000"), nullable=False)
    currency = Column(String(8), default="UZS", nullable=False)
    promo_code = Column(String(32), nullable=True)
    payment_method = Column(String(32), default="balance", nullable=False)
    status = Column(String(32), default=OrderStatus.CREATED, index=True, nullable=False)
    recipient_username = Column(String(64), nullable=True)
    price_lock_id = Column(String(64), nullable=True)
    correlation_id = Column(String(64), nullable=True, index=True)

    # Fragment / Delivery fields
    fragment_req_id = Column(String(64), nullable=True)
    fragment_payload = Column(Text, nullable=True)
    fragment_tx_hash = Column(String(128), nullable=True)
    fulfillment_status = Column(String(32), default="pending") # pending, processing, fulfilled, failed, manual_review
    fulfillment_attempts = Column(Integer, default=0, nullable=False)
    fulfillment_error = Column(Text, nullable=True)

    # State Timestamps
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    processing_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="orders")
    payment_transactions = relationship("PaymentTransaction", back_populates="order")
    timeline = relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan", order_by="OrderStatusHistory.created_at.asc()")


class OrderStatusHistory(Base):
    """
    Detailed order timeline and status transition history.
    Tracks every status change, timestamp, actor, and contextual notes.
    """
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    order_code = Column(String(32), index=True, nullable=False)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=False)
    actor = Column(String(32), default="SYSTEM", nullable=False) # SYSTEM, USER, ADMIN, WORKER, WEBHOOK
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    order = relationship("Order", back_populates="timeline")


class CheckoutIdempotency(Base):
    """
    Prevents duplicate purchases from rapid clicks or network retries.
    """
    __tablename__ = "checkout_idempotency"

    idempotency_key = Column(String(128), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    request_hash = Column(String(64), nullable=False)
    response_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
