import urllib.parse
from typing import List, Dict, Any, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from data import config

def get_shop_main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="shop:stars"),
            InlineKeyboardButton(text="💎 Telegram Premium", callback_data="shop:premium")
        ],
        [
            InlineKeyboardButton(text="🎁 Raqamli Sovg'alar", callback_data="shop:gifts"),
            InlineKeyboardButton(text="💰 Hamyon / Balans", callback_data="wallet:view")
        ],
        [
            InlineKeyboardButton(text="👤 Profil & Referal", callback_data="profile:view"),
            InlineKeyboardButton(text="📋 Buyurtmalar", callback_data="orders:history")
        ],
        [
            InlineKeyboardButton(text="🛟 Yordam & Ma'lumot", callback_data="help:view")
        ]
    ]
    if is_admin:
        admin_url = config.get_admin_app_url() if hasattr(config, "get_admin_app_url") else config.ADMIN_APP_URL
        if admin_url and admin_url.startswith("https://"):
            buttons.append([
                InlineKeyboardButton(text="⚙️ Admin Boshqaruv Paneli (Web App)", web_app=WebAppInfo(url=admin_url))
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text="⚙️ Admin Boshqaruv Paneli (Web App)", url=admin_url or "https://t.me")
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


def get_stars_keyboard(packages: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for pkg in packages:
        stars = pkg["stars"]
        price = pkg["price_uzs"]
        row.append(
            InlineKeyboardButton(
                text=f"{stars} ⭐ ({price:,.0f} so'm)",
                callback_data=f"stars:pkg:{stars}"
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="✍️ Boshqa miqdor kiritish", callback_data="stars:custom")
    ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_recipient_keyboard(my_username: Optional[str] = None) -> InlineKeyboardMarkup:
    buttons = []
    if my_username:
        clean_user = my_username.lstrip("@")
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 O'zimga (@{clean_user})",
                callback_data=f"recipient:self:{clean_user}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="✍️ Boshqa do'stimga (@username)", callback_data="recipient:other")
    ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_purchase_keyboard(confirm_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Xaridni tasdiqlash", callback_data=f"buy:confirm:{confirm_data}")
        ],
        [
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="menu:main")
        ]
    ])


def get_premium_keyboard(premium_prices: Dict[str, Any]) -> InlineKeyboardMarkup:
    buttons = []
    durations = [
        ("3", "💎 3 oylik Premium"),
        ("6", "💎 6 oylik Premium"),
        ("12", "💎 12 oylik (1 yillik) Premium")
    ]
    for key, title in durations:
        price = premium_prices.get(key, 0)
        buttons.append([
            InlineKeyboardButton(
                text=f"{title} — {price:,.0f} so'm",
                callback_data=f"premium:pkg:{key}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_gifts_keyboard(gifts: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = []
    for g in gifts:
        icon = g.get("icon", "🎁")
        name = g.get("name", "Sovg'a")
        price = g.get("price_uzs", 0)
        gid = g.get("id", "gift")
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {name} — {price:,.0f} so'm",
                callback_data=f"gift:pkg:{gid}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Balansni to'ldirish", callback_data="wallet:topup")
        ],
        [
            InlineKeyboardButton(text="🧾 To'lovlar tarixi", callback_data="wallet:history"),
            InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
        ]
    ])


def get_topup_amounts_keyboard() -> InlineKeyboardMarkup:
    amounts = [10000, 25000, 50000, 100000, 200000, 500000]
    buttons = []
    row = []
    for amt in amounts:
        row.append(
            InlineKeyboardButton(
                text=f"{amt:,.0f} so'm",
                callback_data=f"topup:amt:{amt}"
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="✍️ Boshqa summa kiritish", callback_data="topup:custom")
    ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Hamyonga qaytish", callback_data="wallet:view")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_payment_methods_keyboard(
    amount: int,
    click_url: Optional[str] = None,
    payme_url: Optional[str] = None,
    card_active: bool = True
) -> InlineKeyboardMarkup:
    buttons = []
    
    if click_url:
        buttons.append([
            InlineKeyboardButton(text="🔵 Click orqali to'lash", url=click_url)
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🔵 Click orqali to'lash", callback_data=f"pay:click:{amount}")
        ])

    if payme_url:
        buttons.append([
            InlineKeyboardButton(text="🟢 Payme orqali to'lash", url=payme_url)
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🟢 Payme orqali to'lash", callback_data=f"pay:payme:{amount}")
        ])

    if card_active:
        buttons.append([
            InlineKeyboardButton(text="💳 Karta orqali to'lash (P2P / Chek)", callback_data=f"pay:card:{amount}")
        ])

    buttons.append([
        InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="wallet:view")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_receipt_upload_keyboard(amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📸 Chekni yubordim", callback_data=f"receipt:sent:{amount}")
        ],
        [
            InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="wallet:view")
        ]
    ])


def get_admin_receipt_approval_keyboard(tx_id: int, user_id: int, amount: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash (+ Balans)", callback_data=f"adm_chk:approve:{tx_id}:{user_id}:{int(amount)}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_chk:reject:{tx_id}:{user_id}:{int(amount)}")
        ]
    ])


def get_profile_keyboard(bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    share_text = f"⭐ Telegram Stars va Premium xizmatlarini eng arzon narxlarda xarid qiling! Havola orqali kiring: {ref_link}"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote(share_text)}"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔗 Do'stlarga ulashish", url=share_url)
        ],
        [
            InlineKeyboardButton(text="🎟 Promo-kod kiritish", callback_data="promo:enter")
        ],
        [
            InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
        ]
    ])


def get_back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
        ]
    ])


def get_insufficient_balance_keyboard(required_amount: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Hamyonni to'ldirish", callback_data="wallet:topup")
        ],
        [
            InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
        ]
    ])


def get_orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="orders:history")
        ],
        [
            InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")
        ]
    ])
