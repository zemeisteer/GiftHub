"""Backward-compatibility re-export."""

from app.services.payments.click import (
    ClickProvider,
    click_provider,
    generate_click_link,
    process_click_complete,
    process_click_prepare,
    verify_click_signature,
)

__all__ = [
    "ClickProvider",
    "click_provider",
    "generate_click_link",
    "process_click_complete",
    "process_click_prepare",
    "verify_click_signature",
]
