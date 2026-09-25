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
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, index=True, nullable=False)
    reward_type = Column(String(32), default="discount_percent", nullable=False) # discount_percent, fixed_discount, balance_bonus
    reward_value = Column(Numeric(18, 2), default=Decimal("10.00"), nullable=False)
    max_discount = Column(Numeric(18, 2), nullable=True) # Cap for percentage discounts
    min_order_amount = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    max_uses = Column(Integer, default=100, nullable=False)
    current_uses = Column(Integer, default=0, nullable=False)
    max_uses_per_user = Column(Integer, default=1, nullable=False)
    applicable_products = Column(String(128), default="all", nullable=False) # all, stars, premium, gift, service
    is_active = Column(Boolean, default=True, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    redemptions = relationship("PromoRedemption", back_populates="promo_code", cascade="all, delete-orphan")
    usages = relationship("PromoCodeUsage", back_populates="promo_code", cascade="all, delete-orphan")


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    benefit_amount = Column(Numeric(18, 2), nullable=False)
    redeemed_at = Column(DateTime(timezone=True), default=utc_now)

    promo_code = relationship("PromoCode", back_populates="redemptions")


class PromoCodeUsage(Base):
    """Legacy usage tracking table preserved for backward compatibility."""
    __tablename__ = "promo_code_usages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    benefit_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    used_at = Column(DateTime(timezone=True), default=utc_now)

    promo_code = relationship("PromoCode", back_populates="usages")
