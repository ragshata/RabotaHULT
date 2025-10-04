# -*- coding: utf-8 -*-
import sqlite3
from aiogram import BaseMiddleware
from aiogram.types import User
from tgbot.data.config import PATH_DATABASE


class ExistsUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u: User | None = data.get("event_from_user")
        if not u or u.is_bot:
            return await handler(event, data)

        user_id = u.id
        user_login = (u.username or "").lower()

        with sqlite3.connect(PATH_DATABASE) as con:
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            row = cur.execute(
                "SELECT * FROM workers WHERE telegram_id=?", (user_id,)
            ).fetchone()

            if row is None:
                # создаём пустую запись, имя остаётся пустым (будет введено в регистрации)
                cur.execute(
                    """
                    INSERT INTO workers (
                        telegram_id, name, phone, city, district, citizenship,
                        telegram_login, created_at
                    )
                    VALUES (?, '', '', '', '', '', ?, strftime('%s','now'))
                    """,
                    (user_id, user_login),
                )
            else:
                # обновляем только telegram_login, но не имя
                if user_login and user_login != row["telegram_login"]:
                    cur.execute(
                        "UPDATE workers SET telegram_login=? WHERE telegram_id=?",
                        (user_login, user_id),
                    )

            con.commit()

        return await handler(event, data)
