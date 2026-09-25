from aiogram.types import InlineKeyboardMarkup

from app.keyboards.shop_keyboards import get_shop_main_menu


def get_main_menu_keyboard(is_admin: bool = False, services_count: int = 0) -> InlineKeyboardMarkup:
    """To'liq native Telegram Inline menyu tugmalari"""
    return get_shop_main_menu(is_admin=is_admin, services_count=services_count)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Faqat /admin komandasi orqali yuboriladigan inline boshqaruv klaviaturasi"""
    from app.keyboards.admin_keyboards import get_admin_main_keyboard
    return get_admin_main_keyboard()
