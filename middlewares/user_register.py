from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from database import queries
from database.db import AsyncSessionLocal


class UserRegisterMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Any],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user and not user.is_bot:
            async with AsyncSessionLocal() as session:
                db_user = await queries.get_or_create_user(
                    session=session,
                    user_id=user.id,
                    first_name=user.first_name or "Foydalanuvchi",
                    last_name=user.last_name,
                    username=user.username,
                )
                data["db_user"] = db_user

        return await handler(event, data)
