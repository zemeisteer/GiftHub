from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String

from app.models.base import Base, utc_now


class ChannelRequirement(Base):
    __tablename__ = "channel_requirements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=True, index=True)
    username_or_link = Column(String(255), nullable=False)
    title = Column(String(128), nullable=False)
    req_type = Column(String(32), default="ordinary", nullable=False) # ordinary, join_request, external
    is_active = Column(Boolean, default=True, nullable=False)
    is_detected = Column(Boolean, default=False, nullable=False) # True if auto-detected via my_chat_member


class UserJoinRequest(Base):
    __tablename__ = "user_join_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
