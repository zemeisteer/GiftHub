from fastapi import FastAPI

from app.web.routes.admin import router as admin_router
from app.web.routes.health import router as health_router
from app.web.routes.orders import router as orders_router
from app.web.routes.payments import router as payments_router
from app.web.routes.products import router as products_router
from app.web.routes.users import router as users_router
from app.web.routes.webhooks import router as webhooks_router


def register_routes(app: FastAPI) -> None:
    """Registers all modular sub-routers onto the main FastAPI application."""
    app.include_router(health_router)
    app.include_router(webhooks_router)
    app.include_router(users_router)
    app.include_router(products_router)
    app.include_router(payments_router)
    app.include_router(orders_router)
    app.include_router(admin_router)
