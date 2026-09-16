import os
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from data import config
from database.models import (
    Base, PricingSetting, ReferralSetting, PaymentSetting, ChannelRequirement, User, PromoCode, FragmentSetting, UserJoinRequest
)

# SQLite path check if relative
db_url = config.DB_URL
if db_url.startswith("sqlite+aiosqlite:///"):
    relative_path = db_url.replace("sqlite+aiosqlite:///", "")
    if not os.path.isabs(relative_path):
        abs_db_path = os.path.join(config.BASE_DIR, relative_path).replace("\\", "/")
        db_url = f"sqlite+aiosqlite:///{abs_db_path}"
    data_dir = os.path.dirname(db_url.replace("sqlite+aiosqlite:///", ""))
    os.makedirs(data_dir, exist_ok=True)

engine = create_async_engine(db_url, echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate star_unit_price_uzs if not exists
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE pricing_settings ADD COLUMN star_unit_price_uzs FLOAT DEFAULT 180.0"))
        except Exception:
            pass # column already exists

        # Migrate orders fragment fields if not exists
        for col_sql in [
            "ALTER TABLE orders ADD COLUMN fragment_req_id VARCHAR(64)",
            "ALTER TABLE orders ADD COLUMN fragment_payload TEXT",
            "ALTER TABLE orders ADD COLUMN fragment_tx_hash VARCHAR(128)",
            "ALTER TABLE orders ADD COLUMN fulfillment_status VARCHAR(32) DEFAULT 'pending'",
            "ALTER TABLE orders ADD COLUMN fulfillment_error TEXT"
        ]:
            try:
                from sqlalchemy import text
                await conn.execute(text(col_sql))
            except Exception:
                pass

        # Migrate payment card fields if not exists
        for col_sql in [
            "ALTER TABLE payment_settings ADD COLUMN card_active BOOLEAN DEFAULT 1",
            "ALTER TABLE payment_settings ADD COLUMN card_number VARCHAR(32) DEFAULT '8600 1234 5678 9012'",
            "ALTER TABLE payment_settings ADD COLUMN card_holder VARCHAR(128) DEFAULT 'ANVAR S.'",
            "ALTER TABLE payment_settings ADD COLUMN bank_name VARCHAR(64) DEFAULT 'TBC Bank'"
        ]:
            try:
                from sqlalchemy import text
                await conn.execute(text(col_sql))
            except Exception:
                pass

    # Initialize default settings if not exists
    async with AsyncSessionLocal() as session:
        # Check FragmentSetting
        frag_setting = await session.get(FragmentSetting, 1)
        if not frag_setting:
            frag_setting = FragmentSetting(
                id=1,
                is_auto_buy=True,
                ton_wallet_address="",
                ton_wallet_mnemonic="",
                tonapi_key="",
                network="mainnet",
                min_ton_balance=1.0,
                simulation_mode=False
            )
            session.add(frag_setting)
        # Check PricingSetting
        pricing = await session.get(PricingSetting, 1)
        if not pricing:
            pricing = PricingSetting(
                id=1,
                stars_cost_ton=0.0021,
                ton_rate_uzs=14800.0,
                margin_percent=15.0
            )
            session.add(pricing)

        # Check ReferralSetting
        referral = await session.get(ReferralSetting, 1)
        if not referral:
            referral = ReferralSetting(
                id=1,
                bonus_percent=5.0,
                min_purchase_uzs=20000.0,
                auto_reward=True,
                require_purchase=True
            )
            session.add(referral)

        # Check PaymentSetting
        payment = await session.get(PaymentSetting, 1)
        if not payment:
            payment = PaymentSetting(
                id=1,
                click_active=True,
                payme_active=True,
                autopaycard_active=False
            )
            session.add(payment)

        # Clean up any leftover demo channels if they were added previously
        from sqlalchemy import delete
        await session.execute(
            delete(ChannelRequirement).where(
                ChannelRequirement.username_or_link.in_(["@stellar_news", "@stellar_chat"])
            )
        )

        # Seed default demo promo codes
        res_promo = await session.execute(select(PromoCode))
        if not res_promo.scalars().first():
            p1 = PromoCode(
                code="STELLAR10",
                reward_type="discount_percent",
                reward_value=10.0,
                max_uses=500,
                min_order_amount=5000.0,
                is_active=True
            )
            p2 = PromoCode(
                code="WELCOME5K",
                reward_type="balance_bonus",
                reward_value=5000.0,
                max_uses=1000,
                is_active=True
            )
            session.add_all([p1, p2])

        # Seed super admins from config
        for admin_id_str in config.ADMINS:
            try:
                admin_id = int(admin_id_str.strip())
                user = await session.get(User, admin_id)
                if not user:
                    user = User(
                        id=admin_id,
                        first_name="Super Admin",
                        username="superadmin",
                        role="super_admin",
                        balance=500000.0
                    )
                    session.add(user)
                else:
                    if user.role != "super_admin":
                        user.role = "super_admin"
            except ValueError:
                pass

        await session.commit()
