from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(32), nullable=False) # payment, order, refund, referral, promo, support, system
    title = Column(String(128), nullable=False)
    message = Column(Text, nullable=False)
    related_entity = Column(String(64), nullable=True) # e.g. "order:#12345"
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", back_populates="notifications")
