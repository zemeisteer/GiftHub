from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text

from app.models.base import Base, utc_now


class CustomService(Base):
    __tablename__ = "custom_services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    category = Column(String(64), default="Xizmatlar", nullable=False)
    price_uzs = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    cost_uzs = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    icon = Column(String(16), default="⚡", nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
