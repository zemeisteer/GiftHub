from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="chk_users_balance_non_neg"),
        CheckConstraint("referral_earnings >= 0", name="chk_users_ref_earnings_non_neg"),
    )

    id = Column(BigInteger, primary_key=True, index=True)  # Telegram User ID
    first_name = Column(String(128), nullable=False, default="")
    last_name = Column(String(128), nullable=True, default="")
    username = Column(String(64), nullable=True, index=True)
    photo_url = Column(String(512), nullable=True)
    balance = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    referrer_id = Column(BigInteger, nullable=True, index=True)
    referral_earnings = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    referrals_count = Column(Integer, default=0, nullable=False)
    role = Column(
        String(32), default="user", nullable=False
    )  # super_admin, price_admin, support_admin, marketing_admin, user
    is_blocked = Column(Boolean, default=False, nullable=False)
    is_flagged_for_abuse = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    orders = relationship("Order", back_populates="user")
    wallet_transactions = relationship("WalletTransaction", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    support_tickets = relationship("SupportTicket", back_populates="user")
    notifications = relationship("InAppNotification", back_populates="user")
    saved_recipients = relationship("SavedRecipient", back_populates="user", cascade="all, delete-orphan")

    @property
    def telegram_id(self) -> int:
        return self.id

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name or ''}".strip()
