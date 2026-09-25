import logging
import time
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import Message

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5):
        self.default_limit = rate_limit
        self.last_times: Dict[int, float] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Any],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        limit = get_flag(data, "throttling_rate_limit") or self.default_limit
        now = time.time()
        last_time = self.last_times.get(user.id, 0)

        if now - last_time < limit:
            logger.warning(f"⛔️ Throttled: {user.id} - too fast")
            await event.answer("🚫 Juda ko'p so'rov yuborildi. Iltimos, biroz kuting.")
            return

        self.last_times[user.id] = now
        return await handler(event, data)
