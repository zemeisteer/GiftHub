import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def build_engine(db_url: str) -> AsyncEngine:
    if "postgresql" in db_url:
        return create_async_engine(
            db_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    else:
        # SQLite
        if db_url.startswith("sqlite+aiosqlite:///"):
            data_dir = os.path.dirname(db_url.replace("sqlite+aiosqlite:///", ""))
            if data_dir:
                os.makedirs(data_dir, exist_ok=True)
        return create_async_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False} if "sqlite" in db_url else {}
        )


engine = build_engine(settings.DB_URL)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding database session with safe rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def async_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for background workers and services."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
