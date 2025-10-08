# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Bot, Router, F
from aiogram.types import CallbackQuery

from tgbot.data.config import PATH_DATABASE, get_admins
from tgbot.services.broadcast import broadcast_order
from tgbot.services.tz import TZ

router = Router()


# ===== Вспомогательные =====
def _now_ts() -> int:
    return int(dt.datetime.now(TZ).timestamp())


async def _notify_admins(bot, text: str):
    """Уведомление всем админам"""
    for admin_id in get_admins():
        try:
            await bot.send_message(admin_id, text)
        except:
            pass


# ===== 📍 Я на месте =====
@router.callback_query(F.data.startswith("shift_arrive:"))
async def shift_arrive(callback: CallbackQuery, bot):
    shift_id = int(callback.data.split(":")[1])
    now = _now_ts()

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        s = cur.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
        if not s:
            await callback.answer("Смена не найдена.", show_alert=True)
            return
        if s["status"] != "accepted":
            await callback.answer("❗️ Уже отмечено.", show_alert=True)
            return

        # обновляем
        cur.execute(
            "UPDATE shifts SET status='arrived', arrived_at=? WHERE id=?",
            (now, shift_id),
        )

        # если первый прибыл — заказ становится started
        first = cur.execute(
            "SELECT 1 FROM shifts WHERE order_id=? AND status='arrived' LIMIT 1",
            (s["order_id"],),
        ).fetchone()
        if not first:
            cur.execute(
                "UPDATE orders SET status='started' WHERE id=?", (s["order_id"],)
            )
        con.commit()

    await callback.answer("📍 Прибытие отмечено!", show_alert=True)
    await callback.message.edit_text(
        "✅ Вы отметили прибытие.\nНе забудьте нажать «Отработал» по завершении."
    )

    # уведомляем админов
    await _notify_admins(
        bot,
        f"👷 Работник #{s['worker_id']} прибыл на смену (shift_id={shift_id}, order_id={s['order_id']})",
    )


# ===== ✅ Отработал =====
@router.callback_query(F.data.startswith("shift_done:"))
async def shift_done(callback: CallbackQuery, bot):
    shift_id = int(callback.data.split(":")[1])
    now = _now_ts()

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        s = cur.execute(
            "SELECT s.*, o.format, o.start_time, o.id as order_id "
            "FROM shifts s JOIN orders o ON s.order_id=o.id WHERE s.id=?",
            (shift_id,),
        ).fetchone()
        if not s:
            await callback.answer("Смена не найдена.", show_alert=True)
            return
        if s["status"] not in ("arrived", "accepted"):
            await callback.answer("Эта смена уже завершена.", show_alert=True)
            return

        start = s["arrived_at"] or s["start_time"]

        if s["format"] == "hour":
            hours = max(4, (now - start + 3599) // 3600)
            amount = hours * 400
        elif s["format"] == "shift8":
            amount = 3500
        else:
            amount = 4800

        cur.execute(
            "UPDATE shifts SET status='done', finished_at=?, amount=? WHERE id=?",
            (now, amount, shift_id),
        )
        cur.execute(
            "UPDATE workers SET balance = balance + ? WHERE id=?",
            (amount, s["worker_id"]),
        )
        cur.execute("UPDATE orders SET status='done' WHERE id=?", (s["order_id"],))
        con.commit()

    await callback.answer("✅ Смена завершена.", show_alert=True)
    await callback.message.edit_text(
        f"✅ Отработано. Начислено {amount} ₽. Проверьте 💰 Баланс."
    )

    # уведомляем админов
    await _notify_admins(
        bot,
        f"✅ Работник #{s['worker_id']} завершил смену. Начислено {amount} ₽ (shift_id={shift_id}, order_id={s['order_id']})",
    )


# ===== ❌ Отказаться =====
@router.callback_query(F.data.startswith("shift_cancel:"))
async def shift_cancel(callback: CallbackQuery, bot: Bot):
    shift_id = int(callback.data.split(":")[1])
    now = int(dt.datetime.now(TZ).timestamp())

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        s_row = cur.execute(
            "SELECT s.*, o.start_time, o.places_taken, o.places_total, o.address, o.district, o.description, o.id AS order_id "
            "FROM shifts s JOIN orders o ON s.order_id=o.id WHERE s.id=?",
            (shift_id,),
        ).fetchone()
        if not s_row:
            await callback.answer("Смена не найдена.", show_alert=True)
            return
        s = dict(s_row)

        if now >= s["start_time"]:
            await callback.answer("После старта отказаться нельзя.", show_alert=True)
            return

        accepted_at = s.get("accepted_at") or 0
        penalty = -0.1 if (now - accepted_at) <= 2 * 3600 else -0.5
        was_full = s["places_taken"] >= s["places_total"]

        cur.execute("UPDATE shifts SET status='cancelled' WHERE id=?", (shift_id,))
        cur.execute(
            "UPDATE workers SET rating = rating + ? WHERE id=?",
            (penalty, s["worker_id"]),
        )
        cur.execute(
            "UPDATE orders SET places_taken = CASE WHEN places_taken>0 THEN places_taken-1 ELSE 0 END WHERE id=?",
            (s["order_id"],),
        )
        con.commit()

    # ответ пользователю
    msg = (
        "❌ Вы отказались. Рейтинг −0.1."
        if penalty == -0.1
        else "❌ Поздний отказ. Рейтинг −0.5. Возможны ограничения."
    )
    await callback.answer(msg, show_alert=True)
    await callback.message.edit_text(msg)

    # === уведомления админам ===
    admin_text = (
        f"⚠️ <b>Отказ исполнителя</b>\n\n" f"👷 <b>Worker ID:</b> {s['worker_id']}\n"
    )

    # достанем имя и телефон работника
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        worker = con.execute(
            "SELECT name, phone FROM workers WHERE id=?", (s["worker_id"],)
        ).fetchone()

    if worker:
        admin_text += (
            f"👤 <b>Имя:</b> {worker['name']}\n📞 <b>Телефон:</b> {worker['phone']}\n\n"
        )

    admin_text += (
        f"📦 <b>Заказ #{s['order_id']}</b>\n"
        f"📝 <b>Описание:</b> {s.get('description','—')}\n"
        f"📍 <b>Адрес:</b> {s.get('address','—')} ({s.get('district','—')})\n"
        f"🕒 <b>Начало:</b> {dt.datetime.fromtimestamp(s['start_time'], TZ).strftime('%d.%m %H:%M')}\n"
        f"🔻 <b>Штраф:</b> {penalty}"
    )

    for admin_id in get_admins():
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass

    # автодобор при прежней укомплектованности
    if was_full:
        try:
            await broadcast_order(bot, s["order_id"])
        except Exception:
            pass
