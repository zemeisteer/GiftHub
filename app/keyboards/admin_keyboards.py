from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Umumiy statistika", callback_data="admin:stats"),
                InlineKeyboardButton(text="📦 Kutilayotgan buyurtmalar", callback_data="admin:orders"),
            ],
            [
                InlineKeyboardButton(text="💵 Narxlarni sozlash", callback_data="admin:prices"),
                InlineKeyboardButton(text="📢 Majburiy kanallar", callback_data="admin:channels"),
            ],
            [
                InlineKeyboardButton(text="📢 Xabarnoma (Broadcast)", callback_data="admin:broadcast"),
                InlineKeyboardButton(text="💳 Karta sozlamalari", callback_data="admin:card"),
            ],
            [InlineKeyboardButton(text="🔙 Asosiy bot menyusi", callback_data="menu:main")],
        ]
    )


def get_admin_orders_keyboard(orders: list) -> InlineKeyboardMarkup:
    buttons = []
    for ord_item in orders[:8]:
        status_icon = "⏳" if ord_item.status == "pending" else ("✅" if ord_item.status == "done" else "❌")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{status_icon} #{ord_item.order_code} | {ord_item.item_title} ({ord_item.total_price:,.0f} so'm)",
                    callback_data=f"adm_ord:view:{ord_item.id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin:orders"),
            InlineKeyboardButton(text="🔙 Admin menyusi", callback_data="admin:menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_order_action_keyboard(order_id: int, is_service: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if is_service:
        rows.append([InlineKeyboardButton(text="🔗 Havola (Link) yuborish", callback_data=f"adm_srv:send:{order_id}")])
    rows.append(
        [
            InlineKeyboardButton(text="✅ Bajarildi deb belgilash", callback_data=f"adm_ord:done:{order_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish (+ Pul qaytarish)", callback_data=f"adm_ord:cancel:{order_id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🔙 Buyurtmalarga qaytish", callback_data="admin:orders")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_channels_keyboard(channels: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in channels:
        status = "🟢" if ch.is_active else "🔴"
        title = ch.title or ch.username_or_link
        buttons.append(
            [
                InlineKeyboardButton(text=f"{status} {title}", callback_data=f"adm_ch:view:{ch.id}"),
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"adm_ch:del:{ch.id}"),
            ]
        )
    buttons.append([InlineKeyboardButton(text="➕ Yangi kanal qo'shish", callback_data="adm_ch:add")])
    buttons.append([InlineKeyboardButton(text="🔙 Admin menyusi", callback_data="admin:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Admin panelga qaytish", callback_data="admin:menu")]]
    )
