from aiogram import Router
from aiogram.filters.command import Command
from aiogram.types import Message

router = Router()


@router.message(Command(commands=["help"]))
async def help(message: Message):
    text = ("Buyruqlar: ", "/start - Botni ishga tushirish", "/help - Yordam")

    await message.answer("\n".join(text))
