from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class SavedRecipient(Base):
    """
    User's saved recipient contacts for quick checkout selection.
    """
    __tablename__ = "saved_recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_username = Column(String(64), nullable=False)
    label = Column(String(64), nullable=True) # e.g. "Do'stim", "O'zim"
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="saved_recipients")
