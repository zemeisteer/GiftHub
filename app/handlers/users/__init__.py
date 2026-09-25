from aiogram import Dispatcher

from .admin_forward import router as admin_forward_router
from .admin_panel import router as admin_panel_router
from .help import router as help_router
from .orders import router as orders_router
from .profile import router as profile_router
from .shop import router as shop_router
from .start import router as user_router
from .wallet import router as wallet_router


def setup(dp: Dispatcher):
    dp.include_routers(
        user_router,
        shop_router,
        wallet_router,
        profile_router,
        orders_router,
        admin_panel_router,
        admin_forward_router,
        help_router
    )