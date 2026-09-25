from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class PaymentTransaction(Base):
    """
    Unified Payment Transaction Ledger.
    Guarantees idempotency via database-level unique constraint on (provider, provider_transaction_id).
    """
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, index=True) # click, payme, autopaycard, manual_card
    provider_transaction_id = Column(String(128), nullable=False, index=True)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(8), default="UZS", nullable=False)
    status = Column(String(32), default="pending", index=True) # pending, prepared, success, failed, cancelled, refunded
    raw_payload = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    order = relationship("Order", back_populates="payment_transactions")

    __table_args__ = (
        UniqueConstraint("provider", "provider_transaction_id", name="uq_provider_tx_id"),
    )


class ClickTransaction(Base):
    """
    Dedicated Click Merchant transactions table (preserved for backward compatibility).
    """
    __tablename__ = "click_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    click_trans_id = Column(BigInteger, unique=True, index=True, nullable=False)
    service_id = Column(Integer, nullable=False)
    merchant_trans_id = Column(String(64), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    action = Column(Integer, nullable=False) # 0: prepare, 1: complete
    error = Column(Integer, default=0)
    error_note = Column(String(255), default="Success")
    sign_time = Column(String(32), nullable=True)
    sign_string = Column(String(255), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), default="prepared") # prepared, completed, cancelled
    created_at = Column(DateTime(timezone=True), default=utc_now)


class PaymeTransaction(Base):
    """
    Dedicated Payme Paycom transactions table (preserved for backward compatibility).
    """
    __tablename__ = "payme_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paycom_id = Column(String(64), unique=True, index=True, nullable=False)
    paycom_time = Column(BigInteger, nullable=False)
    create_time = Column(BigInteger, default=lambda: int(datetime.utcnow().timestamp() * 1000))
    perform_time = Column(BigInteger, default=0)
    cancel_time = Column(BigInteger, default=0)
    amount = Column(BigInteger, nullable=False) # In tiyin (1 UZS = 100 tiyin)
    state = Column(Integer, default=1) # 1: created, 2: performed, -1: cancelled created, -2: cancelled performed
    reason = Column(Integer, nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)


class PaymentCard(Base):
    __tablename__ = "payment_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    card_number = Column(String(32), nullable=False)
    card_holder = Column(String(128), nullable=False)
    bank_name = Column(String(64), nullable=False)
    card_type = Column(String(32), default="UZCARD")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)


class PaymentSetting(Base):
    __tablename__ = "payment_settings"

    id = Column(Integer, primary_key=True)
    click_active = Column(Boolean, default=True)
    payme_active = Column(Boolean, default=True)
    card_active = Column(Boolean, default=True)
    card_number = Column(String(32), default="8600 1234 5678 9012")
    card_holder = Column(String(128), default="ANVAR S.")
    bank_name = Column(String(64), default="TBC Bank")
    autopaycard_active = Column(Boolean, default=False)
    autopaycard_api_key = Column(String(255), default="")
    autopaycard_last4 = Column(String(8), default="6412")
    autopaycard_email = Column(String(128), default="payments.gifthub@gmail.com")
    autopaycard_webhook_url = Column(String(255), default="https://gifthub.uz/webhook/autopaycard")
