from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class WalletTransaction(Base):
    """
    Immutable Wallet Ledger table.
    Tracks every balance mutation with before/after snapshots and traceable reference.
    """
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tx_type = Column(String(32), nullable=False) # deposit, purchase, refund, referral_bonus, admin_adjustment, promo_bonus
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(8), default="UZS", nullable=False)
    balance_before = Column(Numeric(18, 2), nullable=False)
    balance_after = Column(Numeric(18, 2), nullable=False)
    reference_type = Column(String(64), nullable=True, index=True) # order, payment, referral, admin, promo
    reference_id = Column(String(128), nullable=True, index=True)
    note = Column(String(255), nullable=True)
    meta_info = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="wallet_transactions")


class Transaction(Base):
    """
    Legacy transaction table maintained for backward compatibility.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    tx_type = Column(String(32), nullable=False) # topup, purchase, refund, referral_bonus, admin_adjustment
    method = Column(String(32), default="balance") # click, payme, autopaycard, balance, admin
    status = Column(String(32), default="success") # pending, success, failed
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", back_populates="transactions")
