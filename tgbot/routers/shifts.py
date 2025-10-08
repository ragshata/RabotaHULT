# -*- coding: utf-8 -*-
import sqlite3
import datetime
import urllib.parse
from aiogram import Bot, Router, F
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message,
)
from tgbot.services.tz import TZ
from tgbot.data.config import PATH_DATABASE, get_admins
from tgbot.routers.orders import get_worker
from tgbot.services.broadcast import broadcast_order

router = Router()

# ================= Вспомогательные =================

RU_STATUS = {
    "accepted": "принял участие",
    "arrived": "прибыл",
    "done": "завершил",
    "no_show": "не явился",
    "cancelled": "отменён",
}


def get_shifts(user_id: int, status: str):
    """Получаем список смен по вкладке."""
    worker = get_worker(user_id)
    if not worker:
        return []

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        if status == "accepted":  # активные = accepted/arrived
            cur.execute(
                """
                SELECT s.*, o.description, o.address, o.district, o.start_time, o.format, o.features
                FROM shifts s
                JOIN orders o ON s.order_id = o.id
                WHERE s.worker_id = ? AND s.status IN ('accepted','arrived')
                ORDER BY o.start_time ASC
                """,
                (worker["id"],),
            )
        else:
            cur.execute(
                """
                SELECT s.*, o.description, o.address, o.district, o.start_time, o.format, o.features
                FROM shifts s
                JOIN orders o ON s.order_id = o.id
                WHERE s.worker_id = ? AND s.status = ?
                ORDER BY o.start_time ASC
                """,
                (worker["id"], status),
            )
        return [dict(r) for r in cur.fetchall()]


def format_time_until(start_time: int) -> str:
    dt = datetime.datetime.fromtimestamp(start_time, TZ)
    now = datetime.datetime.now(TZ)
    diff = dt - now
    if diff.total_seconds() > 0:
        h, m = divmod(int(diff.total_seconds()) // 60, 60)
        return f"Старт через {h}ч {m}м ({dt.strftime('%d.%m %H:%M')})"
    else:
        return f"Старт был {dt.strftime('%d.%m %H:%M')}"


def shift_button_text(s: dict) -> str:
    dt_str = datetime.datetime.fromtimestamp(s["start_time"], TZ).strftime("%d.%m %H:%M")
    return f"{dt_str} • {s['description']} • {RU_STATUS.get(s['status'], s['status'])}"


def format_shift_card(s: dict) -> str:
    start_str = format_time_until(s["start_time"])
    if s["format"] == "hour":
        rate = "400 ₽/час (мин. 4ч)"
    elif s["format"] == "shift8":
        rate = "3500 ₽ за 8ч"
    else:
        rate = "4800 ₽ за 12ч"

    return (
        f"📋 {s['description']}\n"
        f"📍 Адрес: {s['address']} ({s['district']})\n"
        f"⏰ {start_str}\n"
        f"⚙️ Формат: {s['format']}\n"
        f"💰 Ставка: {rate}\n"
        f"📊 Статус: {RU_STATUS.get(s['status'], s['status'])}\n"
        f"ℹ️ Особенности: {s.get('features','-')}"
    )


def shift_card_keyboard(s: dict):
    now = int(datetime.datetime.now(TZ).timestamp())
    start = s["start_time"]
    buttons = []

    # 📍 Я на месте (от -1ч до +1ч от старта)
    if s["status"] == "accepted" and start - 3600 <= now <= start + 3600:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="📍 Я на месте", callback_data=f"shift_arrive:{s['id']}"
                )
            ]
        )

    # ✅ Отработал
    if s["status"] in ("arrived", "accepted"):
        if s["format"] == "hour" and now >= start + 4 * 3600:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="✅ Отработал", callback_data=f"shift_done:{s['id']}"
                    )
                ]
            )
        elif s["format"] == "shift8" and now >= start + 8 * 3600:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="✅ Отработал", callback_data=f"shift_done:{s['id']}"
                    )
                ]
            )
        elif s["format"] == "day12" and now >= start + 12 * 3600:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="✅ Отработал", callback_data=f"shift_done:{s['id']}"
                    )
                ]
            )

    # ❌ Отказаться (только до старта)
    if s["status"] == "accepted" and now < start:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="❌ Отказаться", callback_data=f"shift_cancel:{s['id']}"
                )
            ]
        )

    # 🗺 Карта
    query = f"Екатеринбург {s['address']} {s['district']}"
    map_url = "https://yandex.ru/maps/?text=" + urllib.parse.quote(query)
    buttons.append([InlineKeyboardButton(text="🗺 Открыть адрес в картах", url=map_url)])

    # Назад
    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"shifts_tab:{s['status']}"
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ================= Хэндлеры =================


@router.message(F.text == "📅 Мои смены")
async def show_shifts_tabs(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 Активные", callback_data="shifts_tab:accepted"
                ),
                InlineKeyboardButton(
                    text="✅ Завершённые", callback_data="shifts_tab:done"
                ),
                InlineKeyboardButton(
                    text="❌ Отменённые", callback_data="shifts_tab:cancelled"
                ),
            ]
        ]
    )
    await message.answer("📅 Выберите вкладку:", reply_markup=kb)


@router.callback_query(F.data.startswith("shifts_tab:"))
async def show_shifts(callback: CallbackQuery):
    status = callback.data.split(":")[1]
    shifts = get_shifts(callback.from_user.id, status)
    title = {
        "accepted": "📌 Активные",
        "done": "✅ Завершённые",
        "cancelled": "❌ Отменённые",
    }.get(status)

    if not shifts:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="shifts_back")]
            ]
        )
        await callback.message.edit_text(
            f"{title}\n\n❗️ Нет смен в этой вкладке.", reply_markup=kb
        )
        return

    kb_rows = [
        [
            InlineKeyboardButton(
                text=shift_button_text(s), callback_data=f"shift_card:{s['id']}"
            )
        ]
        for s in shifts
    ]
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="shifts_back")])

    await callback.message.edit_text(
        title, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )


@router.callback_query(F.data == "shifts_back")
async def shifts_back(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 Активные", callback_data="shifts_tab:accepted"
                ),
                InlineKeyboardButton(
                    text="✅ Завершённые", callback_data="shifts_tab:done"
                ),
                InlineKeyboardButton(
                    text="❌ Отменённые", callback_data="shifts_tab:cancelled"
                ),
            ]
        ]
    )
    await callback.message.edit_text("📅 Выберите вкладку:", reply_markup=kb)


@router.callback_query(F.data.startswith("shift_card:"))
async def show_shift_card(callback: CallbackQuery):
    shift_id = int(callback.data.split(":")[1])
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        s = con.execute(
            "SELECT s.*, o.description, o.address, o.district, o.start_time, o.format, o.features "
            "FROM shifts s JOIN orders o ON s.order_id=o.id WHERE s.id=?",
            (shift_id,),
        ).fetchone()

    if not s:
        await callback.answer("Смена не найдена.", show_alert=True)
        return

    s = dict(s)
    await callback.message.edit_text(
        format_shift_card(s), reply_markup=shift_card_keyboard(s), parse_mode="HTML"
    )


# === 📍 Я на месте ===
@router.callback_query(F.data.startswith("shift_arrive:"))
async def shift_arrive(callback: CallbackQuery):
    shift_id = int(callback.data.split(":")[1])
    now = int(datetime.datetime.now(TZ).timestamp())

    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute(
            "UPDATE shifts SET status='arrived', arrived_at=? WHERE id=?",
            (now, shift_id),
        )
        con.commit()

    await callback.answer("📍 Прибытие отмечено!")
    await show_shift_card(callback)


# === ✅ Отработал ===
@router.callback_query(F.data.startswith("shift_done:"))
async def shift_done(callback: CallbackQuery):
    shift_id = int(callback.data.split(":")[1])
    now = int(datetime.datetime.now(TZ).timestamp())

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

        s = dict(s)
        # расчёт суммы
        if s["format"] == "hour":
            start_time = s.get("arrived_at") or s["start_time"]
            hours = max(4, -(-(now - start_time) // 3600))  # округление вверх
            amount = 400 * hours
        elif s["format"] == "shift8":
            amount = 3500
        else:
            amount = 4800

        cur.execute(
            "UPDATE shifts SET status='done', finished_at=? WHERE id=?", (now, shift_id)
        )
        cur.execute(
            "INSERT INTO transactions (worker_id, order_id, amount, status, created_at) VALUES (?, ?, ?, 'unpaid', ?)",
            (s["worker_id"], s["order_id"], amount, now),
        )
        con.commit()

    await callback.answer(
        f"✅ Отработано! Начислено {amount} ₽. Проверьте 💰 Баланс.", show_alert=True
    )
    await show_shift_card(callback)


# === ❌ Отказаться ===
@router.callback_query(F.data.startswith("shift_cancel:"))
async def shift_cancel(callback: CallbackQuery, bot: Bot):
    shift_id = int(callback.data.split(":")[1])
    now = int(datetime.datetime.now(TZ).timestamp())

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        s_row = cur.execute(
            "SELECT s.*, o.id AS order_id, o.start_time, o.places_taken, o.places_total, o.address, o.district, o.description "
            "FROM shifts s JOIN orders o ON s.order_id=o.id WHERE s.id=?",
            (shift_id,),
        ).fetchone()

        if not s_row:
            await callback.answer("Смена не найдена.", show_alert=True)
            return

        s = dict(s_row)

        if now >= s["start_time"]:
            await callback.answer(
                "❌ Нельзя отказаться после начала смены.", show_alert=True
            )
            return

        accepted_at = s.get("accepted_at") or 0
        penalty = -0.1 if (now - accepted_at) <= 2 * 3600 else -0.5
        was_full = s["places_taken"] >= s["places_total"]

        cur.execute(
            "UPDATE workers SET rating = rating + ? WHERE id=?",
            (penalty, s["worker_id"]),
        )
        cur.execute("UPDATE shifts SET status='cancelled' WHERE id=?", (shift_id,))
        cur.execute(
            "UPDATE orders SET places_taken = CASE WHEN places_taken>0 THEN places_taken-1 ELSE 0 END WHERE id=?",
            (s["order_id"],),
        )
        con.commit()

    msg = (
        "❌ Вы отказались от смены. Рейтинг снижен на 0.1."
        if penalty == -0.1
        else "❌ Вы отказались от смены. Рейтинг снижен на 0.5. Возможны ограничения."
    )
    await callback.answer(msg, show_alert=True)

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
        f"🕒 <b>Начало:</b> {datetime.datetime.fromtimestamp(s['start_time'], TZ).strftime('%d.%m %H:%M')}\n"
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
            await broadcast_order(bot, s["order_id"])
        except Exception:
            pass

    # вернём список смен
    await show_shifts(callback)
