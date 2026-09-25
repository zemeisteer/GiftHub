import logging
import re
import sys

SECRET_PATTERNS = [
    re.compile(r"(BOT_TOKEN\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(secret_key\s*[:=]\s*)([^\s,\"']+)", re.IGNORECASE),
    re.compile(r"(api_key\s*[:=]\s*)([^\s,\"']+)", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*)([^\s,\"']+)", re.IGNORECASE),
    re.compile(r"(\d{9,11}:[a-zA-Z0-9_-]{35})"), # Telegram bot token pattern
]

class SecretMaskingFormatter(logging.Formatter):
    """Filters out known sensitive keys from log messages and injects correlation ID."""
    def format(self, record: logging.LogRecord) -> str:
        try:
            from app.core.correlation import correlation_id_ctx
            cid = correlation_id_ctx.get()
            if cid and not getattr(record, "_cid_injected", False):
                record.msg = f"[{cid}] {record.msg}"
                record._cid_injected = True
        except (LookupError, AttributeError):
            pass
        except Exception as e:
            import sys
            sys.stderr.write(f"Correlation ID formatting error: {e}\n")

        original = super().format(record)
        masked = original
        for pattern in SECRET_PATTERNS:
            masked = pattern.sub(r"\1***MASKED***", masked)
        return masked


def setup_logger(log_level: str = "INFO"):
    root_logger = logging.getLogger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = SecretMaskingFormatter(
        fmt="%(asctime)s | %(levelname)-7s | [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    # Suppress verbose noise from third-party libraries
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
