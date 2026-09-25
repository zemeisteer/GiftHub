import uuid
from contextvars import ContextVar

# ContextVar for tracing request / transaction lifecycle across Telegram, API, Orders, Workers
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Returns the current correlation ID or a newly generated one if not set."""
    cid = correlation_id_ctx.get()
    if not cid:
        cid = f"gh-{uuid.uuid4().hex[:12]}"
        correlation_id_ctx.set(cid)
    return cid


def set_correlation_id(cid: str | None = None) -> str:
    """Sets correlation ID in the context and returns it."""
    clean_id = cid or f"gh-{uuid.uuid4().hex[:12]}"
    correlation_id_ctx.set(clean_id)
    return clean_id
