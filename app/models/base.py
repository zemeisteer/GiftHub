from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import declarative_base

Base = declarative_base()

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

DECIMAL_ZERO = Decimal("0.00")
