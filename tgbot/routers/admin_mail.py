# -*- coding: utf-8 -*-
import asyncio
import sqlite3
from aiogram import Router, F, types, Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from tgbot.data.config import PATH_DATABASE, get_admins

router = Router()


# =================== Состояния ===================
class Broadcast(StatesGroup):
    waiting = State()


# =================== Старт рассылки ===================
@router.message(F.text == "📣 Рассылка")
async def start_broadcast(message: types.Message, state):
    await state.set_state(Broadcast.waiting)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
        ]
    )

    await message.answer(
        "📣 Отправьте сообщение для рассылки.\n\n"
        "Можно отправить текст, фото, видео, документ или голосовое сообщение — "
        "я разошлю его всем активным пользователям (кроме админов).",
        reply_markup=kb,
    )


# =================== Отмена рассылки ===================
@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(callback: types.CallbackQuery, state):
    await state.clear()
    await callback.answer("Рассылка отменена.")
    await callback.message.edit_text("❌ Рассылка отменена.")


# =================== Приём контента и рассылка ===================
@router.message(Broadcast.waiting)
async def handle_broadcast(message: types.Message, state, bot: Bot):
    # --- получаем всех активных пользователей ---
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT telegram_id FROM workers WHERE status='active' AND telegram_id IS NOT NULL"
        ).fetchall()

    recipients = [r["telegram_id"] for r in rows if r["telegram_id"]]

    # исключаем админов
    admin_ids = set(get_admins())
    recipients = [uid for uid in recipients if uid not in admin_ids]

    if not recipients:
        await state.clear()
        await message.answer("❗️ Нет активных пользователей для рассылки.")
        return

    # --- рассылаем пакетами ---
    success = 0
    failed = 0
    errors = []
    rate_limit = 20  # не более 20 сообщений в секунду

    for i, uid in enumerate(recipients, start=1):
        try:
            await message.copy_to(chat_id=uid)
            success += 1
        except Exception as e:
            failed += 1
            errors.append(str(e))

        if i % rate_limit == 0:
            await asyncio.sleep(1)

    await state.clear()

    # --- отчёт ---
    report = (
        "📣 <b>Рассылка завершена</b>\n\n"
        f"✅ Доставлено: <b>{success}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>\n"
        f"👥 Получателей: <b>{len(recipients)}</b>"
    )
    if errors:
        report += "\n\n<b>Примеры ошибок:</b>\n" + "\n".join(
            f"— {e}" for e in errors[:5]
        )

    await message.answer(report, parse_mode="HTML")
