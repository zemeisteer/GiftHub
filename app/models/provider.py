from enum import Enum

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.models.base import Base, utc_now


class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Tripped / rejecting traffic
    HALF_OPEN = "half_open" # Testing recovery with probe requests


class ProviderHealth(Base):
    """
    Health and Circuit Breaker status for individual payment & fulfillment providers.
    E.g.: click, payme, autopaycard, fragment, telegram_api
    """
    __tablename__ = "provider_health"

    provider_name = Column(String(32), primary_key=True)
    status = Column(String(20), default=ProviderStatus.HEALTHY.value, nullable=False)
    circuit_state = Column(String(20), default=CircuitState.CLOSED.value, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    disabled_reason = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
