import hashlib
import hmac
import time
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.payment import PaymentSetting
from app.models.pricing import PricingSetting
from app.models.referral import ReferralSetting
from app.models.user import User

# Test database using in-memory aiosqlite
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        # Seed default pricing and payment settings
        pricing = PricingSetting(
            id=1,
            stars_cost_ton=Decimal("0.0021"),
            ton_rate_uzs=Decimal("14800.00"),
            margin_percent=Decimal("15.00"),
            star_unit_price_uzs=Decimal("180.00"),
            minimum_margin=Decimal("5.00"),
            maximum_discount=Decimal("30.00"),
            minimum_price=Decimal("1000.00")
        )
        pay_setting = PaymentSetting(
            id=1,
            click_active=True,
            payme_active=True,
            card_active=True
        )
        ref_setting = ReferralSetting(
            id=1,
            bonus_percent=Decimal("5.00"),
            min_purchase_uzs=Decimal("10000.00"),
            auto_reward=True,
            require_purchase=True
        )
        session.add_all([pricing, pay_setting, ref_setting])
        await session.commit()

        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    user = User(
        id=12345678,
        username="testbuyer",
        first_name="Test",
        last_name="Buyer",
        balance=Decimal("150000.00"),
        role="user"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def sample_admin(db_session: AsyncSession) -> User:
    admin = User(
        id=99999999,
        username="superadmin",
        first_name="Super",
        last_name="Admin",
        balance=Decimal("0.00"),
        role="super_admin"
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


def make_telegram_init_data(bot_token: str, user_id: int, username: str = "testuser", auth_date: int = None) -> str:
    """Helper to generate cryptographically valid Telegram initData for tests."""
    if auth_date is None:
        auth_date = int(time.time())
    user_json = f'{{"id":{user_id},"first_name":"Test","username":"{username}","language_code":"uz"}}'
    
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhr123",
        "user": user_json
    }
    
    # Sort keys
    data_check_arr = [f"{k}={params[k]}" for k in sorted(params.keys())]
    data_check_string = "\n".join(data_check_arr)
    
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    import urllib.parse
    params["hash"] = computed_hash
    return urllib.parse.urlencode(params)
