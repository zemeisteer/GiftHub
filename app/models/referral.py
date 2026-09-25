from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)

from app.models.base import Base, utc_now


class ReferralSetting(Base):
    __tablename__ = "referral_settings"

    id = Column(Integer, primary_key=True)
    bonus_percent = Column(Numeric(18, 2), default=Decimal("5.00"), nullable=False)
    min_purchase_uzs = Column(Numeric(18, 2), default=Decimal("20000.00"), nullable=False)
    auto_reward = Column(Boolean, default=True, nullable=False)
    require_purchase = Column(Boolean, default=True, nullable=False)
    # Configurable tiers
    tier_1_count = Column(Integer, default=5)
    tier_1_percent = Column(Numeric(18, 2), default=Decimal("5.00"))
    tier_2_count = Column(Integer, default=20)
    tier_2_percent = Column(Numeric(18, 2), default=Decimal("7.00"))
    tier_3_count = Column(Integer, default=50)
    tier_3_percent = Column(Numeric(18, 2), default=Decimal("10.00"))


class ReferralReward(Base):
    """
    Transparent, idempotent referral reward ledger.
    Unique constraint on order_id ensures an order can never be rewarded twice.
    """

    __tablename__ = "referral_rewards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    referred_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    commission_rate = Column(Numeric(18, 2), nullable=False)
    commission_amount = Column(Numeric(18, 2), nullable=False)
    status = Column(String(32), default="paid", nullable=False)  # pending, paid, cancelled
    created_at = Column(DateTime(timezone=True), default=utc_now)
