import os
from decimal import Decimal
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import engine, AsyncSessionLocal
from app.core.logging import get_logger
from app.models import (
    Base, PricingSetting, ReferralSetting, PaymentSetting, ChannelRequirement,
    User, PromoCode, FragmentSetting, UserJoinRequest, PaymentCard
)

logger = get_logger(__name__)

# Re-export engine and sessionmaker for backward compatibility
db_url = settings.DB_URL


async def init_db():
    """
    Initializes database schema and default records.
    In production, schema tables are managed strictly by Alembic migrations.
    """
    if settings.ENVIRONMENT != "production":
        async with engine.begin() as conn:
            # Create any tables not yet created for local dev / tests
            await conn.run_sync(Base.metadata.create_all)
    else:
        logger.info("Production mode: Schema tables are managed via Alembic migrations.")

    async with AsyncSessionLocal() as session:
        # 1. FragmentSetting singleton
        frag_setting = await session.get(FragmentSetting, 1)
        if not frag_setting:
            frag_setting = FragmentSetting(
                id=1,
                is_auto_buy=True,
                ton_wallet_address="",
                ton_wallet_mnemonic="",
                tonapi_key="",
                network="mainnet",
                min_ton_balance=Decimal("1.0000"),
                simulation_mode=False
            )
            session.add(frag_setting)

        # 2. PricingSetting singleton
        pricing = await session.get(PricingSetting, 1)
        if not pricing:
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
            session.add(pricing)

        # 3. ReferralSetting singleton
        referral = await session.get(ReferralSetting, 1)
        if not referral:
            referral = ReferralSetting(
                id=1,
                bonus_percent=Decimal("5.00"),
                min_purchase_uzs=Decimal("20000.00"),
                auto_reward=True,
                require_purchase=True
            )
            session.add(referral)

        # 4. PaymentSetting singleton
        payment = await session.get(PaymentSetting, 1)
        if not payment:
            payment = PaymentSetting(
                id=1,
                click_active=True,
                payme_active=True,
                card_active=True,
                card_number="",
                card_holder="",
                bank_name="",
                autopaycard_active=False
            )
            session.add(payment)

        # Clean up any leftover legacy demo channels
        await session.execute(
            delete(ChannelRequirement).where(
                (ChannelRequirement.username_or_link.in_(["@stellar_news", "@stellar_chat"])) |
                (ChannelRequirement.username_or_link.ilike("%stellar%"))
            )
        )

        # 5. Seed default promo codes only if SEED_DEMO_DATA=True or in local dev
        if settings.SEED_DEMO_DATA or settings.ENVIRONMENT == "development":
            res_promo = await session.execute(select(PromoCode))
            if not res_promo.scalars().first():
                p1 = PromoCode(
                    code="GIFTHUB10",
                    reward_type="discount_percent",
                    reward_value=Decimal("10.00"),
                    max_uses=500,
                    min_order_amount=Decimal("5000.00"),
                    is_active=True
                )
                session.add(p1)

        # 6. Seed super admins from config (strictly 0 balance - no free money in production)
        for admin_id in settings.ADMINS:
            user = await session.get(User, admin_id)
            if not user:
                user = User(
                    id=admin_id,
                    first_name="Super Admin",
                    username="superadmin",
                    role="super_admin",
                    balance=Decimal("0.00")
                )
                session.add(user)
            else:
                if user.role != "super_admin":
                    user.role = "super_admin"

        await session.commit()
        logger.info("Database essential singletons verified.")
