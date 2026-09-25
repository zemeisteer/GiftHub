from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class BasePaymentProvider(ABC):
    provider_name: str

    @abstractmethod
    def generate_checkout_url(self, user_id: int, amount: Decimal, return_url: str | None = None) -> str:
        """Generates the external payment link for customer checkout."""

    @abstractmethod
    async def process_webhook(self, session: AsyncSession, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Processes provider webhook with signature verification and idempotency."""
