from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from data import config

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    web_url = config.get_web_app_url() if hasattr(config, "get_web_app_url") else config.WEB_APP_URL

    # Telegram WebAppInfo faqat HTTPS havolalarini qabul qiladi.
    if web_url.startswith("https://"):
        buttons.append([
            InlineKeyboardButton(
                text="⭐ Stellar Web App",
                web_app=WebAppInfo(url=web_url)
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="⭐ Stellar Web App (Brauzerda)",
                url=web_url
            )
        ])

    # Yangiliklar va Yordam (Support) faqat sozlangan bo'lsa chiqariladi
    extra_row = []
    if config.NEWS_CHANNEL_URL:
        extra_row.append(
            InlineKeyboardButton(
                text="📣 Yangiliklar",
                url=config.NEWS_CHANNEL_URL
            )
        )
    if config.SUPPORT_URL:
        support_link = config.SUPPORT_URL if config.SUPPORT_URL.startswith("http") else f"https://t.me/{config.SUPPORT_URL.lstrip('@')}"
        extra_row.append(
            InlineKeyboardButton(
                text="🛟 Yordam",
                url=support_link
            )
        )
    if extra_row:
        buttons.append(extra_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Faqat /admin komandasi orqali adminlarga yuboriladi"""
    buttons = []
    admin_url = config.get_admin_app_url() if hasattr(config, "get_admin_app_url") else config.ADMIN_APP_URL
    if admin_url.startswith("https://"):
        buttons.append([
            InlineKeyboardButton(
                text="⚙ Admin Panel (Web App)",
                web_app=WebAppInfo(url=admin_url)
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="⚙ Admin Panel (Brauzerda)",
                url=admin_url
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_gate_keyboard(channels: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in channels:
        if isinstance(ch, dict):
            title = ch.get("title") or ch.get("display_name") or ch.get("username_or_link") or "Kanalga a'zo bo'lish"
            link = ch.get("link") or ch.get("username_or_link") or "https://t.me"
        else:
            title = getattr(ch, "title", None) or getattr(ch, "username_or_link", None) or "Kanalga a'zo bo'lish"
            link = getattr(ch, "username_or_link", "https://t.me")

        if link and not str(link).startswith("http"):
            link = f"https://t.me/{str(link).lstrip('@')}"

        buttons.append([
            InlineKeyboardButton(
                text=f"➕ {title}",
                url=str(link)
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="✅ Tekshirish",
            callback_data="check_subscription"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
