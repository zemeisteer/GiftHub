import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.catalog import CatalogProduct

logger = get_logger(__name__)

DEFAULT_PRODUCTS = [
    # Stars
    {"category": "stars", "sku": "stars_50", "title": "50 Telegram Stars", "quantity": 50, "base_price_uzs": Decimal("11000.00"), "display_order": 1, "badge_text": ""},
    {"category": "stars", "sku": "stars_100", "title": "100 Telegram Stars", "quantity": 100, "base_price_uzs": Decimal("21500.00"), "display_order": 2, "badge_text": "Ommabop"},
    {"category": "stars", "sku": "stars_250", "title": "250 Telegram Stars", "quantity": 250, "base_price_uzs": Decimal("53000.00"), "display_order": 3, "badge_text": ""},
    {"category": "stars", "sku": "stars_500", "title": "500 Telegram Stars", "quantity": 500, "base_price_uzs": Decimal("105000.00"), "display_order": 4, "badge_text": "Qulay"},
    {"category": "stars", "sku": "stars_1000", "title": "1000 Telegram Stars", "quantity": 1000, "base_price_uzs": Decimal("209000.00"), "display_order": 5, "badge_text": "-5%"},

    # Premium
    {"category": "premium", "sku": "premium_3m", "title": "Telegram Premium 3 oylik", "quantity": 1, "duration_months": 3, "base_price_uzs": Decimal("145000.00"), "display_order": 1, "badge_text": ""},
    {"category": "premium", "sku": "premium_6m", "title": "Telegram Premium 6 oylik", "quantity": 1, "duration_months": 6, "base_price_uzs": Decimal("195000.00"), "display_order": 2, "badge_text": "Eng mashhur"},
    {"category": "premium", "sku": "premium_12m", "title": "Telegram Premium 12 oylik", "quantity": 1, "duration_months": 12, "base_price_uzs": Decimal("320000.00"), "display_order": 3, "badge_text": "-25%"},

    # Gifts
    {"category": "gift", "sku": "gift_teddy", "title": "Teddy Bear Sovg'asi", "quantity": 15, "base_price_uzs": Decimal("35000.00"), "display_order": 1, "badge_text": "Yangi"},
    {"category": "gift", "sku": "gift_heart", "title": "Red Heart Sovg'asi", "quantity": 25, "base_price_uzs": Decimal("55000.00"), "display_order": 2, "badge_text": "Romantik"},
    {"category": "gift", "sku": "gift_cake", "title": "Birthday Cake Sovg'asi", "quantity": 50, "base_price_uzs": Decimal("110000.00"), "display_order": 3, "badge_text": "Tavsiya"}
]


class CatalogService:
    @staticmethod
    async def list_products(
        session: AsyncSession,
        category: Optional[str] = None,
        active_only: bool = True
    ) -> List[CatalogProduct]:
        """Lists products ordered by display_order."""
        await CatalogService.ensure_default_catalog(session)
        stmt = select(CatalogProduct).order_by(CatalogProduct.category.asc(), CatalogProduct.display_order.asc())
        if category:
            stmt = stmt.where(CatalogProduct.category == category)
        if active_only:
            stmt = stmt.where(CatalogProduct.is_active == True)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_by_sku(session: AsyncSession, sku: str) -> Optional[CatalogProduct]:
        """Fetches product by SKU."""
        stmt = select(CatalogProduct).where(CatalogProduct.sku == sku)
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def create_product(
        session: AsyncSession,
        category: str,
        sku: str,
        title: str,
        base_price_uzs: Decimal,
        quantity: int = 1,
        duration_months: Optional[int] = None,
        description: Optional[str] = None,
        badge_text: Optional[str] = None,
        display_order: int = 0
    ) -> CatalogProduct:
        product = CatalogProduct(
            category=category,
            sku=sku,
            title=title,
            base_price_uzs=base_price_uzs,
            quantity=quantity,
            duration_months=duration_months,
            description=description,
            badge_text=badge_text,
            display_order=display_order,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(product)
        await session.flush()
        logger.info(f"Catalog product created: {sku} ({title})")
        return product

    @staticmethod
    async def update_product(
        session: AsyncSession,
        product_id: int,
        **kwargs
    ) -> Optional[CatalogProduct]:
        product = await session.get(CatalogProduct, product_id)
        if not product:
            return None
        for k, v in kwargs.items():
            if hasattr(product, k) and v is not None:
                setattr(product, k, v)
        product.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return product

    @staticmethod
    async def delete_product(session: AsyncSession, product_id: int) -> bool:
        product = await session.get(CatalogProduct, product_id)
        if not product:
            return False
        await session.delete(product)
        await session.flush()
        return True

    @staticmethod
    async def ensure_default_catalog(session: AsyncSession) -> None:
        """Seeds default catalog if table is empty."""
        stmt = select(CatalogProduct).limit(1)
        res = await session.execute(stmt)
        if res.scalars().first() is None:
            now = datetime.now(timezone.utc)
            for item in DEFAULT_PRODUCTS:
                prod = CatalogProduct(
                    category=item["category"],
                    sku=item["sku"],
                    title=item["title"],
                    quantity=item["quantity"],
                    duration_months=item.get("duration_months"),
                    base_price_uzs=item["base_price_uzs"],
                    display_order=item["display_order"],
                    badge_text=item.get("badge_text", ""),
                    is_active=True,
                    created_at=now,
                    updated_at=now
                )
                session.add(prod)
            await session.flush()
            logger.info("Default GiftHub product catalog seeded successfully.")


catalog_service = CatalogService()
