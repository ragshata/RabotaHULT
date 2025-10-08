# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import StatesGroup, State

from tgbot.data.config import PATH_DATABASE
from tgbot.utils.misc.bot_filters import IsAdmin

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ================= FSM =================
class EditOrder(StatesGroup):
    waiting_field = State()
    waiting_value = State()


# ================= Хэндлеры =================
@router.callback_query(F.data.startswith("admin_edit_order:"))
async def choose_edit(callback: CallbackQuery, state):
    order_id = int(callback.data.split(":")[1])
    await state.update_data(order_id=order_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🕒 Время", callback_data="edit_field:start_time"
                ),
                InlineKeyboardButton(
                    text="📍 Адрес", callback_data="edit_field:address"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Кол-во мест", callback_data="edit_field:places_total"
                ),
                InlineKeyboardButton(
                    text="⬅ Назад", callback_data=f"admin_order:{order_id}"
                ),
            ],
        ]
    )
    await callback.message.edit_text(
        f"✏️ Что редактируем в заказе #{order_id}?", reply_markup=kb
    )
    await state.set_state(EditOrder.waiting_field)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field:"))
async def ask_new_value(callback: CallbackQuery, state):
    field = callback.data.split(":")[1]
    await state.update_data(edit_field=field)

    if field == "start_time":
        await callback.message.answer(
            "⏰ Введите новую дату/время (формат: 15.09 09:00):"
        )
    elif field == "address":
        await callback.message.answer("📍 Введите новый адрес:")
    elif field == "places_total":
        await callback.message.answer("👥 Введите новое количество мест (1–20):")

    await state.set_state(EditOrder.waiting_value)
    await callback.answer()


@router.message(EditOrder.waiting_value)
async def save_edit_value(message: types.Message, state, bot):
    data = await state.get_data()
    order_id = data["order_id"]
    field = data["edit_field"]
    value = message.text.strip()

    # преобразования
    if field == "start_time":
        try:
            dt_obj = dt.datetime.strptime(value, "%d.%m %H:%M")
            dt_obj = dt_obj.replace(year=dt.datetime.now(TZ).year)
            value = int(dt_obj.timestamp())
        except Exception:
            await message.answer("⚠️ Неверный формат. Введите: 15.09 09:00")
            return
    elif field == "places_total":
        try:
            n = int(value)
            if not 1 <= n <= 20:
                raise ValueError
            value = n
        except Exception:
            await message.answer("⚠️ Нужно число от 1 до 20.")
            return

    # обновляем заказ
    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute(f"UPDATE orders SET {field}=? WHERE id=?", (value, order_id))
        con.commit()

        # находим назначенных работников
        workers = con.execute(
            """
            SELECT w.telegram_id FROM shifts s
            JOIN workers w ON w.id=s.worker_id
            WHERE s.order_id=? AND s.status IN ('accepted','arrived')
            """,
            (order_id,),
        ).fetchall()

    # уведомления
    field_map = {
        "start_time": "новое время",
        "address": "новый адрес",
        "places_total": "новое количество мест",
    }
    for w in workers:
        try:
            await bot.send_message(
                w["telegram_id"],
                f"⚠️ В заказ №{order_id} внесены изменения: {field_map[field]}.",
            )
        except Exception:
            pass

    await message.answer(f"✅ Заказ #{order_id} обновлён. Работники уведомлены.")
    await state.clear()
