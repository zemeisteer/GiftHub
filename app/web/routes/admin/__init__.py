from fastapi import APIRouter

from app.web.routes.admin.analytics import router as analytics_router
from app.web.routes.admin.broadcasts import router as broadcasts_router
from app.web.routes.admin.channels import router as channels_router
from app.web.routes.admin.orders import router as orders_router
from app.web.routes.admin.payments import router as payments_router
from app.web.routes.admin.pricing import router as pricing_router
from app.web.routes.admin.promos import router as promos_router
from app.web.routes.admin.referrals import router as referrals_router
from app.web.routes.admin.support import router as support_router
from app.web.routes.admin.system import router as system_router
from app.web.routes.admin.users import router as users_router

router = APIRouter(tags=["Admin"])

router.include_router(analytics_router)
router.include_router(orders_router)
router.include_router(users_router)
router.include_router(pricing_router)
router.include_router(payments_router)
router.include_router(promos_router)
router.include_router(referrals_router)
router.include_router(channels_router)
router.include_router(support_router)
router.include_router(broadcasts_router)
router.include_router(system_router)
