# -*- coding: utf-8 -*-
import sqlite3
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from tgbot.data.config import PATH_DATABASE


def format_order_card(o: dict) -> str:
    return (
        f"📦 Новый заказ #{o['id']}\n"
        f"{o['description']}\n"
        f"Адрес: {o['address']} ({o['district']})\n"
        f"Старт: {o['start_time']:%d.%m %H:%M}\n"
        f"Формат: {o['format']}\n"
        f"Места: {o['places_taken']}/{o['places_total']}\n"
        f"Гражданство: {o['citizenship_required']}\n"
        f"Особенности: {o['features'] or '-'}"
    )


async def broadcast_order(bot: Bot, order_id: int):
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        o = cur.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            return
        o = dict(o)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Берусь", callback_data=f"order_take:{o['id']}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Пропустить", callback_data=f"order_skip:{o['id']}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📋 Подробнее", callback_data=f"order_card:{o['id']}"
                    )
                ],
            ]
        )

        # выбираем всех активных работников
        workers = cur.execute("SELECT * FROM workers WHERE status='active'").fetchall()
        for w in workers:
            # фильтр по гражданству
            if o["citizenship_required"] == "РФ" and w["citizenship"] != "РФ":
                continue
            if o["citizenship_required"] == "Иностранец" and w["citizenship"] == "РФ":
                continue

            try:
                await bot.send_message(
                    w["telegram_id"], format_order_card(o), reply_markup=kb
                )
            except Exception:
                pass
