# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from tgbot.data.config import PATH_DATABASE
from tgbot.routers.orders import get_worker
from tgbot.services.tz import TZ

router = Router()


# ====== Вспомогательные ======
def get_balance(user_id: int):
    """Получить баланс и историю транзакций работника"""
    worker = get_worker(user_id)
    if not worker:
        return 0, []

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Общий баланс (не выплачено)
        total = cur.execute(
            """
            SELECT COALESCE(SUM(amount),0) AS total
            FROM transactions
            WHERE worker_id=? AND status='unpaid'
            """,
            (worker["id"],),
        ).fetchone()["total"]

        # Последние 20 транзакций
        rows = cur.execute(
            """
            SELECT t.*, o.description, o.id as order_id
            FROM transactions t
            JOIN orders o ON o.id = t.order_id
            WHERE t.worker_id=?
            ORDER BY t.created_at DESC
            LIMIT 20
            """,
            (worker["id"],),
        ).fetchall()

    return total, rows


# ====== Хэндлеры ======
@router.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    """Отображение баланса и истории"""
    total, rows = get_balance(message.from_user.id)

    text = f"💰 <b>Итого к выплате:</b> {total} ₽\n\n📜 <b>История:</b>\n"
    if not rows:
        text += "— История пуста."
    else:
        for r in rows:
            date = dt.datetime.fromtimestamp(r["created_at"], TZ).strftime("%d.%m")
            status = "✅ выплачено" if r["status"] == "paid" else "⌛ не выплачено"
            text += f"— {date} | Заказ №{r['order_id']} | {r['amount']} ₽ | {status}\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ℹ️ Условия выплат", callback_data="payout_info")]
        ]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "payout_info")
async def payout_info(callback: CallbackQuery):
    """Информация о выплатах"""
    await callback.message.answer(
        "ℹ️ <b>Условия выплат</b>\n\n"
        "• Выплаты производятся по договорённости (СБП / карта / нал).\n"
        "• Срок — в конце смены или по согласованию с оператором.\n"
        "• Если заказ отменён из-за клиента — это <b>не влияет</b> на ваш рейтинг.",
        parse_mode="HTML",
    )
    await callback.answer()
