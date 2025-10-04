# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Router, F, types, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from tgbot.data.config import PATH_DATABASE
from tgbot.utils.misc.bot_filters import IsAdmin

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ====== Вспомогательные ======
def get_unpaid_summary():
    """Собираем список работников и сумм к выплате"""
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT w.id as worker_id, w.telegram_id, w.name, w.phone, SUM(t.amount) as total
            FROM transactions t
            JOIN workers w ON w.id = t.worker_id
            WHERE t.status='unpaid'
            GROUP BY w.id
            ORDER BY total DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def mark_paid(worker_id: int):
    """Отметить все транзакции работника как выплаченные"""
    now = int(dt.datetime.now().timestamp())
    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute(
            "UPDATE transactions SET status='paid', created_at=? WHERE worker_id=? AND status='unpaid'",
            (now, worker_id),
        )
        con.commit()
        return cur.rowcount  # сколько строк обновили


# ====== Хэндлеры ======
@router.message(F.text == "💰 Выплаты")
async def admin_payouts(message: types.Message):
    """Экран выплат для админа"""
    rows = get_unpaid_summary()
    if not rows:
        await message.answer("✅ Все выплаты произведены, задолженностей нет.")
        return

    text = "💰 <b>Невыплаченные суммы:</b>\n\n"
    kb = []
    for r in rows:
        text += f"👤 {r['name']} ({r['phone']}) — {r['total']} ₽\n"
        kb.append(
            [
                InlineKeyboardButton(
                    text=f"✅ Отметить {r['name']} ({r['total']} ₽)",
                    callback_data=f"admin_pay:{r['worker_id']}",
                )
            ]
        )

    await message.answer(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin_pay:"))
async def admin_pay(callback: CallbackQuery, bot: Bot):
    """Отметка выплат админом"""
    worker_id = int(callback.data.split(":")[1])
    count = mark_paid(worker_id)

    if count > 0:
        # достанем телеграм ID работника
        with sqlite3.connect(PATH_DATABASE) as con:
            con.row_factory = sqlite3.Row
            w = con.execute(
                "SELECT telegram_id, name FROM workers WHERE id=?", (worker_id,)
            ).fetchone()

        if w and w["telegram_id"]:
            try:
                await bot.send_message(
                    w["telegram_id"],
                    f"✅ Выплата произведена. Средства за {count} смен(ы) отмечены как выплаченные.",
                )
            except:
                pass

        await callback.answer(
            f"✅ Выплаты ({count} транзакций) отмечены!", show_alert=True
        )
        await callback.message.edit_text("Выплаты успешно отмечены. Обновите список.")
    else:
        await callback.answer("❗ Нет невыплаченных транзакций.", show_alert=True)
