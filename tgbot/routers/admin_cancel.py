# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State

from tgbot.data.config import PATH_DATABASE
from tgbot.utils.misc.bot_filters import IsAdmin
from tgbot.utils.misc.bot_models import FSM

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# === FSM для причины отмены ===
class CancelFSM(StatesGroup):
    waiting_reason = State()


# === Кнопка "❌ Отменить заказ" в карточке заказа ===
@router.callback_query(F.data.startswith("admin_cancel_order:"))
async def admin_cancel_order(callback: CallbackQuery, state: FSM):
    order_id = int(callback.data.split(":")[1])
    await state.update_data(order_id=order_id)

    await callback.message.answer(f"❌ Укажите причину отмены заказа #{order_id}:")
    await state.set_state(CancelFSM.waiting_reason)
    await callback.answer()


# === Ввод причины отмены ===
@router.message(CancelFSM.waiting_reason)
async def admin_cancel_reason(message: Message, state: FSM, bot: Bot):
    data = await state.get_data()
    order_id = data.get("order_id")
    reason = message.text.strip()

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row

        # обновляем заказ
        con.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))

        # достаём всех исполнителей
        shifts = con.execute(
            """
            SELECT s.id, w.telegram_id
            FROM shifts s
            JOIN workers w ON w.id=s.worker_id
            WHERE s.order_id=? AND s.status IN ('accepted','arrived')
            """,
            (order_id,),
        ).fetchall()

        # снимаем работников без штрафа
        for s in shifts:
            con.execute("UPDATE shifts SET status='cancelled' WHERE id=?", (s["id"],))

            # уведомление
            try:
                text = (
                    f"❌ Заказ №{order_id} отменён администратором.\n"
                    f"Причина: {reason}\n\n"
                    f"Это не влияет на ваш рейтинг."
                )
                await bot.send_message(s["telegram_id"], text)
            except Exception:
                pass

        con.commit()

    await message.answer(f"✅ Заказ #{order_id} отменён с причиной: {reason}")
    await state.clear()
