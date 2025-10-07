# -*- coding: utf-8 -*-
import sqlite3
import datetime
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from tgbot.data.config import PATH_DATABASE, get_admins
from tgbot.services.broadcast import broadcast_order

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
async def cancel_shift(callback: CallbackQuery, bot: Bot):
    shift_id = int(callback.data.split(":")[1])
    now = int(datetime.datetime.now().timestamp())
    user_id = callback.from_user.id

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # тянем смену + заказ
        s_row = cur.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
        if not s_row:
            await callback.answer("Смена не найдена.", show_alert=True)
            return
        s = dict(s_row)

        o_row = cur.execute(
            "SELECT * FROM orders WHERE id=?", (s["order_id"],)
        ).fetchone()
        if not o_row:
            await callback.answer("Заказ не найден.", show_alert=True)
            return
        o = dict(o_row)

        # нельзя после старта
        if now >= o["start_time"]:
            await callback.answer(
                "❌ Нельзя отказаться после начала смены.", show_alert=True
            )
            return

        # штраф: <=2ч после записи — -0.1, позже — -0.5
        accepted_at = s.get("accepted_at") or 0
        penalty = -0.1 if (now - accepted_at) <= 2 * 3600 else -0.5

        # был ли заказ укомплектован до отказа?
        was_full = o["places_taken"] >= o["places_total"]

        # применяем
        cur.execute("UPDATE shifts SET status='cancelled' WHERE id=?", (shift_id,))
        cur.execute(
            "UPDATE workers SET rating = rating + ? WHERE id=?",
            (penalty, s["worker_id"]),
        )
        cur.execute(
            "UPDATE orders SET places_taken = CASE WHEN places_taken>0 THEN places_taken-1 ELSE 0 END WHERE id=?",
            (o["id"],),
        )
        con.commit()

    # ответ исполнителю
    msg = (
        "❌ Вы отказались от смены. Рейтинг снижен на 0.1."
        if penalty == -0.1
        else "❌ Вы отказались от смены. Рейтинг снижен на 0.5. Возможны ограничения."
    )
    await callback.answer(msg, show_alert=True)
    await callback.message.edit_text("Смена отменена.")

    # === уведомления админам ===
    admin_text = (
        f"⚠️ <b>Отказ исполнителя</b>\n\n"
        f"👷 <b>Worker ID:</b> {s['worker_id']}\n"
    )

    # достанем имя и телефон работника
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        worker = con.execute(
            "SELECT name, phone FROM workers WHERE id=?", (s["worker_id"],)
        ).fetchone()

    if worker:
        admin_text += f"👤 <b>Имя:</b> {worker['name']}\n📞 <b>Телефон:</b> {worker['phone']}\n\n"

    admin_text += (
        f"📦 <b>Заказ #{s['order_id']}</b>\n"
        f"📝 <b>Описание:</b> {s.get('description','—')}\n"
        f"📍 <b>Адрес:</b> {s.get('address','—')} ({s.get('district','—')})\n"
        f"🕒 <b>Начало:</b> {datetime.datetime.fromtimestamp(s['start_time']).strftime('%d.%m %H:%M')}\n"
        f"🔻 <b>Штраф:</b> {penalty}"
    )

    for admin_id in get_admins():
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass

    # автодобор, если было укомплектовано
    if was_full:
        try:
            await broadcast_order(bot, o["id"])
        except Exception:
            pass


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
