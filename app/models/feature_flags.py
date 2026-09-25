from sqlalchemy import JSON, Boolean, Column, DateTime, String, Text

from app.models.base import Base, utc_now


class FeatureFlag(Base):
    """
    Dynamic feature flags and system controls controllable from Admin Panel
    without needing code redeployment.
    Examples:
      - store_checkout_enabled (bool)
      - stars_purchases_enabled (bool)
      - premium_purchases_enabled (bool)
      - gifts_purchases_enabled (bool)
      - maintenance_mode (bool)
    """

    __tablename__ = "feature_flags"

    name = Column(String(64), primary_key=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    description = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True, default=dict)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
