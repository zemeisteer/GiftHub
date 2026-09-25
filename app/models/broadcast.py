from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text

from app.models.base import Base, utc_now


class BroadcastDraft(Base):
    __tablename__ = "broadcast_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String(32), default="write", nullable=False) # write, forward, postbot
    text = Column(Text, nullable=True)
    photo = Column(String(255), nullable=True)
    button_text = Column(String(64), nullable=True)
    button_url = Column(String(255), nullable=True)
    forward_chat_id = Column(BigInteger, nullable=True)
    forward_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
