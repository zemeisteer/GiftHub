"""Backward-compatibility re-export."""
from app.services.payments.autopaycard import (
    AutoPayCardProvider,
    autopaycard_provider,
    handle_autopaycard_webhook,
)

__all__ = [
    "AutoPayCardProvider",
    "autopaycard_provider",
    "handle_autopaycard_webhook",
]
