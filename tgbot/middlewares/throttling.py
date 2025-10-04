# -*- coding: utf-8 -*-
import time
from typing import Any, Awaitable, Callable, Dict, Union

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import Message, User
from cachetools import TTLCache


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, default_rate: Union[int, float] = 1) -> None:
        self.default_rate = float(default_rate)
        # на пользователя держим окно в 10 минут
        self.users = TTLCache(maxsize=10_000, ttl=600)

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ):
        this_user: User = data.get("event_from_user")

        # ЭФФЕКТИВНАЯ скорость для ЭТОГО сообщения
        rate = get_flag(data, "rate")
        rate = float(rate) if rate is not None else self.default_rate

        # 1) Полный пропуск антиспама для альбомов (media groups)
        if isinstance(event, Message) and getattr(event, "media_group_id", None):
            return await handler(event, data)

        # 2) Явное отключение антиспама флагом
        if rate == 0:
            return await handler(event, data)

        now = int(time.time())
        info = self.users.get(this_user.id)

        if info is None:
            # первая активность за окно
            self.users[this_user.id] = {
                "last_ts": now,
                "count": 0,
                "rate": rate,
            }
            return await handler(event, data)

        # если прошло больше, чем rate — сбрасываем окно
        if now - info["last_ts"] >= info.get("rate", rate):
            self.users[this_user.id] = {
                "last_ts": now,
                "count": 0,
                "rate": rate,
            }
            return await handler(event, data)

        # внутри окна
        info["last_ts"] = now
        info["count"] = info.get("count", 0) + 1

        # допускаем небольшой «бёрст» (ещё 1 сообщение) без санкций
        if info["count"] <= 1:
            return await handler(event, data)

        # предупреждение на втором «лишнем»
        if info["count"] == 2:
            await event.reply(
                "<b>❗ Пожалуйста, не спамьте.\n" "❗ Please, do not spam.</b>"
            )
            return

        # всё последующее в окне — тихо глушим
        if info["count"] >= 3:
            # можно добавить одноразовое сообщение о блокировке, но лучше молча
            return
