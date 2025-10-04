# -*- coding: utf-8 -*-
import sqlite3
import datetime
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from tgbot.data.config import PATH_DATABASE

router = Router()


# ================= Вспомогательные =================
def add_transaction(worker_id: int, order_id: int, amount: float):
    now = int(datetime.datetime.now().timestamp())
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            "INSERT INTO transactions (worker_id, order_id, amount, status, created_at) VALUES (?, ?, ?, 'unpaid', ?)",
            (worker_id, order_id, amount, now),
        )
        con.commit()


def update_rating(
    user_id: int, delta: float, block_days: int = 0, cooldown_hours: int = 0
):
    now = int(datetime.datetime.now().timestamp())
    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute(
            "UPDATE workers SET rating = rating + ? WHERE telegram_id=?",
            (delta, user_id),
        )
        if block_days > 0:
            cur.execute(
                "UPDATE workers SET blocked_until=? WHERE telegram_id=?",
                (now + block_days * 86400, user_id),
            )
        if cooldown_hours > 0:
            cur.execute(
                "UPDATE workers SET cooldown_until=? WHERE telegram_id=?",
                (now + cooldown_hours * 3600, user_id),
            )
        con.commit()


# ================= Обработчики =================
# 📍 Я на месте
@router.callback_query(F.data.startswith("shift_arrive:"))
async def mark_arrive(callback: CallbackQuery):
    shift_id = int(callback.data.split(":")[1])
    now = int(datetime.datetime.now().timestamp())

    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute(
            "UPDATE shifts SET status='arrived', start_time=? WHERE id=?",
            (now, shift_id),
        )
        cur.execute("SELECT order_id FROM shifts WHERE id=?", (shift_id,))
        order_id = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM shifts WHERE order_id=? AND status='arrived'",
            (order_id,),
        )
        if cur.fetchone()[0] == 1:
            cur.execute("UPDATE orders SET status='started' WHERE id=?", (order_id,))
        con.commit()

    await callback.answer("📍 Вы отметились как 'на месте'.", show_alert=True)
    await callback.message.edit_text(
        "Статус: прибыл\nНе забудьте нажать ✅ Отработал по завершении."
    )


# ✅ Отработал
@router.callback_query(F.data.startswith("shift_done:"))
async def mark_done(callback: CallbackQuery):
    shift_id = int(callback.data.split(":")[1])
    now = int(datetime.datetime.now().timestamp())

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        s = cur.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
        o = cur.execute("SELECT * FROM orders WHERE id=?", (s["order_id"],)).fetchone()

        amount = 0
        note = ""

        if o["format"] == "hour":
            start = s["start_time"]
            hours = max(4, (now - start) // 3600 + 1)
            amount = hours * 400
            note = f"Начислено: 400 ₽ × {hours} ч = {amount} ₽"
        elif o["format"] == "shift8":
            amount = 3500
            note = "Начислено: 3500 ₽ за смену."
        else:
            amount = 4800
            note = "Начислено: 4800 ₽ за день."

        add_transaction(s["worker_id"], o["id"], amount)
        cur.execute(
            "UPDATE shifts SET status='done', end_time=? WHERE id=?", (now, shift_id)
        )
        con.commit()

    await callback.answer("✅ Смена завершена.", show_alert=True)
    await callback.message.edit_text(note + "\nПроверьте 💰 Баланс.")


# ❌ Отказаться
@router.callback_query(F.data.startswith("shift_cancel:"))
async def cancel_shift(callback: CallbackQuery):
    shift_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    now = int(datetime.datetime.now().timestamp())

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        s = cur.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
        o = cur.execute("SELECT * FROM orders WHERE id=?", (s["order_id"],)).fetchone()

        accepted_at = o["start_time"] - 3 * 3600
        diff_hours = (now - accepted_at) / 3600

        delta, msg = 0, ""
        if diff_hours <= 2:
            delta = -0.1
            msg = "Вы отказались в течение 2 часов после записи. Рейтинг −0.1."
        elif now < o["start_time"]:
            delta = -0.5
            msg = "Вы отказались поздно. Рейтинг −0.5. Возможны ограничения на записи 24ч."
            update_rating(user_id, delta, cooldown_hours=24)
        else:
            delta = -1.0
            msg = "Неявка. Рейтинг −1.0. Блокировка 7 дней."
            update_rating(user_id, delta, block_days=7)

        if delta < 0:
            update_rating(user_id, delta)

        cur.execute("UPDATE shifts SET status='cancelled' WHERE id=?", (shift_id,))
        con.commit()

    await callback.answer(msg, show_alert=True)
    await callback.message.edit_text("Смена отменена.")


# ================= Автопометка "Неявка" =================
async def job_mark_no_shows_and_penalize(bot: Bot):
    """Вызывается из scheduler каждые 5 минут — помечает неявившихся через 15 минут после старта"""
    now = int(datetime.datetime.now().timestamp())
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # ищем активные смены, которые должны были начаться >15 минут назад, но без "arrived"
        shifts = cur.execute(
            """
            SELECT s.*, w.telegram_id
            FROM shifts s
            JOIN workers w ON s.worker_id=w.id
            JOIN orders o ON s.order_id=o.id
            WHERE s.status='accepted' AND o.start_time < ? - 900
            """,
            (now,),
        ).fetchall()

        for s in shifts:
            cur.execute("UPDATE shifts SET status='cancelled' WHERE id=?", (s["id"],))
            update_rating(s["telegram_id"], -1.0, block_days=7)

            try:
                await bot.send_message(
                    s["telegram_id"],
                    "❌ Вы не отметились в заказе в течение 15 минут после старта.\n"
                    "Статус: не явился.\n"
                    "Рейтинг −1.0, блокировка 7 дней.",
                )
            except Exception:
                pass

        con.commit()
