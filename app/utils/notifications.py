import logging
from datetime import datetime
from typing import Optional, List
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from data import config

logger = logging.getLogger(__name__)

def get_store_keyboard() -> Optional[InlineKeyboardMarkup]:
    url = config.get_web_app_url() if hasattr(config, "get_web_app_url") else config.WEB_APP_URL
    if url and url.startswith("https://"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Do'konni ochish", web_app=WebAppInfo(url=url))]
        ])
    return None

def get_admin_keyboard() -> Optional[InlineKeyboardMarkup]:
    url = config.get_admin_app_url() if hasattr(config, "get_admin_app_url") else config.ADMIN_APP_URL
    if url and url.startswith("https://"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Admin Panel", web_app=WebAppInfo(url=url))]
        ])
    return None

async def send_topup_notification(
    bot: Optional[Bot],
    user_id: int,
    amount: float,
    method: str,
    new_balance: float
):
    if not bot:
        return
    try:
        method_names = {
            "click": "Click 💳",
            "payme": "Payme 💳",
            "autopaycard": "AutoPayCard 💳"
        }
        method_label = method_names.get(method.lower(), method.upper())
        text = (
            "💳 <b>Hamyon to'ldirildi!</b>\n\n"
            f"💰 <b>Qo'shilgan summa:</b> +{amount:,.0f} so'm\n"
            f"🏦 <b>To'lov usuli:</b> {method_label}\n"
            f"💵 <b>Joriy balans:</b> {new_balance:,.0f} so'm\n"
            f"📅 <b>Sana:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            "<i>Stars, Premium yoki sovg'alarni sotib olish uchun do'konga kiring!</i>"
        ).replace(",", " ")

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_store_keyboard()
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchiga to'ldirish xabarnomasi yuborilmadi ({user_id}): {e}")

def format_recipient_link(recipient: Optional[str]) -> str:
    if not recipient:
        return ""
    clean = recipient.strip()
    if clean.startswith("@"):
        uname = clean.lstrip("@")
        return f'<a href="https://t.me/{uname}">@{uname}</a>'
    elif clean.isdigit():
        return f'<a href="tg://user?id={clean}">ID: {clean}</a>'
    elif clean.lower().startswith("id:"):
        uid = clean[3:].strip()
        return f'<a href="tg://user?id={uid}">ID: {uid}</a>'
    else:
        return f'<a href="https://t.me/{clean}">@{clean}</a>'

async def send_order_created_notification(
    bot: Optional[Bot],
    user_id: int,
    order_code: str,
    item_title: str,
    amount: int,
    total_price: float,
    status: str,
    new_balance: float,
    recipient_username: Optional[str] = None,
    buyer_username: Optional[str] = None
):
    if not bot:
        return
    try:
        status_badges = {
            "done": "✅ Bajarildi",
            "pending": "⏳ Kutilmoqda",
            "cancel": "❌ Bekor qilindi"
        }
        status_label = status_badges.get(status, status)
        effective_recipient = recipient_username or (f"@{buyer_username}" if buyer_username else str(user_id))
        formatted_rcp = format_recipient_link(effective_recipient)
        recipient_line = f"🎯 <b>Qabul qiluvchi:</b> {formatted_rcp}\n" if formatted_rcp else ""

        text = (
            "🛍 <b>Yangi buyurtma qabul qilindi!</b>\n\n"
            f"🧾 <b>Buyurtma kodi:</b> <code>{order_code}</code>\n"
            f"📦 <b>Mahsulot:</b> {item_title}\n"
            f"🔢 <b>Miqdor:</b> {amount} dona\n"
            f"{recipient_line}"
            f"💵 <b>To'langan summa:</b> {total_price:,.0f} so'm\n"
            f"📊 <b>Holati:</b> {status_label}\n"
            f"💰 <b>Qolgan balans:</b> {new_balance:,.0f} so'm\n"
            f"📅 <b>Vaqt:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            "<i>Xaridingiz uchun tashakkur!</i>"
        ).replace(",", " ")

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_store_keyboard()
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchiga buyurtma xabarnomasi yuborilmadi ({user_id}): {e}")

async def send_admin_order_alert(
    bot: Optional[Bot],
    admin_ids: List[str],
    user_name: str,
    user_id: int,
    username: Optional[str],
    order_code: str,
    item_title: str,
    amount: int,
    total_price: float,
    cost_price: float,
    status: str,
    recipient_username: Optional[str] = None
):
    if not bot:
        return
    profit = total_price - cost_price
    user_tag = f"@{username}" if username else f"<code>{user_id}</code>"
    formatted_rcp = format_recipient_link(recipient_username)
    recipient_info = f"\n🎯 <b>Qabul qiluvchi:</b> {formatted_rcp}" if formatted_rcp else ""

    text = (
        "🔔 <b>YANGI XARID AMALGA OSHIRILDI!</b>\n\n"
        f"🧾 <b>Buyurtma:</b> <code>{order_code}</code>\n"
        f"👤 <b>Mijoz:</b> {user_name} ({user_tag})\n"
        f"📦 <b>Mahsulot:</b> {item_title} (x{amount}){recipient_info}\n"
        f"💰 <b>Tushum:</b> {total_price:,.0f} so'm\n"
        f"📉 <b>Tannarx:</b> {cost_price:,.0f} so'm\n"
        f"📈 <b>Sof foyda:</b> +{profit:,.0f} so'm\n"
        f"📊 <b>Holat:</b> {status.upper()}\n"
        f"📅 <b>Vaqt:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    ).replace(",", " ")

    for admin_id_str in admin_ids:
        try:
            admin_id = int(admin_id_str.strip())
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=get_admin_keyboard(),
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning(f"Adminga ({admin_id_str}) xabar yuborilmadi: {e}")

async def send_order_status_update_notification(
    bot: Optional[Bot],
    user_id: int,
    order_code: str,
    item_title: str,
    new_status: str,
    refund_amount: float = 0
):
    if not bot:
        return
    try:
        if new_status == "done":
            text = (
                "🎉 <b>Buyurtmangiz muvaffaqiyatli bajarildi!</b>\n\n"
                f"🧾 <b>Buyurtma:</b> <code>{order_code}</code>\n"
                f"📦 <b>Mahsulot:</b> {item_title}\n"
                "✅ <b>Holati:</b> Bajarildi\n\n"
                "<i>Stars/obuna hisobingizga muvaffaqiyatli yetkazildi. Bizni tanlaganingiz uchun rahmat!</i>"
            )
        elif new_status == "cancel":
            text = (
                "❌ <b>Buyurtmangiz bekor qilindi</b>\n\n"
                f"🧾 <b>Buyurtma:</b> <code>{order_code}</code>\n"
                f"📦 <b>Mahsulot:</b> {item_title}\n"
                f"💸 <b>Qaytarilgan summa:</b> +{refund_amount:,.0f} so'm\n\n"
                "<i>Mablag' hamyoningizga qaytarildi. Savollaringiz bo'lsa qo'llab-quvvatlash xizmatiga murojaat qiling.</i>"
            ).replace(",", " ")
        else:
            text = (
                f"ℹ️ <b>Buyurtma holati o'zgardi</b>\n\n"
                f"🧾 <b>Buyurtma:</b> <code>{order_code}</code>\n"
                f"📊 <b>Yangi holat:</b> {new_status}"
            )

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_store_keyboard()
        )
    except Exception as e:
        logger.warning(f"Buyurtma holati xabarnomasi yuborilmadi ({user_id}): {e}")

async def send_referral_reward_notification(
    bot: Optional[Bot],
    referrer_id: int,
    buyer_name: str,
    bonus_amount: float,
    new_balance: float
):
    if not bot:
        return
    try:
        text = (
            "🎁 <b>REFERAL BONUSI HISOBLANDI!</b>\n\n"
            f"👤 <b>Do'stingiz:</b> {buyer_name} do'konda xarid qildi.\n"
            f"💰 <b>Sizning bonusingiz:</b> +{bonus_amount:,.0f} so'm\n"
            f"💵 <b>Joriy balansingiz:</b> {new_balance:,.0f} so'm\n\n"
            "<i>Do'stlaringizni taklif qilishda davom eting va har bir xariddan foiz oling!</i>"
        ).replace(",", " ")

        await bot.send_message(
            chat_id=referrer_id,
            text=text,
            reply_markup=get_store_keyboard()
        )
    except Exception as e:
        logger.warning(f"Referal bonus xabarnomasi yuborilmadi ({referrer_id}): {e}")

async def send_promocode_notification(
    bot: Optional[Bot],
    user_id: int,
    code: str,
    message: str,
    new_balance: Optional[float] = None
):
    if not bot:
        return
    try:
        balance_info = f"\n💵 <b>Joriy balans:</b> {new_balance:,.0f} so'm".replace(",", " ") if new_balance is not None else ""
        text = (
            "🎟 <b>PROMO-KOD FAOLLASHTIRILDI!</b>\n\n"
            f"🏷 <b>Kod:</b> <code>{code.upper()}</code>\n"
            f"✨ {message}{balance_info}\n\n"
            "<i>Bizni tanlaganingiz uchun tashakkur!</i>"
        )
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_store_keyboard()
        )
    except Exception as e:
        logger.warning(f"Promo-kod xabarnomasi yuborilmadi ({user_id}): {e}")

