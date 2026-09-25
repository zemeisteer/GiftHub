import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.feature_flags import FeatureFlag

logger = get_logger(__name__)

# Default system flags initialized on first run
DEFAULT_FLAGS = {
    "maintenance_mode": (False, "Global platform maintenance mode. Disables client app and bot checkout."),
    "store_checkout_enabled": (True, "Enables new order creation and checkout across all products."),
    "stars_purchases_enabled": (True, "Enables Telegram Stars purchase catalog and checkout."),
    "premium_purchases_enabled": (True, "Enables Telegram Premium subscription plans."),
    "gifts_purchases_enabled": (True, "Enables Telegram Digital Gifts purchases."),
    "promocodes_enabled": (True, "Enables discount promo code redemption."),
    "referrals_enabled": (True, "Enables referral tracking and bonus reward distribution.")
}


class FeatureFlagService:
    def __init__(self):
        self._cache: Dict[str, bool] = {}
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 15.0 # Cache for 15s to minimize DB reads

    async def _refresh_cache(self, session: AsyncSession) -> None:
        try:
            res = await session.execute(select(FeatureFlag))
            flags = res.scalars().all()
            new_cache = {}
            for f in flags:
                new_cache[f.name] = f.is_enabled
            self._cache = new_cache
            self._cache_ts = time.time()
        except Exception as e:
            logger.warning(f"Failed to refresh feature flags cache: {e}")

    async def is_enabled(self, session: AsyncSession, flag_name: str, default: bool = True) -> bool:
        """Fast cached lookup for feature flags."""
        if time.time() - self._cache_ts > self._cache_ttl or flag_name not in self._cache:
            await self._refresh_cache(session)
        return self._cache.get(flag_name, default)

    async def is_maintenance_mode(self, session: AsyncSession) -> bool:
        """Returns True if platform-wide maintenance mode is enabled."""
        return await self.is_enabled(session, "maintenance_mode", default=False)

    async def set_flag(
        self,
        session: AsyncSession,
        name: str,
        is_enabled: bool,
        description: Optional[str] = None
    ) -> FeatureFlag:
        """Sets a feature flag and invalidates cache."""
        flag = await session.get(FeatureFlag, name)
        now = datetime.now(timezone.utc)
        if not flag:
            flag = FeatureFlag(name=name, is_enabled=is_enabled, description=description, updated_at=now)
            session.add(flag)
        else:
            flag.is_enabled = is_enabled
            if description:
                flag.description = description
            flag.updated_at = now

        await session.flush()
        self._cache_ts = 0.0 # Invalidate cache immediately
        logger.info(f"Feature flag '{name}' updated to {is_enabled}")
        return flag

    async def list_all_flags(self, session: AsyncSession) -> List[FeatureFlag]:
        """Returns all feature flags for the Admin Panel."""
        await self.ensure_defaults(session)
        res = await session.execute(select(FeatureFlag).order_by(FeatureFlag.name.asc()))
        return list(res.scalars().all())

    async def ensure_defaults(self, session: AsyncSession) -> None:
        """Seeds default feature flags if missing."""
        for name, (is_enabled, desc) in DEFAULT_FLAGS.items():
            existing = await session.get(FeatureFlag, name)
            if not existing:
                flag = FeatureFlag(
                    name=name,
                    is_enabled=is_enabled,
                    description=desc,
                    metadata_json={},
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(flag)
        await session.flush()


feature_flag_service = FeatureFlagService()
