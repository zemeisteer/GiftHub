from aiogram import Bot
from aiogram.types import BotCommand

async def set_bot_commands(bot: Bot):
    """
    Bot uchun qulay komandalar menyusini sozlash
    """
    commands = [
        BotCommand(command="start", description="⭐ Asosiy do'kon menyusi"),
        BotCommand(command="help", description="🛟 Yordam va ma'lumot"),
        BotCommand(command="admin", description="⚙️ Boshqaruv paneli (admin)")
    ]
    await bot.set_my_commands(commands=commands)